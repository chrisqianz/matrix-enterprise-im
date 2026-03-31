#!/usr/bin/env python3
"""
消息归档数据模型
设计原则：不可篡改、完整记录、支持审计
"""

from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, DateTime, Text, Boolean, 
    ForeignKey, Index, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class ArchivedMessage(Base):
    """归档消息表（核心）"""
    __tablename__ = "archived_messages"
    
    # 主键
    id = Column(String(64), primary_key=True)  # UUID
    
    # 消息标识
    message_id = Column(String(128), unique=True, nullable=False, index=True)  # 原始消息 ID
    external_message_id = Column(String(128), index=True)  # 企业微信消息 ID
    
    # 消息内容
    msg_type = Column(String(32), nullable=False)  # text/image/voice/video/file/link/event
    content = Column(Text)  # 消息内容
    content_html = Column(Text)  # HTML 格式内容
    content_json = Column(JSONB)  # 原始 JSON 内容
    
    # 发送者/接收者
    sender_id = Column(String(255), nullable=False, index=True)  # Matrix 用户 ID
    sender_wecom_id = Column(String(100), index=True)  # 企业微信用户 ID
    sender_external_id = Column(String(100), index=True)  # 外部联系人 ID
    sender_nickname = Column(String(255))  # 发送者昵称
    
    receiver_id = Column(String(255), nullable=False, index=True)  # 接收者（房间 ID 或用户 ID）
    receiver_wecom_id = Column(String(100), index=True)  # 企业微信接收者
    
    # 时间戳
    created_at = Column(DateTime, nullable=False, index=True)  # 创建时间
    archived_at = Column(DateTime, nullable=False, default=datetime.utcnow)  # 归档时间
    
    # 消息状态
    is_read = Column(Boolean, default=False)  # 是否已读
    is_recalled = Column(Boolean, default=False)  # 是否已撤回
    is_deleted = Column(Boolean, default=False)  # 是否已删除
    recall_time = Column(DateTime)  # 撤回时间
    delete_time = Column(DateTime)  # 删除时间
    
    # 文件信息
    file_url = Column(String(500))  # 文件 URL
    file_name = Column(String(255))  # 文件名称
    file_size = Column(Integer)  # 文件大小（字节）
    file_type = Column(String(100))  # 文件类型
    media_id = Column(String(255))  # 媒体 ID
    
    # 来源标识
    source_platform = Column(String(32), nullable=False)  # matrix/wecom
    source_room_id = Column(String(255), index=True)  # 来源房间 ID
    source_event_id = Column(String(255), index=True)  # Matrix 事件 ID
    
    # 审计信息
    archived_by = Column(String(100))  # 归档操作者
    audit_log = Column(JSONB)  # 审计日志
    
    # 索引
    __table_args__ = (
        Index('idx_created_at', 'created_at'),
        Index('idx_sender_created', 'sender_id', 'created_at'),
        Index('idx_room_created', 'source_room_id', 'created_at'),
    )


class ArchivedUser(Base):
    """归档用户表"""
    __tablename__ = "archived_users"
    
    id = Column(String(64), primary_key=True)
    
    # 用户标识
    matrix_user_id = Column(String(255), unique=True, nullable=False, index=True)
    wecom_userid = Column(String(100), index=True)
    external_userid = Column(String(100), index=True)
    wecom_unionid = Column(String(100))
    
    # 用户信息
    nickname = Column(String(255))
    avatar_url = Column(String(500))
    phone = Column(String(50))
    email = Column(String(255))
    
    # 用户类型
    user_type = Column(String(32))  # internal/external/bot
    is_external = Column(Boolean, default=False)
    
    # 状态
    is_active = Column(Boolean, default=True)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime)
    
    # 时间戳
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 索引
    __table_args__ = (
        Index('idx_wecom_userid', 'wecom_userid'),
        Index('idx_external_userid', 'external_userid'),
    )


class ArchivedRoom(Base):
    """归档房间表"""
    __tablename__ = "archived_rooms"
    
    id = Column(String(64), primary_key=True)
    
    # 房间标识
    room_id = Column(String(255), unique=True, nullable=False, index=True)
    room_alias = Column(String(255), unique=True, index=True)
    
    # 房间信息
    room_name = Column(String(500))
    room_topic = Column(String(1000))
    is_public = Column(Boolean, default=False)
    
    # 关联的企业微信信息
    wecom_group_id = Column(String(100), index=True)  # 企业微信群 ID
    wecom_user_id = Column(String(100), index=True)  # 私聊时关联的用户 ID
    
    # 房间类型
    room_type = Column(String(32))  # chat/group/bot
    
    # 状态
    is_active = Column(Boolean, default=True)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime)
    
    # 时间戳
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ArchivedFile(Base):
    """归档文件表"""
    __tablename__ = "archived_files"
    
    id = Column(String(64), primary_key=True)
    
    # 文件标识
    file_id = Column(String(255), unique=True, nullable=False, index=True)
    media_id = Column(String(255), index=True)
    message_id = Column(String(128), ForeignKey('archived_messages.message_id'), index=True)
    
    # 文件信息
    file_name = Column(String(500), nullable=False)
    file_type = Column(String(100))  # image/audio/video/file
    file_size = Column(Integer)  # 字节
    mime_type = Column(String(100))
    
    # 存储信息
    storage_type = Column(String(32))  # local/s3/oss
    storage_path = Column(String(1000))  # 存储路径
    download_url = Column(String(1000))  # 下载 URL
    thumbnail_url = Column(String(1000))  # 缩略图 URL
    
    # 关联信息
    sender_id = Column(String(255), index=True)
    room_id = Column(String(255), index=True)
    
    # 状态
    is_archived = Column(Boolean, default=True)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime)
    
    # 时间戳
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # 索引
    __table_args__ = (
        Index('idx_message_id', 'message_id'),
        Index('idx_sender_created', 'sender_id', 'created_at'),
    )


class AuditLog(Base):
    """审计日志表（不可篡改）"""
    __tablename__ = "audit_logs"
    
    id = Column(String(64), primary_key=True)
    
    # 操作信息
    operation = Column(String(64), nullable=False)  # create/update/delete/archive/query
    resource_type = Column(String(64), nullable=False)  # message/user/room/file
    resource_id = Column(String(255), nullable=False, index=True)
    
    # 操作者
    operator_id = Column(String(255), nullable=False, index=True)
    operator_type = Column(String(32))  # admin/auditor/system/user
    
    # 操作详情
    old_value = Column(JSONB)  # 旧值
    new_value = Column(JSONB)  # 新值
    reason = Column(Text)  # 操作原因
    
    # 时间戳
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # IP 地址
    ip_address = Column(String(50))
    user_agent = Column(String(500))
    
    # 索引
    __table_args__ = (
        Index('idx_resource', 'resource_type', 'resource_id'),
        Index('idx_operator', 'operator_id', 'created_at'),
    )


class ArchiveConfig(Base):
    """归档配置表"""
    __tablename__ = "archive_configs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 配置项
    config_key = Column(String(100), unique=True, nullable=False)
    config_value = Column(JSONB, nullable=False)
    
    # 配置说明
    description = Column(String(500))
    
    # 时间戳
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 索引
    __table_args__ = (
        Index('idx_config_key', 'config_key'),
    )
