#!/usr/bin/env python3
"""
消息归档管理器
实现：实时归档、定期归档、归档查询、审计日志
"""

import os
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy import and_, or_, func
from sqlalchemy.orm import Session

from archive.archive_models import (
    ArchivedMessage, ArchivedUser, ArchivedRoom, 
    ArchivedFile, AuditLog, ArchiveConfig, Base
)

logger = logging.getLogger(__name__)


class ArchiveManager:
    """消息归档管理器"""
    
    def __init__(self, database_url: str):
        """
        初始化归档管理器
        
        Args:
            database_url: 归档数据库 URL
        """
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        
        # 创建表
        Base.metadata.create_all(bind=self.engine)
        logger.info("归档数据库表已初始化")
    
    def _get_session(self) -> Session:
        """获取数据库会话"""
        return self.SessionLocal()
    
    # ==================== 消息归档 ====================
    
    async def archive_message(self, message_data: dict, 
                             source_platform: str = "matrix") -> str:
        """
        归档单条消息
        
        Args:
            message_data: 消息数据
            source_platform: 来源平台（matrix/wecom）
        
        Returns:
            str: 归档消息 ID
        """
        message_id = str(uuid.uuid4())
        
        with self._get_session() as session:
            archived_msg = ArchivedMessage(
                id=message_id,
                message_id=message_data.get("message_id", message_id),
                external_message_id=message_data.get("external_message_id"),
                
                msg_type=message_data.get("msg_type", "text"),
                content=message_data.get("content"),
                content_json=message_data.get("content_json"),
                
                sender_id=message_data.get("sender_id"),
                sender_wecom_id=message_data.get("sender_wecom_id"),
                sender_external_id=message_data.get("sender_external_id"),
                sender_nickname=message_data.get("sender_nickname"),
                
                receiver_id=message_data.get("receiver_id"),
                receiver_wecom_id=message_data.get("receiver_wecom_id"),
                
                created_at=message_data.get("created_at", datetime.utcnow()),
                archived_at=datetime.utcnow(),
                
                source_platform=source_platform,
                source_room_id=message_data.get("source_room_id"),
                source_event_id=message_data.get("source_event_id"),
                
                archived_by="system"
            )
            
            session.add(archived_msg)
            session.commit()
            
            logger.info(f"消息已归档：{message_id}")
            return message_id
    
    async def archive_message_batch(self, messages: List[dict],
                                    source_platform: str = "matrix") -> int:
        """
        批量归档消息
        
        Args:
            messages: 消息列表
            source_platform: 来源平台
        
        Returns:
            int: 归档数量
        """
        count = 0
        
        with self._get_session() as session:
            for msg_data in messages:
                try:
                    message_id = str(uuid.uuid4())
                    
                    archived_msg = ArchivedMessage(
                        id=message_id,
                        message_id=msg_data.get("message_id", message_id),
                        msg_type=msg_data.get("msg_type", "text"),
                        content=msg_data.get("content"),
                        sender_id=msg_data.get("sender_id"),
                        receiver_id=msg_data.get("receiver_id"),
                        created_at=msg_data.get("created_at", datetime.utcnow()),
                        archived_at=datetime.utcnow(),
                        source_platform=source_platform,
                        archived_by="system"
                    )
                    
                    session.add(archived_msg)
                    count += 1
                    
                except Exception as e:
                    logger.error(f"批量归档消息失败：{e}")
            
            session.commit()
            
            logger.info(f"批量归档完成：{count} 条")
            return count
    
    async def archive_user(self, user_data: dict) -> str:
        """
        归档用户信息
        
        Args:
            user_data: 用户数据
        
        Returns:
            str: 归档用户 ID
        """
        user_id = str(uuid.uuid4())
        
        with self._get_session() as session:
            archived_user = ArchivedUser(
                id=user_id,
                matrix_user_id=user_data.get("matrix_user_id"),
                wecom_userid=user_data.get("wecom_userid"),
                external_userid=user_data.get("external_userid"),
                wecom_unionid=user_data.get("wecom_unionid"),
                nickname=user_data.get("nickname"),
                avatar_url=user_data.get("avatar_url"),
                phone=user_data.get("phone"),
                email=user_data.get("email"),
                user_type=user_data.get("user_type", "internal"),
                is_external=user_data.get("is_external", False),
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            session.add(archived_user)
            session.commit()
            
            logger.info(f"用户已归档：{user_id}")
            return user_id
    
    async def archive_room(self, room_data: dict) -> str:
        """
        归档房间信息
        
        Args:
            room_data: 房间数据
        
        Returns:
            str: 归档房间 ID
        """
        room_id = str(uuid.uuid4())
        
        with self._get_session() as session:
            archived_room = ArchivedRoom(
                id=room_id,
                room_id=room_data.get("room_id"),
                room_alias=room_data.get("room_alias"),
                room_name=room_data.get("room_name"),
                room_topic=room_data.get("room_topic"),
                is_public=room_data.get("is_public", False),
                wecom_group_id=room_data.get("wecom_group_id"),
                wecom_user_id=room_data.get("wecom_user_id"),
                room_type=room_data.get("room_type", "chat"),
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            session.add(archived_room)
            session.commit()
            
            logger.info(f"房间已归档：{room_id}")
            return room_id
    
    # ==================== 归档查询 ====================
    
    async def search_messages(self, 
                            sender_id: Optional[str] = None,
                            room_id: Optional[str] = None,
                            start_time: Optional[datetime] = None,
                            end_time: Optional[datetime] = None,
                            keyword: Optional[str] = None,
                            msg_type: Optional[str] = None,
                            limit: int = 100,
                            offset: int = 0) -> List[Dict[str, Any]]:
        """
        搜索归档消息
        
        Args:
            sender_id: 发送者 ID
            room_id: 房间 ID
            start_time: 开始时间
            end_time: 结束时间
            keyword: 关键词
            msg_type: 消息类型
            limit: 限制数量
            offset: 偏移量
        
        Returns:
            list: 消息列表
        """
        with self._get_session() as session:
            query = session.query(ArchivedMessage)
            
            # 构建查询条件
            conditions = []
            
            if sender_id:
                conditions.append(ArchivedMessage.sender_id == sender_id)
            
            if room_id:
                conditions.append(ArchivedMessage.source_room_id == room_id)
            
            if start_time:
                conditions.append(ArchivedMessage.created_at >= start_time)
            
            if end_time:
                conditions.append(ArchivedMessage.created_at <= end_time)
            
            if msg_type:
                conditions.append(ArchivedMessage.msg_type == msg_type)
            
            if keyword:
                # 全文搜索（PostgreSQL）
                conditions.append(ArchivedMessage.content.ilike(f"%{keyword}%"))
            
            if conditions:
                query = query.filter(and_(*conditions))
            
            # 排序和分页
            query = query.order_by(ArchivedMessage.created_at.desc())\
                         .limit(limit).offset(offset)
            
            results = query.all()
            
            # 转换为字典
            messages = []
            for msg in results:
                messages.append({
                    "id": msg.id,
                    "message_id": msg.message_id,
                    "msg_type": msg.msg_type,
                    "content": msg.content,
                    "sender_id": msg.sender_id,
                    "sender_nickname": msg.sender_nickname,
                    "receiver_id": msg.receiver_id,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                    "archived_at": msg.archived_at.isoformat() if msg.archived_at else None,
                    "is_recalled": msg.is_recalled,
                    "is_deleted": msg.is_deleted,
                    "source_platform": msg.source_platform,
                    "source_room_id": msg.source_room_id
                })
            
            return messages
    
    async def get_message_count(self,
                               sender_id: Optional[str] = None,
                               room_id: Optional[str] = None,
                               start_time: Optional[datetime] = None,
                               end_time: Optional[datetime] = None) -> int:
        """
        获取消息数量统计
        
        Args:
            sender_id: 发送者 ID
            room_id: 房间 ID
            start_time: 开始时间
            end_time: 结束时间
        
        Returns:
            int: 消息数量
        """
        with self._get_session() as session:
            query = session.query(func.count(ArchivedMessage.id))
            
            conditions = []
            
            if sender_id:
                conditions.append(ArchivedMessage.sender_id == sender_id)
            
            if room_id:
                conditions.append(ArchivedMessage.source_room_id == room_id)
            
            if start_time:
                conditions.append(ArchivedMessage.created_at >= start_time)
            
            if end_time:
                conditions.append(ArchivedMessage.created_at <= end_time)
            
            if conditions:
                query = query.filter(and_(*conditions))
            
            return query.scalar()
    
    async def get_message_statistics(self, 
                                    start_time: Optional[datetime] = None,
                                    end_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        获取消息统计信息
        
        Args:
            start_time: 开始时间
            end_time: 结束时间
        
        Returns:
            dict: 统计信息
        """
        with self._get_session() as session:
            # 总消息数
            total_count = session.query(func.count(ArchivedMessage.id)).scalar()
            
            # 按类型统计
            type_stats = session.query(
                ArchivedMessage.msg_type,
                func.count(ArchivedMessage.id)
            ).group_by(ArchivedMessage.msg_type).all()
            
            # 按发送者统计（Top 10）
            sender_stats = session.query(
                ArchivedMessage.sender_id,
                ArchivedMessage.sender_nickname,
                func.count(ArchivedMessage.id)
            ).group_by(
                ArchivedMessage.sender_id,
                ArchivedMessage.sender_nickname
            ).order_by(func.count(ArchivedMessage.id).desc())\
             .limit(10).all()
            
            # 撤回消息数
            recalled_count = session.query(func.count(ArchivedMessage.id)).filter(
                ArchivedMessage.is_recalled == True
            ).scalar()
            
            # 删除消息数
            deleted_count = session.query(func.count(ArchivedMessage.id)).filter(
                ArchivedMessage.is_deleted == True
            ).scalar()
            
            return {
                "total_count": total_count,
                "type_stats": {t[0]: t[1] for t in type_stats},
                "top_senders": [
                    {
                        "sender_id": s[0],
                        "sender_nickname": s[1],
                        "message_count": s[2]
                    }
                    for s in sender_stats
                ],
                "recalled_count": recalled_count,
                "deleted_count": deleted_count
            }
    
    # ==================== 审计日志 ====================
    
    async def log_audit(self,
                       operation: str,
                       resource_type: str,
                       resource_id: str,
                       operator_id: str,
                       operator_type: str = "system",
                       old_value: Optional[dict] = None,
                       new_value: Optional[dict] = None,
                       reason: Optional[str] = None,
                       ip_address: Optional[str] = None,
                       user_agent: Optional[str] = None) -> str:
        """
        记录审计日志
        
        Args:
            operation: 操作类型
            resource_type: 资源类型
            resource_id: 资源 ID
            operator_id: 操作者 ID
            operator_type: 操作者类型
            old_value: 旧值
            new_value: 新值
            reason: 原因
            ip_address: IP 地址
            user_agent: User-Agent
        
        Returns:
            str: 审计日志 ID
        """
        log_id = str(uuid.uuid4())
        
        with self._get_session() as session:
            audit_log = AuditLog(
                id=log_id,
                operation=operation,
                resource_type=resource_type,
                resource_id=resource_id,
                operator_id=operator_id,
                operator_type=operator_type,
                old_value=old_value,
                new_value=new_value,
                reason=reason,
                ip_address=ip_address,
                user_agent=user_agent,
                created_at=datetime.utcnow()
            )
            
            session.add(audit_log)
            session.commit()
            
            logger.info(f"审计日志已记录：{log_id} - {operation} {resource_type} {resource_id}")
            return log_id
    
    async def query_audit_logs(self,
                              operator_id: Optional[str] = None,
                              resource_type: Optional[str] = None,
                              operation: Optional[str] = None,
                              start_time: Optional[datetime] = None,
                              end_time: Optional[datetime] = None,
                              limit: int = 100,
                              offset: int = 0) -> List[Dict[str, Any]]:
        """
        查询审计日志
        
        Args:
            operator_id: 操作者 ID
            resource_type: 资源类型
            operation: 操作类型
            start_time: 开始时间
            end_time: 结束时间
            limit: 限制数量
            offset: 偏移量
        
        Returns:
            list: 审计日志列表
        """
        with self._get_session() as session:
            query = session.query(AuditLog)
            
            conditions = []
            
            if operator_id:
                conditions.append(AuditLog.operator_id == operator_id)
            
            if resource_type:
                conditions.append(AuditLog.resource_type == resource_type)
            
            if operation:
                conditions.append(AuditLog.operation == operation)
            
            if start_time:
                conditions.append(AuditLog.created_at >= start_time)
            
            if end_time:
                conditions.append(AuditLog.created_at <= end_time)
            
            if conditions:
                query = query.filter(and_(*conditions))
            
            query = query.order_by(AuditLog.created_at.desc())\
                         .limit(limit).offset(offset)
            
            results = query.all()
            
            logs = []
            for log in results:
                logs.append({
                    "id": log.id,
                    "operation": log.operation,
                    "resource_type": log.resource_type,
                    "resource_id": log.resource_id,
                    "operator_id": log.operator_id,
                    "operator_type": log.operator_type,
                    "reason": log.reason,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                    "ip_address": log.ip_address
                })
            
            return logs
    
    # ==================== 归档配置 ====================
    
    async def set_archive_config(self, key: str, value: dict, 
                                 description: str = "") -> bool:
        """
        设置归档配置
        
        Args:
            key: 配置键
            value: 配置值
            description: 描述
        
        Returns:
            bool: 是否成功
        """
        with self._get_session() as session:
            # 查找现有配置
            config = session.query(ArchiveConfig).filter(
                ArchiveConfig.config_key == key
            ).first()
            
            if config:
                # 更新
                config.config_value = value
                config.description = description
                config.updated_at = datetime.utcnow()
            else:
                # 创建
                config = ArchiveConfig(
                    config_key=key,
                    config_value=value,
                    description=description,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                session.add(config)
            
            session.commit()
            
            logger.info(f"归档配置已更新：{key}")
            return True
    
    async def get_archive_config(self, key: str) -> Optional[dict]:
        """
        获取归档配置
        
        Args:
            key: 配置键
        
        Returns:
            dict: 配置值或 None
        """
        with self._get_session() as session:
            config = session.query(ArchiveConfig).filter(
                ArchiveConfig.config_key == key
            ).first()
            
            if config:
                return config.config_value
            return None
