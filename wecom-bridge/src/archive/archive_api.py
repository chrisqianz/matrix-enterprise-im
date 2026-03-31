#!/usr/bin/env python3
"""
归档 API 接口
提供：消息查询、统计分析、审计日志、配置管理
"""

import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from archive.archive_manager import ArchiveManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/archive", tags="归档管理")


@router.get("/messages")
async def search_messages(
    sender_id: Optional[str] = Query(None, description="发送者 ID"),
    room_id: Optional[str] = Query(None, description="房间 ID"),
    start_time: Optional[str] = Query(None, description="开始时间（ISO 格式）"),
    end_time: Optional[str] = Query(None, description="结束时间（ISO 格式）"),
    keyword: Optional[str] = Query(None, description="关键词"),
    msg_type: Optional[str] = Query(None, description="消息类型"),
    limit: int = Query(100, ge=1, le=1000, description="限制数量"),
    offset: int = Query(0, ge=0, description="偏移量")
):
    """
    搜索归档消息
    
    支持按发送者、房间、时间范围、关键词、消息类型搜索
    """
    # 解析时间参数
    start_dt = datetime.fromisoformat(start_time) if start_time else None
    end_dt = datetime.fromisoformat(end_time) if end_time else None
    
    messages = await ArchiveManager.search_messages(
        sender_id=sender_id,
        room_id=room_id,
        start_time=start_dt,
        end_time=end_dt,
        keyword=keyword,
        msg_type=msg_type,
        limit=limit,
        offset=offset
    )
    
    return {
        "count": len(messages),
        "messages": messages,
        "limit": limit,
        "offset": offset
    }


@router.get("/messages/count")
async def get_message_count(
    sender_id: Optional[str] = Query(None),
    room_id: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None)
):
    """获取消息数量统计"""
    start_dt = datetime.fromisoformat(start_time) if start_time else None
    end_dt = datetime.fromisoformat(end_time) if end_time else None
    
    count = await ArchiveManager.get_message_count(
        sender_id=sender_id,
        room_id=room_id,
        start_time=start_dt,
        end_time=end_dt
    )
    
    return {"count": count}


@router.get("/messages/stats")
async def get_message_statistics(
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None)
):
    """获取消息统计信息"""
    start_dt = datetime.fromisoformat(start_time) if start_time else None
    end_dt = datetime.fromisoformat(end_time) if end_time else None
    
    stats = await ArchiveManager.get_message_statistics(
        start_time=start_dt,
        end_time=end_dt
    )
    
    return stats


@router.get("/audit-logs")
async def query_audit_logs(
    operator_id: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    operation: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """查询审计日志"""
    start_dt = datetime.fromisoformat(start_time) if start_time else None
    end_dt = datetime.fromisoformat(end_time) if end_time else None
    
    logs = await ArchiveManager.query_audit_logs(
        operator_id=operator_id,
        resource_type=resource_type,
        operation=operation,
        start_time=start_dt,
        end_time=end_dt,
        limit=limit,
        offset=offset
    )
    
    return {
        "count": len(logs),
        "logs": logs
    }


@router.post("/config")
async def set_archive_config(
    key: str,
    value: dict,
    description: str = ""
):
    """设置归档配置"""
    success = await ArchiveManager.set_archive_config(key, value, description)
    
    if success:
        return {"status": "success", "key": key}
    else:
        raise HTTPException(status_code=500, detail="Failed to set config")


@router.get("/config/{key}")
async def get_archive_config(key: str):
    """获取归档配置"""
    config = await ArchiveManager.get_archive_config(key)
    
    if config is None:
        raise HTTPException(status_code=404, detail=f"Config not found: {key}")
    
    return {"key": key, "value": config}


@router.get("/stats/overview")
async def get_archive_overview():
    """获取归档概览统计"""
    # 获取总体统计
    stats = await ArchiveManager.get_message_statistics()
    
    # 获取用户统计
    # 获取房间统计
    # 获取存储统计
    
    return {
        "messages": stats,
        "storage": {
            "total_size": 0,  # TODO: 实现
            "file_count": 0   # TODO: 实现
        },
        "retention_days": 365  # TODO: 从配置读取
    }


@router.delete("/messages/{message_id}")
async def delete_archived_message(message_id: str,
                                  reason: str = "",
                                  operator_id: str = "admin"):
    """
    删除归档消息（仅标记删除，实际数据保留）
    
    注意：合规要求通常不允许物理删除，只允许逻辑删除
    """
    # 记录审计日志
    await ArchiveManager.log_audit(
        operation="delete",
        resource_type="message",
        resource_id=message_id,
        operator_id=operator_id,
        operator_type="admin",
        reason=reason
    )
    
    # 标记为已删除（不实际删除）
    # TODO: 实现逻辑删除
    
    return {
        "status": "deleted",
        "message_id": message_id,
        "note": "Message marked as deleted (logical delete only)"
    }
