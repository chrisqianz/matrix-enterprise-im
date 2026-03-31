#!/usr/bin/env python3
"""
企业微信 - Matrix 桥接服务（AppService 模式 v3.0 - 生产版）
完整实现：企业微信回调、虚拟用户、Portal 房间、消息双向同步、消息归档
修正（2026-03-30）：幂等性、真正用户创建、防回环、MessageMapping

核心修正：
1. ✅ Transaction 幂等性（txn_id 缓存）
2. ✅ 真正的用户创建（ensure_user_registered）
3. ✅ 正确的房间查询（portal_mapping）
4. ✅ 正确的路由逻辑（room_id → conversation → wecom_target）
5. ✅ 防回环机制（过滤 @wecom_* 用户）
6. ✅ MessageMapping（消息映射）
"""

import os
import logging
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Header, Query
from pydantic import BaseModel

from wecom_client import WecomClient
from matrix_appservice import MatrixAppService
from bridge.user_mapper import UserMapper
from bridge.puppet_manager import PuppetManager
from bridge.portal_manager import PortalManager
from bridge.message_sync import MessageSyncManager
from handlers.wecom_callback import WecomCallbackHandler
from archive.archive_manager import ArchiveManager
from archive.archive_api import router as archive_router

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 环境变量
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://wecom:***@wecom-db/wecom")
ARCHIVE_DATABASE_URL = os.getenv("ARCHIVE_DATABASE_URL", DATABASE_URL)
MATRIX_HOMESERVER = os.getenv("MATRIX_HOMESERVER", "http://synapse:8008")
MATRIX_DOMAIN = os.getenv("MATRIX_DOMAIN", "matrix.example.com")
AS_TOKEN=os.get...EN")
HS_TOKEN=os.get...EN")


class TransactionEvent(BaseModel):
    """AppService 事务事件"""
    type: str
    state_key: Optional[str] = None
    room_id: Optional[str] = None
    content: Dict[str, Any]
    sender: Optional[str] = None
    origin_server_ts: int
    event_id: Optional[str] = None


class Transaction(BaseModel):
    """AppService 事务"""
    events: List[TransactionEvent]
    timeout: int = 0


class WecomMessage(BaseModel):
    """发送消息请求"""
    to_user: str
    content: str
    msgtype: str = "text"


# ============================================================================
# ✅ 幂等性缓存（修正 1：Transaction 幂等性）
# ============================================================================

class IdempotencyCache:
    """幂等性缓存（防止重复处理）"""
    
    def __init__(self, ttl_seconds: int = 3600, max_size: int = 10000):
        self._txn_cache: Dict[str, datetime] = {}
        self._event_cache: Dict[str, datetime] = {}
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_size = max_size
    
    def _cleanup(self, cache: Dict[str, datetime]):
        """清理过期条目"""
        now = datetime.utcnow()
        expired = [k for k, v in cache.items() if now - v > self._ttl]
        for k in expired:
            del cache[k]
        
        # 如果超出容量，删除最早的条目
        if len(cache) > self._max_size:
            oldest = min(cache.items(), key=lambda x: x[1])
            del cache[oldest[0]]
    
    def check_txn(self, txn_id: str) -> bool:
        """
        检查 txn_id 是否已处理
        
        Returns:
            bool: True 如果已处理（应该跳过）
        """
        self._cleanup(self._txn_cache)
        
        if txn_id in self._txn_cache:
            logger.debug(f"Transaction 已处理，跳过：{txn_id}")
            return True
        
        self._txn_cache[txn_id] = datetime.utcnow()
        return False
    
    def check_event(self, event_id: str) -> bool:
        """
        检查 event_id 是否已处理
        
        Returns:
            bool: True 如果已处理（应该跳过）
        """
        self._cleanup(self._event_cache)
        
        if event_id in self._event_cache:
            logger.debug(f"Event 已处理，跳过：{event_id}")
            return True
        
        self._event_cache[event_id] = datetime.utcnow()
        return False


# 全局幂等性缓存
_idempotency_cache = IdempotencyCache()


# ============================================================================
# 应用生命周期管理
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理（修正版）"""
    logger.info("=" * 70)
    logger.info("企业微信桥接服务启动（AppService v3.0 - 生产版）")
    logger.info(f"Matrix Homeserver: {MATRIX_HOMESERVER}")
    logger.info(f"Matrix Domain: {MATRIX_DOMAIN}")
    logger.info("=" * 70)
    
    try:
        # 1. 初始化企业微信客户端
        app.state.wecom_client = WecomClient(
            corp_id=os.getenv("WECOMP_CORP_ID"),
            secret=os.get...T"),
            agent_id=int(os.getenv("WECOMP_AGENT_ID", "1000001"))
        )
        logger.info("✅ 企业微信客户端初始化完成")
        
        # 2. 初始化 Matrix AppService 客户端
        app.state.matrix_client = MatrixAppService(
            homeserver_url=MATRIX_HOMESERVER,
            as_token=***
            hs_token=***
        )
        logger.info("✅ Matrix AppService 客户端初始化完成")
        
        # 3. 初始化用户映射器
        app.state.user_mapper = UserMapper(DATABASE_URL)
        logger.info("✅ 用户映射器初始化完成")
        
        # 4. 初始化虚拟用户管理器（修正：传入 matrix_client）
        app.state.puppet_manager = PuppetManager(
            user_mapper=app.state.user_mapper,
            matrix_domain=MATRIX_DOMAIN,
            matrix_client=app.state.matrix_client  # ✅ 新增
        )
        logger.info("✅ 虚拟用户管理器初始化完成")
        
        # 5. 初始化 Portal 房间管理器（修正：传入 database_url）
        app.state.portal_manager = PortalManager(
            matrix_client=app.state.matrix_client,
            puppet_manager=app.state.puppet_manager,
            matrix_domain=MATRIX_DOMAIN,
            database_url=DATABASE_URL  # ✅ 新增
        )
        logger.info("✅ Portal 房间管理器初始化完成")
        
        # 6. 初始化消息同步管理器（修正：独立初始化）
        app.state.message_sync = MessageSyncManager(
            wecom_client=app.state.wecom_client,
            matrix_client=app.state.matrix_client,
            puppet_manager=app.state.puppet_manager,
            portal_manager=app.state.portal_manager,
            matrix_domain=MATRIX_DOMAIN
        )
        logger.info("✅ 消息同步管理器初始化完成")
        
        # 7. 初始化企业微信回调处理器
        app.state.wecom_handler = WecomCallbackHandler(app.state)
        logger.info("✅ 企业微信回调处理器初始化完成")
        
        # 8. 初始化归档管理器
        app.state.archive_manager = ArchiveManager(ARCHIVE_DATABASE_URL)
        logger.info("✅ 归档管理器初始化完成")
        
        logger.info("=" * 70)
        logger.info("所有模块初始化完成，服务启动成功")
        logger.info("=" * 70)
        
    except Exception as e:
        logger.error(f"初始化失败：{e}")
        raise
    
    yield
    
    logger.info("企业微信桥接服务关闭")


app = FastAPI(
    title="企业微信-Matrix 桥接服务（AppService v3.0 - 生产版）",
    description="完整实现：企业微信回调、虚拟用户、Portal 房间、消息双向同步、消息归档",
    version="3.0.0",
    lifespan=lifespan
)

# 注册归档路由
app.include_router(archive_router)


# ============================================================================
# 健康检查
# ============================================================================

@app.get("/")
async def root():
    """健康检查"""
    return {
        "status": "healthy",
        "service": "wecom-matrix-bridge",
        "version": "3.0.0 (AppService 生产版)",
        "features": [
            "✅ Transaction 幂等性",
            "✅ 真正的用户创建",
            "✅ 正确的房间查询",
            "✅ 正确的路由逻辑",
            "✅ 防回环机制",
            "✅ MessageMapping"
        ],
        "timestamp": datetime.now().isoformat()
    }


@app.get("/health")
async def health_check():
    """详细健康检查（优化版）"""
    result = {"status": "healthy"}
    
    # 1. 企业微信检查
    try:
        app.state.wecom_client._get_access_token()
        result["wecom"] = "ok"
    except Exception as e:
        result["wecom"] = f"error: {str(e)[:100]}"
        result["status"] = "unhealthy"
    
    # 2. Matrix 检查
    try:
        await app.state.matrix_client.get_account_status()
        result["matrix"] = "ok"
    except Exception as e:
        result["matrix"] = f"error: {str(e)[:100]}"
        result["status"] = "unhealthy"
    
    # 3. 数据库实际连接检查
    try:
        with app.state.user_mapper._get_session() as session:
            session.execute("SELECT 1")
        result["database"] = "ok"
    except Exception as e:
        result["database"] = f"error: {str(e)[:100]}"
        result["status"] = "unhealthy"
    
    # 4. 模块状态检查
    result["modules"] = {
        "puppet_manager": "ok" if hasattr(app.state, 'puppet_manager') else "missing",
        "portal_manager": "ok" if hasattr(app.state, 'portal_manager') else "missing",
        "message_sync": "ok" if hasattr(app.state, 'message_sync') else "missing",
        "wecom_handler": "ok" if hasattr(app.state, 'wecom_handler') else "missing",
        "archive_manager": "ok" if hasattr(app.state, 'archive_manager') else "missing",
    }
    
    result["timestamp"] = datetime.now().isoformat()
    
    return result


# ============================================================================
# AppService 端点（核心修正）
# ============================================================================

@app.put("/_matrix/app/v1/transactions/{txn_id}")
async def handle_transaction(
    txn_id: str,
    transaction: Transaction,
    authorization: Optional[str] = Header(None)
):
    """
    ✅ 核心端点：接收 Synapse 推送的事件（修正版）
    
    修正：
    1. Transaction 幂等性
    2. 防回环检查
    3. MessageMapping
    """
    logger.info(f"收到事务：{txn_id}, events={len(transaction.events)}")
    
    # 验证 HS Token
    if authorization != f"Bearer {HS_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid HS token")
    
    # ✅ 修正 1：检查 Transaction 幂等性
    if _idempotency_cache.check_txn(txn_id):
        logger.warning(f"Transaction 已处理过，跳过：{txn_id}")
        return {"pid": 1}
    
    # 处理每个事件
    success_count = 0
    fail_count = 0
    
    for event in transaction.events:
        try:
            if event.type == "m.room.message":
                await handle_matrix_message(event)
                success_count += 1
            elif event.type == "m.room.member":
                await handle_matrix_member_event(event)
                success_count += 1
            else:
                logger.debug(f"忽略事件类型：{event.type}")
        except Exception as e:
            logger.error(f"处理事件失败：{event.event_id} - {e}")
            fail_count += 1
    
    logger.info(f"事务处理完成：{txn_id}, success={success_count}, fail={fail_count}")
    
    # 返回成功
    return {"pid": 1}


@app.get("/_matrix/app/v1/users/{user_id:path}")
async def query_user(user_id: str):
    """
    ✅ 核心端点：查询用户是否存在（修正版）
    
    修正：
    - 真正的用户创建（ensure_user_registered）
    """
    # 检查是否是桥接用户
    if not (user_id.startswith("@wecom_") or user_id.startswith("@wecom_ext_")):
        return {"exists": False}
    
    if f":{MATRIX_DOMAIN}" not in user_id:
        return {"exists": False}
    
    # ✅ 修正 2：真正确保用户存在
    try:
        # 检查是否在 Matrix 中存在
        exists = await app.state.matrix_client.user_exists(user_id)
        
        if not exists:
            # 触发用户自动注册
            logger.info(f"触发用户注册：{user_id}")
            await app.state.matrix_client.ensure_user_registered(user_id)
        
        return {"exists": True}
        
    except Exception as e:
        logger.error(f"查询用户失败：{user_id} - {e}")
        return {"exists": False}


@app.get("/_matrix/app/v1/rooms/{room_alias:path}")
async def query_room(room_alias: str):
    """
    ✅ 核心端点：查询房间是否存在（修正版）
    
    修正：
    - 通过 portal_mapping 查询真实 room_id
    """
    # ✅ 修正 3：通过 portal_mapping 查询
    # 格式：#wecom_dm_zhangsan:matrix.example.com
    
    # 提取会话 ID
    if room_alias.startswith("#wecom_dm_"):
        conversation_id = f"dm_{room_alias[10:].split(':')[0]}"
    elif room_alias.startswith("#wecom_external_"):
        conversation_id = f"external_{room_alias[16:].split(':')[0]}"
    elif room_alias.startswith("#wecom_group_"):
        conversation_id = f"group_{room_alias[13:].split(':')[0]}"
    else:
        return {"room_id": ""}
    
    # 查询 portal_mapping
    mapping = await app.state.portal_manager.get_portal_by_conversation(conversation_id)
    
    if mapping and mapping.room_id:
        logger.info(f"查询房间：{room_alias} -> {mapping.room_id}")
        return {"room_id": mapping.room_id}
    else:
        logger.warning(f"房间不存在：{room_alias}")
        return {"room_id": ""}


# ============================================================================
# 事件处理（核心修正）
# ============================================================================

async def handle_matrix_message(event: TransactionEvent):
    """
    处理 Matrix 消息 → 转发到企业微信（修正版）
    
    ✅ 修正：
    1. 防回环检查（过滤 @wecom_* 用户）
    2. 正确的路由逻辑（room_id → conversation → wecom_target）
    3. MessageMapping
    4. Event 幂等性
    """
    room_id = event.room_id
    sender = event.sender
    content = event.content
    event_id = event.event_id
    
    logger.info(f"Matrix 消息：room={room_id}, sender={sender}, event_id={event_id}")
    
    # ✅ 修正 4：防回环检查（过滤桥接用户）
    if sender.startswith("@wecom_"):
        logger.debug(f"跳过桥接用户消息：{sender}")
        return
    
    # ✅ 修正 5：Event 幂等性
    if _idempotency_cache.check_event(event_id):
        logger.warning(f"Event 已处理过，跳过：{event_id}")
        return
    
    # 获取消息内容
    msgtype = content.get("msgtype", "m.text")
    body = content.get("body", "")
    
    if not body:
        logger.debug("消息内容为空，忽略")
        return
    
    # ✅ 修正 6：正确的路由逻辑（room_id → conversation → wecom_target）
    # 使用 MessageSyncManager 的修正版逻辑
    success = await app.state.message_sync.sync_matrix_to_wecom(
        room_id=room_id,
        sender=sender,
        content=body,
        event_id=event_id
    )
    
    if success:
        # ✅ 修正 7：创建 MessageMapping
        await app.state.user_mapper.create_message_mapping(
            matrix_event_id=event_id,
            matrix_room_id=room_id,
            matrix_sender=sender,
            direction="matrix_to_wecom",
            status="success"
        )
        
        logger.info(f"消息已同步到企业微信：{event_id}")
    else:
        # 记录失败
        await app.state.user_mapper.create_message_mapping(
            matrix_event_id=event_id,
            matrix_room_id=room_id,
            matrix_sender=sender,
            direction="matrix_to_wecom",
            status="failed"
        )
        
        logger.warning(f"同步到企业微信失败：{event_id}")


async def handle_matrix_member_event(event: TransactionEvent):
    """处理 Matrix 成员事件"""
    logger.info(f"成员事件：room={event.room_id}, state_key={event.state_key}, type={event.type}")
    
    # TODO: 实现成员同步逻辑
    # - 用户加入/退出房间
    # - 同步到企业微信（如果有需要）


# ============================================================================
# 企业微信回调（修正版）
# ============================================================================

@app.post("/wecom/callback")
async def wecom_callback(request: Request):
    """
    接收企业微信回调消息（修正版）
    
    ✅ 正确的签名验证参数
    ✅ 正确的 AES 解密
    ✅ 正确的 XML 字段
    """
    logger.info("收到企业微信回调")
    
    try:
        # 获取查询参数（签名验证用）
        query_params = dict(request.query_params)
        
        # 获取请求体
        body = await request.json()
        
        # 获取请求头
        headers = dict(request.headers)
        
        # 使用回调处理器（修正版）
        result = await app.state.wecom_handler.handle_callback(
            query_params=query_params,
            request_body=body,
            headers=headers
        )
        
        logger.info(f"企业微信回调处理完成：{result.get('errmsg', 'ok')}")
        return result
        
    except Exception as e:
        logger.error(f"企业微信回调处理失败：{e}")
        import traceback
        traceback.print_exc()
        return {"errcode": -1, "errmsg": str(e)}


# ============================================================================
# API 接口
# ============================================================================

@app.post("/api/send")
async def send_wecom_message(msg: WecomMessage):
    """发送消息到企业微信"""
    try:
        user = await app.state.user_mapper.get_wecom_user(msg.to_user)
        
        if user and user.is_external:
            result = app.state.wecom_client.send_message_to_external(
                external_userid=user.wecom_external_userid,
                content=msg.content
            )
        else:
            result = app.state.wecom_client.send_text_message(
                to_user=msg.to_user,
                content=msg.content
            )
        
        return {"status": "sent", "result": result}
    except Exception as e:
        logger.error(f"发送消息失败：{e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/puppets")
async def list_puppets(limit: int = 100, offset: int = 0):
    """列出所有虚拟用户"""
    puppets = await app.state.puppet_manager.list_all_puppets(limit, offset)
    return {"count": len(puppets), "puppets": puppets}


@app.get("/api/portals")
async def list_portals(limit: int = 100, offset: int = 0):
    """列出所有 Portal 房间"""
    portals = await app.state.portal_manager.list_all_portals(limit, offset)
    return {"count": len(portals), "portals": portals}


@app.get("/api/stats")
async def get_stats():
    """获取统计信息"""
    total_puppets = await app.state.puppet_manager.count_puppets()
    external_puppets = await app.state.puppet_manager.count_puppets(is_external=True)
    
    return {
        "total_puppets": total_puppets,
        "external_puppets": external_puppets,
        "internal_puppets": total_puppets - external_puppets
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
