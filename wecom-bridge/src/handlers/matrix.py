#!/usr/bin/env python3
"""
Matrix 消息处理
处理从 Matrix 发送到企业微信的消息
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class MatrixMessageRequest(BaseModel):
    """Matrix 消息请求"""
    room_id: str
    event_id: str
    sender: str
    content: dict


@router.post("/message")
async def handle_matrix_message(request: MatrixMessageRequest):
    """
    处理 Matrix 消息，转发到企业微信
    
    流程:
    1. 获取发送者的企业微信用户映射
    2. 判断消息类型
    3. 发送到企业微信
    """
    from app import app
    
    room_id = request.room_id
    sender = request.sender
    content = request.content
    
    logger.info(f"收到 Matrix 消息：room={room_id}, sender={sender}")
    
    # 1. 获取消息内容
    msgtype = content.get("msgtype", "m.text")
    body = content.get("body", "")
    
    if not body:
        logger.warning("消息内容为空")
        return {"status": "ignored", "reason": "empty content"}
    
    # 2. 查找发送者的企业微信用户映射
    sender_mapping = await app.state.user_mapper.get_wecom_user(sender)
    
    if not sender_mapping:
        logger.warning(f"发送者没有企业微信映射：{sender}")
        # 可以选择创建默认映射或忽略
        return {"status": "ignored", "reason": "no wecom mapping"}
    
    # 3. 判断消息接收者
    # 如果是私聊房间，发送给对应的企业微信用户
    # 如果是群聊，需要特殊处理
    
    wecom_target = None
    is_external = False
    
    if sender_mapping.is_external:
        # 外部联系人（微信用户）
        wecom_target = sender_mapping.wecom_external_userid
        is_external = True
    else:
        # 企业内部用户
        wecom_target = sender_mapping.wecom_userid
    
    if not wecom_target:
        logger.error(f"没有有效的企业微信目标：{sender}")
        raise HTTPException(status_code=400, detail="No wecom target")
    
    # 4. 发送消息到企业微信
    try:
        if is_external:
            # 发送给外部联系人
            result = app.state.wecom_client.send_message_to_external(
                external_userid=wecom_target,
                content=body,
                msgtype="text"
            )
        else:
            # 发送给企业内部用户
            result = app.state.wecom_client.send_text_message(
                to_user=wecom_target,
                content=body
            )
        
        logger.info(f"消息已发送到企业微信：{wecom_target}, result={result}")
        
        return {
            "status": "sent",
            "target": wecom_target,
            "result": result
        }
        
    except Exception as e:
        logger.error(f"发送企业微信消息失败：{e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 消息监听器 ====================

async def setup_matrix_message_listener():
    """
    设置 Matrix 消息监听器
    
    这会持续监听 Matrix 房间的消息，并自动转发到企业微信
    """
    from app import app
    
    async def on_matrix_message(room_id: str, event: dict):
        """Matrix 消息回调"""
        logger.info(f"Matrix 消息监听：room={room_id}, event={event.get('event_id')}")
        
        # 获取消息内容
        content = event.get("content", {})
        msgtype = content.get("msgtype", "m.text")
        body = content.get("body", "")
        sender = event.get("sender", "")
        
        # 忽略桥接器自己的消息
        if sender == app.state.matrix_client.bridge_user:
            return
        
        # 忽略空消息
        if not body:
            return
        
        # 查找发送者的企业微信映射
        sender_mapping = await app.state.user_mapper.get_wecom_user(sender)
        
        if not sender_mapping:
            logger.debug(f"发送者无企业微信映射，忽略：{sender}")
            return
        
        # 确定消息接收者
        # 这里需要根据房间类型判断：
        # - 私聊房间：发送给对应的企业微信用户
        # - 群聊房间：需要特殊处理（企业微信群）
        
        wecom_target = None
        is_external = False
        
        if sender_mapping.is_external:
            wecom_target = sender_mapping.wecom_external_userid
            is_external = True
        else:
            wecom_target = sender_mapping.wecom_userid
        
        if not wecom_target:
            logger.warning(f"无有效企业微信目标：{sender}")
            return
        
        # 发送消息
        try:
            if is_external:
                result = app.state.wecom_client.send_message_to_external(
                    external_userid=wecom_target,
                    content=body,
                    msgtype="text"
                )
            else:
                result = app.state.wecom_client.send_text_message(
                    to_user=wecom_target,
                    content=body
                )
            
            logger.info(f"自动转发消息到企业微信：{wecom_target}")
            
        except Exception as e:
            logger.error(f"自动转发消息失败：{e}")
    
    # 启动监听
    await app.state.matrix_client.listen_for_messages(on_matrix_message)
    logger.info("Matrix 消息监听器已启动")
