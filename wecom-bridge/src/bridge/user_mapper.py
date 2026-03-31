#!/usr/bin/env python3
"""
用户映射模块（修正版 - Bridge State Store）
管理 Matrix 用户与企业微信用户的映射关系

核心修正（2026-03-30）：
1. ✅ 添加 user_type 字段（puppet/real/bot）
2. ✅ 添加 wecom_agentid 字段
3. ✅ 并发安全（UNIQUE 索引 + 异常处理）
4. ✅ 异步 SQLAlchemy（run_in_executor）
5. ✅ LRU 缓存层
6. ✅ 反查能力（唯一索引）
7. ✅ MessageMapping 表（新增）
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

logger = logging.getLogger(__name__)

Base = declarative_base()


class UserMapping(Base):
    """用户映射表：Matrix 用户 ↔ 企业微信用户（修正版）"""
    __tablename__ = "user_mapping"
    
    id = Column(String(64), primary_key=True)
    matrix_user_id = Column(String(255), nullable=False, index=True)
    wecom_userid = Column(String(100), index=True)  # 企业微信 userid
    wecom_external_userid = Column(String(100), index=True)  # 外部联系人 openid
    wecom_unionid = Column(String(100))  # 微信 unionid（如果有）
    wecom_agentid = Column(String(50), index=True)  # ✅ 新增：应用 agentid
    
    # ✅ 新增：用户类型
    user_type = Column(String(20), default="puppet")  # puppet, real, bot
    is_external = Column(Boolean, default=False)  # 是否是微信外部用户
    
    nickname = Column(String(255))  # 昵称
    avatar_url = Column(String(500))  # 头像 URL
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 软删除标志
    is_active = Column(Boolean, default=True)  # 是否活跃
    deleted_at = Column(DateTime)  # 删除时间
    
    # ✅ 唯一索引（并发安全）
    __table_args__ = (
        Index('idx_matrix_user_unique', 'matrix_user_id', unique=True),
        Index('idx_wecom_userid_unique', 'wecom_userid', 'wecom_agentid', unique=True),
        Index('idx_wecom_external_unique', 'wecom_external_userid', 'wecom_agentid', unique=True),
    )
    
    def __repr__(self):
        return f"<UserMapping matrix={self.matrix_user_id} wecom={self.wecom_userid} type={self.user_type} active={self.is_active}>"


class MessageMapping(Base):
    """消息映射表：Matrix 事件 ↔ 企业微信消息（新增）"""
    __tablename__ = "message_mapping"
    
    id = Column(String(64), primary_key=True)
    matrix_event_id = Column(String(255), unique=True, nullable=False, index=True)
    matrix_room_id = Column(String(255), index=True)
    matrix_sender = Column(String(255))
    
    wecom_msg_id = Column(String(100), index=True)  # 企业微信消息 ID
    wecom_conversation_id = Column(String(100), index=True)  # 会话 ID
    
    direction = Column(String(10), nullable=False)  # wecom_to_matrix, matrix_to_wecom
    status = Column(String(20), default="pending")  # pending, success, failed
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 唯一索引
    __table_args__ = (
        Index('idx_matrix_event_unique', 'matrix_event_id', unique=True),
    )
    
    def __repr__(self):
        return f"<MessageMapping matrix={self.matrix_event_id} wecom={self.wecom_msg_id} dir={self.direction}>"


class UserMapper:
    """用户映射管理器（修正版 - Bridge State Store）"""
    
    def __init__(
        self, 
        database_url: Optional[str] = None,
        cache_ttl_seconds: int = 300,
        cache_max_size: int = 3000  # 支持 200 客户端
    ):
        """
        初始化用户映射器
        
        Args:
            database_url: 数据库 URL
            cache_ttl_seconds: 缓存过期时间（秒）
            cache_max_size: 缓存最大容量
        """
        if database_url is None:
            database_url = os.getenv(
                "DATABASE_URL", 
                "postgresql://wecom:***@postgres-wecom/wecom"
            )
        
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        
        # ✅ LRU 缓存
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._cache_max_size = cache_max_size
        
        # 创建表
        Base.metadata.create_all(bind=self.engine)
        logger.info("用户映射表已初始化（带缓存和并发安全）")
    
    def _get_session(self) -> Session:
        """获取数据库会话"""
        return self.SessionLocal()
    
    # ============================================================================
    # ✅ 缓存层
    # ============================================================================
    
    def _cache_get(self, key: str) -> Optional[UserMapping]:
        """
        从缓存获取
        
        Args:
            key: 缓存键
            
        Returns:
            UserMapping 或 None
        """
        if key not in self._cache:
            return None
        
        cached = self._cache[key]
        if datetime.utcnow() - cached["cached_at"] > self._cache_ttl:
            del self._cache[key]
            return None
        
        return cached["value"]
    
    def _cache_set(self, key: str, value: UserMapping):
        """
        写入缓存
        
        Args:
            key: 缓存键
            value: 缓存值
        """
        # 如果缓存已满，删除最早的条目
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
    
    def _cache_clear(self):
        """清空缓存"""
        self._cache.clear()
    
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
    # UserMapping 查询
    # ============================================================================
    
    async def get_wecom_user(self, matrix_user_id: str) -> Optional[UserMapping]:
        """
        根据 Matrix 用户 ID 查找企业微信用户（修正版）
        
        ✅ 修正：
        - 使用缓存
        - 使用 run_in_executor
        - 只返回活跃记录
        
        Args:
            matrix_user_id: Matrix 用户 ID
        
        Returns:
            UserMapping 对象或 None
        """
        # ✅ 1. 检查缓存
        cached = self._cache_get(f"user_{matrix_user_id}")
        if cached:
            return cached
        
        # ✅ 2. 异步查询（不阻塞事件循环）
        def query_db():
            with self._get_session() as session:
                mapping = session.query(UserMapping).filter(
                    UserMapping.matrix_user_id == matrix_user_id,
                    UserMapping.is_active == True
                ).first()
                return mapping
        
        mapping = await self._run_in_executor(query_db)
        
        # ✅ 3. 写入缓存
        if mapping:
            self._cache_set(f"user_{matrix_user_id}", mapping)
        
        return mapping
    
    async def get_matrix_user(self, wecom_userid: str, agentid: Optional[str] = None) -> Optional[UserMapping]:
        """
        根据企业微信用户 ID 查找 Matrix 用户（修正版）
        
        ✅ 修正：
        - 支持 agentid 过滤
        - 反查能力（唯一索引）
        
        Args:
            wecom_userid: 企业微信 userid
            agentid: 应用 agentid（可选）
        
        Returns:
            UserMapping 对象或 None
        """
        # 检查缓存
        cache_key = f"wecom_{wecom_userid}_{agentid or ''}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        
        def query_db():
            with self._get_session() as session:
                query = session.query(UserMapping).filter(
                    UserMapping.wecom_userid == wecom_userid,
                    UserMapping.is_active == True
                )
                
                if agentid:
                    query = query.filter(UserMapping.wecom_agentid == agentid)
                
                return query.first()
        
        mapping = await self._run_in_executor(query_db)
        
        if mapping:
            self._cache_set(cache_key, mapping)
        
        return mapping
    
    async def get_external_contact(
        self, 
        external_userid: str, 
        agentid: Optional[str] = None
    ) -> Optional[UserMapping]:
        """
        根据外部联系人 ID 查找映射（修正版）
        
        Args:
            external_userid: 外部联系人 userid
            agentid: 应用 agentid（可选）
        
        Returns:
            UserMapping 对象或 None
        """
        cache_key = f"ext_{external_userid}_{agentid or ''}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        
        def query_db():
            with self._get_session() as session:
                query = session.query(UserMapping).filter(
                    UserMapping.wecom_external_userid == external_userid,
                    UserMapping.is_active == True
                )
                
                if agentid:
                    query = query.filter(UserMapping.wecom_agentid == agentid)
                
                return query.first()
        
        mapping = await self._run_in_executor(query_db)
        
        if mapping:
            self._cache_set(cache_key, mapping)
        
        return mapping
    
    # ============================================================================
    # UserMapping 创建（并发安全）
    # ============================================================================
    
    async def create_mapping(
        self, 
        matrix_user_id: str, 
        wecom_userid: str, 
        is_external: bool = False,
        nickname: Optional[str] = None,
        avatar_url: Optional[str] = None,
        agentid: Optional[str] = None,
        user_type: str = "puppet"
    ) -> UserMapping:
        """
        创建用户映射（修正版 - 并发安全）
        
        ✅ 修正：
        - UNIQUE 索引保证并发安全
        - 捕获 IntegrityError 返回现有记录
        - 添加 user_type 和 agentid
        
        Args:
            matrix_user_id: Matrix 用户 ID
            wecom_userid: 企业微信 userid
            is_external: 是否是外部联系人
            nickname: 昵称
            avatar_url: 头像 URL
            agentid: 应用 agentid
            user_type: 用户类型（puppet/real/bot）
        
        Returns:
            创建的 UserMapping 对象
        
        Raises:
            IntegrityError: 如果唯一约束冲突（应该被捕获处理）
        """
        def create_db():
            with self._get_session() as session:
                mapping = UserMapping(
                    id=str(uuid.uuid4()),
                    matrix_user_id=matrix_user_id,
                    wecom_userid=wecom_userid,
                    is_external=is_external,
                    nickname=nickname,
                    avatar_url=avatar_url,
                    wecom_agentid=agentid,
                    user_type=user_type
                )
                
                session.add(mapping)
                session.commit()
                session.refresh(mapping)
                
                return mapping
        
        try:
            mapping = await self._run_in_executor(create_db)
            
            # 清除缓存
            self._cache_delete(f"user_{matrix_user_id}")
            self._cache_delete(f"wecom_{wecom_userid}_{agentid or ''}")
            
            logger.info(f"创建用户映射：{matrix_user_id} -> {wecom_userid} (type={user_type})")
            return mapping
            
        except IntegrityError as e:
            # 并发创建，回滚后查询现有记录
            logger.warning(f"并发创建映射，查询现有记录：{matrix_user_id}")
            
            existing = await self.get_wecom_user(matrix_user_id)
            if existing:
                return existing
            
            raise
    
    async def link_external_contact(
        self, 
        matrix_user_id: str, 
        external_userid: str,
        unionid: Optional[str] = None,
        nickname: Optional[str] = None,
        avatar_url: Optional[str] = None,
        agentid: Optional[str] = None
    ) -> UserMapping:
        """
        关联外部联系人（修正版）
        
        Args:
            matrix_user_id: Matrix 用户 ID
            external_userid: 外部联系人 userid
            unionid: 微信 unionid
            nickname: 昵称
            avatar_url: 头像 URL
            agentid: 应用 agentid
        
        Returns:
            更新后的 UserMapping 对象
        """
        def update_db():
            with self._get_session() as session:
                mapping = session.query(UserMapping).filter(
                    UserMapping.matrix_user_id == matrix_user_id
                ).first()
                
                if mapping:
                    # 更新现有映射
                    mapping.wecom_external_userid = external_userid
                    mapping.wecom_unionid = unionid
                    mapping.is_external = True
                    mapping.wecom_agentid=***
                    if nickname:
                        mapping.nickname = nickname
                    if avatar_url:
                        mapping.avatar_url = avatar_url
                    mapping.updated_at = datetime.utcnow()
                else:
                    # 创建新映射
                    mapping = UserMapping(
                        id=str(uuid.uuid4()),
                        matrix_user_id=matrix_user_id,
                        wecom_external_userid=external_userid,
                        wecom_unionid=unionid,
                        is_external=True,
                        wecom_agentid=agentid,
                        nickname=nickname,
                        avatar_url=avatar_url,
                        user_type="puppet"
                    )
                    session.add(mapping)
                
                session.commit()
                session.refresh(mapping)
                
                return mapping
        
        mapping = await self._run_in_executor(update_db)
        
        # 清除缓存
        self._cache_delete(f"user_{matrix_user_id}")
        self._cache_delete(f"ext_{external_userid}_{agentid or ''}")
        
        logger.info(f"关联外部联系人：{matrix_user_id} -> {external_userid}")
        return mapping
    
    # ============================================================================
    # UserMapping 更新
    # ============================================================================
    
    async def update_user_info(
        self, 
        matrix_user_id: str, 
        nickname: Optional[str] = None,
        avatar_url: Optional[str] = None
    ) -> Optional[UserMapping]:
        """
        更新用户信息（修正版）
        
        Args:
            matrix_user_id: Matrix 用户 ID
            nickname: 昵称
            avatar_url: 头像 URL
        
        Returns:
            更新后的 UserMapping 对象或 None
        """
        def update_db():
            with self._get_session() as session:
                mapping = session.query(UserMapping).filter(
                    UserMapping.matrix_user_id == matrix_user_id
                ).first()
                
                if not mapping:
                    return None
                
                if nickname:
                    mapping.nickname = nickname
                if avatar_url:
                    mapping.avatar_url = avatar_url
                mapping.updated_at = datetime.utcnow()
                
                session.commit()
                session.refresh(mapping)
                
                return mapping
        
        mapping = await self._run_in_executor(update_db)
        
        if mapping:
            # 更新缓存
            self._cache_set(f"user_{matrix_user_id}", mapping)
        
        return mapping
    
    # ============================================================================
    # UserMapping 删除
    # ============================================================================
    
    async def soft_delete_mapping(self, matrix_user_id: str) -> bool:
        """
        软删除用户映射
        
        Args:
            matrix_user_id: Matrix 用户 ID
        
        Returns:
            是否成功删除
        """
        def delete_db():
            with self._get_session() as session:
                mapping = session.query(UserMapping).filter(
                    UserMapping.matrix_user_id == matrix_user_id
                ).first()
                
                if not mapping:
                    return False
                
                mapping.is_active = False
                mapping.deleted_at = datetime.utcnow()
                mapping.updated_at = datetime.utcnow()
                
                session.commit()
                
                return True
        
        result = await self._run_in_executor(delete_db)
        
        if result:
            # 清除缓存
            self._cache_delete(f"user_{matrix_user_id}")
            logger.info(f"软删除用户映射：{matrix_user_id}")
        
        return result
    
    # ============================================================================
    # MessageMapping 操作
    # ============================================================================
    
    async def create_message_mapping(
        self,
        matrix_event_id: str,
        matrix_room_id: str,
        matrix_sender: str,
        wecom_msg_id: Optional[str] = None,
        wecom_conversation_id: Optional[str] = None,
        direction: str = "wecom_to_matrix"
    ) -> MessageMapping:
        """
        创建消息映射
        
        Args:
            matrix_event_id: Matrix 事件 ID
            matrix_room_id: Matrix 房间 ID
            matrix_sender: Matrix 发送者
            wecom_msg_id: 企业微信消息 ID
            wecom_conversation_id: 企业微信会话 ID
            direction: 方向（wecom_to_matrix/matrix_to_wecom）
        
        Returns:
            MessageMapping 对象
        """
        def create_db():
            with self._get_session() as session:
                mapping = MessageMapping(
                    id=str(uuid.uuid4()),
                    matrix_event_id=matrix_event_id,
                    matrix_room_id=matrix_room_id,
                    matrix_sender=matrix_sender,
                    wecom_msg_id=wecom_msg_id,
                    wecom_conversation_id=wecom_conversation_id,
                    direction=direction,
                    status="pending"
                )
                
                session.add(mapping)
                session.commit()
                session.refresh(mapping)
                
                return mapping
        
        try:
            mapping = await self._run_in_executor(create_db)
            logger.debug(f"创建消息映射：{matrix_event_id} ({direction})")
            return mapping
        except IntegrityError as e:
            logger.warning(f"消息映射已存在：{matrix_event_id}")
            # 返回现有记录
            return await self.get_message_mapping(matrix_event_id)
    
    async def update_message_status(
        self, 
        matrix_event_id: str, 
        status: str
    ) -> bool:
        """
        更新消息状态
        
        Args:
            matrix_event_id: Matrix 事件 ID
            status: 状态（pending/success/failed）
        
        Returns:
            是否成功更新
        """
        def update_db():
            with self._get_session() as session:
                mapping = session.query(MessageMapping).filter(
                    MessageMapping.matrix_event_id == matrix_event_id
                ).first()
                
                if not mapping:
                    return False
                
                mapping.status = status
                mapping.updated_at = datetime.utcnow()
                
                session.commit()
                
                return True
        
        return await self._run_in_executor(update_db)
    
    async def get_message_mapping(self, matrix_event_id: str) -> Optional[MessageMapping]:
        """
        获取消息映射
        
        Args:
            matrix_event_id: Matrix 事件 ID
        
        Returns:
            MessageMapping 对象或 None
        """
        def query_db():
            with self._get_session() as session:
                return session.query(MessageMapping).filter(
                    MessageMapping.matrix_event_id == matrix_event_id
                ).first()
        
        return await self._run_in_executor(query_db)
    
    # ============================================================================
    # 统计和列表
    # ============================================================================
    
    async def list_all_mappings(
        self, 
        limit: int = 100, 
        offset: int = 0,
        user_type: Optional[str] = None
    ) -> List[UserMapping]:
        """
        列出所有用户映射
        
        Args:
            limit: 限制数量
            offset: 偏移量
            user_type: 用户类型过滤
        
        Returns:
            UserMapping 列表
        """
        def query_db():
            with self._get_session() as session:
                query = session.query(UserMapping).filter(
                    UserMapping.is_active == True
                )
                
                if user_type:
                    query = query.filter(UserMapping.user_type == user_type)
                
                return query.limit(limit).offset(offset).all()
        
        return await self._run_in_executor(query_db)
    
    async def count_mappings(
        self, 
        is_external: Optional[bool] = None,
        user_type: Optional[str] = None
    ) -> int:
        """
        统计用户映射数量
        
        Args:
            is_external: 是否只统计外部联系人
            user_type: 用户类型
        
        Returns:
            数量
        """
        def count_db():
            with self._get_session() as session:
                query = session.query(UserMapping).filter(
                    UserMapping.is_active == True
                )
                
                if is_external is not None:
                    query = query.filter(UserMapping.is_external == is_external)
                if user_type:
                    query = query.filter(UserMapping.user_type == user_type)
                
                return query.count()
        
        return await self._run_in_executor(count_db)
    
    # ============================================================================
    # 缓存管理
    # ============================================================================
    
    def clear_cache(self):
        """清空缓存"""
        self._cache_clear()
        logger.info("缓存已清空")
