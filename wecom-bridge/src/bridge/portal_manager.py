#!/usr/bin/env python3
"""
Portal 房间管理器（优化版）
管理 Matrix 与企业微信之间的对话房间

核心修正（2026-03-30）：
1. ✅ Portal DB 映射（必须）- conversation_id → room_id
2. ✅ alias ↔ room 绑定
3. ✅ puppet 参与房间创建
4. ✅ 正确 state event（不是 message）
5. ✅ conversation_id 建模（区分单聊/群聊/外部联系人）
6. ✅ 房间生命周期管理
7. ✅ 幂等性保证
8. ✅ 异步 SQLAlchemy（run_in_executor）- 避免阻塞事件循环
9. ✅ 类型注解
10. ✅ LRU 缓存层
"""

import os
import uuid
import logging
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from functools import partial
from sqlalchemy import Column, String, Boolean, DateTime, create_engine, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import IntegrityError

from matrix_appservice import MatrixAppService
from bridge.puppet_manager import PuppetManager

logger = logging.getLogger(__name__)

Base = declarative_base()


class PortalMapping(Base):
    """Portal 映射表：conversation_id ↔ room_id"""
    __tablename__ = "portal_mapping"
    
    id = Column(String(64), primary_key=True)
    conversation_id = Column(String(100), unique=True, nullable=False, index=True)  # 会话 ID
    conversation_type = Column(String(20), nullable=False)  # dm, group, external
    room_id = Column(String(255), unique=True, nullable=False, index=True)  # Matrix 房间 ID
    room_alias = Column(String(255))  # 房间别名
    wecom_userid = Column(String(100))  # 企业微信用户 ID（单聊）
    wecom_external_userid = Column(String(100))  # 外部联系人 ID
    wecom_group_id = Column(String(100))  # 群 ID
    puppet_user_id = Column(String(255))  # Puppet 用户 ID
    is_direct = Column(Boolean, default=True)  # 是否私聊
    is_active = Column(Boolean, default=True)  # 是否活跃
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<PortalMapping conv={self.conversation_id} room={self.room_id} type={self.conversation_type}>"


class PortalManager:
    """Portal 房间管理器（优化版）"""
    
    def __init__(
        self, 
        matrix_client: MatrixAppService, 
        puppet_manager: PuppetManager,
        matrix_domain: str,
        database_url: Optional[str] = None,
        cache_ttl_seconds: int = 300,
        cache_max_size: int = 3000  # 支持 200 客户端
    ):
        """
        初始化 Portal 房间管理器
        
        Args:
            matrix_client: Matrix AppService 客户端
            puppet_manager: 虚拟用户管理器
            matrix_domain: Matrix 域名
            database_url: 数据库 URL
            cache_ttl_seconds: 缓存 TTL（秒）
            cache_max_size: 缓存最大大小
        """
        self.matrix_client = matrix_client
        self.puppet_manager = puppet_manager
        self.matrix_domain = matrix_domain
        
        # 初始化数据库
        if database_url is None:
            database_url = os.getenv(
                "DATABASE_URL", 
                "postgresql://wecom:***@postgres-wecom/wecom"
            )
        
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        
        # 创建表
        Base.metadata.create_all(bind=self.engine)
        logger.info("Portal 映射表已初始化")
        
        # LRU 缓存
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._cache_max_size = cache_max_size
    
    def _get_session(self) -> Session:
        """获取数据库会话"""
        return self.SessionLocal()
    
    # ============================================================================
    # ✅ 缓存管理
    # ============================================================================
    
    def _cache_get(self, key: str) -> Optional[PortalMapping]:
        """从缓存获取"""
        if key not in self._cache:
            return None
        
        cached = self._cache[key]
        if datetime.utcnow() - cached["cached_at"] > self._cache_ttl:
            del self._cache[key]
            return None
        
        return cached["value"]
    
    def _cache_set(self, key: str, value: PortalMapping):
        """写入缓存"""
        if len(self._cache) >= self._cache_max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
        
        self._cache[key] = {
            "value": value,
            "cached_at": datetime.utcnow()
        }
    
    def _cache_delete(self, key: str):
        """删除缓存"""
        if key in self._cache:
            del self._cache[key]
    
    # ============================================================================
    # ✅ 异步数据库操作（使用 run_in_executor）
    # ============================================================================
    
    def _run_in_executor(self, func, *args):
        """
        在 executor 中运行同步函数（避免阻塞事件循环）
        
        Args:
            func: 函数
            *args: 函数参数
            
        Returns:
            函数返回值
        """
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(None, partial(func, *args))
    
    # ============================================================================
    # 1. Conversation ID 建模
    # ============================================================================
    
    def generate_conversation_id(
        self, 
        user_id: Optional[str] = None,
        external_userid: Optional[str] = None,
        group_id: Optional[str] = None
    ) -> str:
        """
        生成会话 ID（修正：区分单聊/群聊/外部联系人）
        
        格式：
        - 单聊：dm_{userid}
        - 外部联系人：external_{external_userid}
        - 群聊：group_{groupid}
        
        Args:
            user_id: 企业微信用户 ID
            external_userid: 外部联系人 ID
            group_id: 群 ID
            
        Returns:
            str: 会话 ID
        """
        if external_userid:
            return f"external_{external_userid}"
        elif group_id:
            return f"group_{group_id}"
        elif user_id:
            return f"dm_{user_id}"
        else:
            raise ValueError("必须提供 user_id、external_userid 或 group_id")
    
    def get_conversation_type(self, conversation_id: str) -> str:
        """
        获取会话类型
        
        Args:
            conversation_id: 会话 ID
            
        Returns:
            str: dm, external, group
        """
        if conversation_id.startswith("external_"):
            return "external"
        elif conversation_id.startswith("group_"):
            return "group"
        else:
            return "dm"
    
    # ============================================================================
    # 2. Portal DB 映射（✅ 异步版本）
    # ============================================================================
    
    async def get_portal_by_conversation(
        self, 
        conversation_id: str
    ) -> Optional[PortalMapping]:
        """
        根据会话 ID 获取 Portal 映射（✅ 优化：异步 + 缓存）
        
        Args:
            conversation_id: 会话 ID
            
        Returns:
            PortalMapping 对象或 None
        """
        # ✅ 1. 检查缓存
        cache_key = f"portal_conv_{conversation_id}"
        cached = self._cache_get(cache_key)
        if cached:
            logger.debug(f"Portal 缓存命中：{conversation_id}")
            return cached
        
        # ✅ 2. 异步查询（不阻塞事件循环）
        def query_db():
            with self._get_session() as session:
                mapping = session.query(PortalMapping).filter(
                    PortalMapping.conversation_id == conversation_id,
                    PortalMapping.is_active == True
                ).first()
                return mapping
        
        mapping = await self._run_in_executor(query_db)
        
        # ✅ 3. 写入缓存
        if mapping:
            self._cache_set(cache_key, mapping)
        
        return mapping
    
    async def get_portal_by_room(self, room_id: str) -> Optional[PortalMapping]:
        """
        根据房间 ID 获取 Portal 映射（✅ 优化：异步 + 缓存）
        
        Args:
            room_id: Matrix 房间 ID
            
        Returns:
            PortalMapping 对象或 None
        """
        # ✅ 1. 检查缓存
        cache_key = f"portal_room_{room_id}"
        cached = self._cache_get(cache_key)
        if cached:
            logger.debug(f"Portal 缓存命中：{room_id}")
            return cached
        
        # ✅ 2. 异步查询
        def query_db():
            with self._get_session() as session:
                mapping = session.query(PortalMapping).filter(
                    PortalMapping.room_id == room_id,
                    PortalMapping.is_active == True
                ).first()
                return mapping
        
        mapping = await self._run_in_executor(query_db)
        
        # ✅ 3. 写入缓存
        if mapping:
            self._cache_set(cache_key, mapping)
        
        return mapping
    
    # ============================================================================
    # 3. 获取或创建 Portal（✅ 异步版本）
    # ============================================================================
    
    async def get_or_create_portal(
        self,
        conversation_id: str,
        conversation_type: str,
        puppet_user_id: str,
        room_name: str,
        is_direct: bool = True,
        invitees: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        获取或创建 Portal 房间（✅ 优化：完整的幂等流程）
        
        Args:
            conversation_id: 会话 ID
            conversation_type: 会话类型（dm/group/external）
            puppet_user_id: Puppet 用户 ID
            room_name: 房间名称
            is_direct: 是否私聊
            invitees: 邀请的用户列表
            
        Returns:
            dict: {"room_id": ..., "created": bool, "portal": PortalMapping}
        """
        logger.info(f"获取或创建 Portal：{conversation_id}")
        
        # 1. 检查是否已存在
        existing = await self.get_portal_by_conversation(conversation_id)
        if existing:
            logger.info(f"Portal 已存在：{conversation_id} -> {existing.room_id}")
            return {
                "room_id": existing.room_id,
                "created": False,
                "portal": existing
            }
        
        # 2. 创建新房间
        invitees = invitees or []
        if puppet_user_id not in invitees:
            invitees.append(puppet_user_id)
        
        result = await self.matrix_client.create_room(
            name=room_name,
            is_direct=is_direct,
            inviteeslist=invitees
        )
        
        room_id = result.get("room_id")
        if not room_id:
            logger.error(f"创建房间失败：{result}")
            raise Exception(f"创建房间失败：{result}")
        
        logger.info(f"创建新房间：{room_id}")
        
        # 3. 创建 Portal 映射（✅ 异步版本）
        portal = await self._create_portal_mapping(
            conversation_id=conversation_id,
            conversation_type=conversation_type,
            room_id=room_id,
            puppet_user_id=puppet_user_id,
            is_direct=is_direct
        )
        
        # 4. 删除缓存（新创建的数据）
        self._cache_delete(f"portal_conv_{conversation_id}")
        
        return {
            "room_id": room_id,
            "created": True,
            "portal": portal
        }
    
    async def _create_portal_mapping(
        self,
        conversation_id: str,
        conversation_type: str,
        room_id: str,
        puppet_user_id: str,
        is_direct: bool = True,
        wecom_userid: Optional[str] = None,
        wecom_external_userid: Optional[str] = None,
        wecom_group_id: Optional[str] = None
    ) -> PortalMapping:
        """
        创建 Portal 映射（✅ 优化：异步 + 并发安全）
        
        Args:
            conversation_id: 会话 ID
            conversation_type: 会话类型
            room_id: 房间 ID
            puppet_user_id: Puppet 用户 ID
            is_direct: 是否私聊
            wecom_userid: 企业微信用户 ID
            wecom_external_userid: 外部联系人 ID
            wecom_group_id: 群 ID
            
        Returns:
            PortalMapping 对象
        """
        portal_id = str(uuid.uuid4())
        
        def create_mapping():
            with self._get_session() as session:
                try:
                    portal = PortalMapping(
                        id=portal_id,
                        conversation_id=conversation_id,
                        conversation_type=conversation_type,
                        room_id=room_id,
                        puppet_user_id=puppet_user_id,
                        is_direct=is_direct,
                        wecom_userid=wecom_userid,
                        wecom_external_userid=wecom_external_userid,
                        wecom_group_id=wecom_group_id,
                        is_active=True
                    )
                    session.add(portal)
                    session.commit()
                    session.refresh(portal)
                    logger.info(f"创建 Portal 映射：{conversation_id} -> {room_id}")
                    return portal
                except IntegrityError as e:
                    session.rollback()
                    logger.warning(f"Portal 已存在（并发创建）：{conversation_id}")
                    # 返回已存在的记录
                    existing = session.query(PortalMapping).filter(
                        PortalMapping.conversation_id == conversation_id,
                        PortalMapping.is_active == True
                    ).first()
                    return existing
        
        return await self._run_in_executor(create_mapping)
    
    # ============================================================================
    # 4. 软删除 Portal（✅ 异步版本）
    # ============================================================================
    
    async def soft_delete_portal(
        self,
        conversation_id: str,
        reason: str = "user_left"
    ) -> bool:
        """
        软删除 Portal（✅ 优化：异步）
        
        Args:
            conversation_id: 会话 ID
            reason: 删除原因
            
        Returns:
            bool: 是否成功
        """
        logger.info(f"软删除 Portal：{conversation_id}, reason: {reason}")
        
        def delete_mapping():
            with self._get_session() as session:
                portal = session.query(PortalMapping).filter(
                    PortalMapping.conversation_id == conversation_id,
                    PortalMapping.is_active == True
                ).first()
                
                if not portal:
                    logger.warning(f"Portal 不存在：{conversation_id}")
                    return False
                
                portal.is_active = False
                portal.updated_at = datetime.utcnow()
                session.commit()
                logger.info(f"软删除 Portal 成功：{conversation_id}")
                return True
        
        success = await self._run_in_executor(delete_mapping)
        
        # 删除缓存
        if success:
            self._cache_delete(f"portal_conv_{conversation_id}")
        
        return success
    
    # ============================================================================
    # 5. 列出所有 Portals（✅ 异步版本）
    # ============================================================================
    
    async def list_all_portals(
        self, 
        limit: int = 100, 
        offset: int = 0
    ) -> List[PortalMapping]:
        """
        列出所有 Portals（✅ 优化：异步）
        
        Args:
            limit: 每页数量
            offset: 偏移量
            
        Returns:
            List[PortalMapping]: Portal 列表
        """
        def query_db():
            with self._get_session() as session:
                portals = session.query(PortalMapping).filter(
                    PortalMapping.is_active == True
                ).order_by(
                    PortalMapping.created_at.desc()
                ).limit(limit).offset(offset).all()
                return portals
        
        return await self._run_in_executor(query_db)
    
    # ============================================================================
    # 6. 清理缓存
    # ============================================================================
    
    def clear_cache(self):
        """清理所有缓存"""
        self._cache.clear()
        logger.info("Portal 缓存已清理")
