#!/usr/bin/env python3
"""
企业微信回调处理
处理企业微信发送的消息回调
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class CallbackRequest(BaseModel):
    """企业微信回调请求"""
    msg_type: str
    encrypt: Optional[str] = None
    signature: Optional[str] = None
    timestamp: Optional[str] = None
    nonce: Optional[str] = None
    msg_signature: Optional[str] = None
    content: Optional[str] = None  # 验证时的 echo_str


@router.post("/callback")
async def handle_wecom_callback(request: CallbackRequest):
    """
    处理企业微信回调消息
    
    支持的消息类型:
    - text: 文本消息
    - image: 图片消息
    - voice: 语音消息
    - video: 视频消息
    - file: 文件消息
    - location: 位置消息
    - link: 链接消息
    - event: 事件推送
    """
    logger.info(f"收到企业微信回调：msg_type={request.msg_type}")
    
    # 1. 验证请求（如果是验证阶段的请求）
    if request.msg_type == "text" and request.content:
        # 服务器验证阶段，返回 echo_str
        logger.info("服务器验证请求")
        return {"echo_str": request.content}
    
    # 2. 验证签名（生产环境必需）
    if request.signature and request.timestamp and request.nonce:
        # TODO: 实现签名验证
        # if not wecom_client.verify_callback(...):
        #     raise HTTPException(status_code=401, detail="Invalid signature")
        pass
    
    # 3. 解密消息
    if not request.encrypt:
        logger.warning("缺少加密数据")
        raise HTTPException(status_code=400, detail="No encrypt data")
    
    # TODO: 实现 AES 解密
    # decrypted_xml = decrypt_message(request.encrypt, encoding_aes_key)
    # 这里简化处理，直接使用模拟数据
    decrypted_xml = request.encrypt  # 实际应该解密
    
    # 4. 解析 XML
    try:
        msg_data = parse_callback_xml(decrypted_xml)
    except Exception as e:
        logger.error(f"解析 XML 失败：{e}")
        raise HTTPException(status_code=400, detail=f"Parse error: {e}")
    
    # 5. 路由消息到 Matrix
    await route_message_to_matrix(msg_data)
    
    # 6. 返回成功
    return {"errcode": 0, "errmsg": "ok"}


def parse_callback_xml(xml_data: str) -> dict:
    """
    解析企业微信回调 XML
    
    返回格式:
    {
        "msg_type": "text",
        "from_user": "userid",
        "to_user": "agentid",
        "content": "消息内容",
        "create_time": 1234567890,
        "msg_id": 123456
    }
    """
    import xml.etree.ElementTree as ET
    
    try:
        root = ET.fromstring(xml_data)
        
        return {
            "msg_type": find_text(root, "MsgType"),
            "from_user": find_text(root, "FromUser"),
            "to_user": find_text(root, "ToUser"),
            "content": find_text(root, "Content"),
            "create_time": find_text(root, "CreateTime"),
            "msg_id": find_text(root, "MsgId"),
            "media_id": find_text(root, "MediaId"),  # 图片/视频/文件
            "event": find_text(root, "Event"),  # 事件类型
        }
    except Exception as e:
        logger.error(f"XML 解析错误：{e}, data={xml_data[:200]}")
        raise


def find_text(root, tag_name: str) -> Optional[str]:
    """查找 XML 元素文本"""
    element = root.find(tag_name)
    return element.text if element is not None else None


async def route_message_to_matrix(msg_data: dict):
    """
    将企业微信消息路由到 Matrix
    
    流程:
    1. 查找发送者的 Matrix 用户映射
    2. 查找或创建聊天房间
    3. 发送消息到 Matrix
    """
    from app import app
    
    msg_type = msg_data.get("msg_type")
    from_user = msg_data.get("from_user")
    content = msg_data.get("content", "")
    
    if not from_user:
        logger.warning("消息缺少 from_user")
        return
    
    logger.info(f"路由消息：{from_user} -> Matrix, type={msg_type}")
    
    # 1. 查找发送者的 Matrix 用户映射
    sender_mapping = await app.state.user_mapper.get_matrix_user(from_user)
    
    if not sender_mapping:
        # 如果没有映射，创建虚拟用户
        # 格式：@wecom_{userid}:matrix.example.com
        matrix_user_id = f"@wecom_{from_user.replace('@', '_')}:{app.state.matrix_client.homeserver_url.split(':')[0].replace('https://', '').replace('http://', '')}"
        
        sender_mapping = await app.state.user_mapper.create_mapping(
            matrix_user_id=matrix_user_id,
            wecom_userid=from_user,
            is_external=False
        )
        logger.info(f"创建虚拟用户映射：{matrix_user_id}")
    
    # 2. 查找或创建聊天房间
    # 房间命名：#wecom_chat_{userid}:matrix.example.com
    room_alias = f"#wecom_chat_{from_user.replace('@', '_')}:{app.state.matrix_client.homeserver_url.split(':')[0].replace('https://', '').replace('http://', '')}"
    
    try:
        room_id = await app.state.matrix_client.join_room(room_alias)
    except Exception:
        # 房间不存在，创建新房间
        room_id = await app.state.matrix_client.create_room(
            room_name=f"企业微信 -{from_user}",
            invitees=[sender_mapping.matrix_user_id]
        )
        logger.info(f"创建新聊天房间：{room_id}")
    
    # 3. 格式化消息
    formatted_content = format_wecom_message(msg_type, content, msg_data)
    
    # 4. 发送消息到 Matrix
    try:
        result = await app.state.matrix_client.send_text_message(
            room_id=room_id,
            content=formatted_content
        )
        logger.info(f"消息已发送到 Matrix: {result.get('event_id')}")
    except Exception as e:
        logger.error(f"发送 Matrix 消息失败：{e}")
        raise


def format_wecom_message(msg_type: str, content: str, msg_data: dict) -> str:
    """
    格式化企业微信消息为 Matrix 消息
    
    Args:
        msg_type: 消息类型
        content: 消息内容
        msg_data: 原始消息数据
    
    Returns:
        str: 格式化后的消息
    """
    prefix = ""
    
    if msg_type == "text":
        prefix = ""
    elif msg_type == "image":
        prefix = "[图片消息] "
    elif msg_type == "voice":
        prefix = "[语音消息] "
    elif msg_type == "video":
        prefix = "[视频消息] "
    elif msg_type == "file":
        prefix = "[文件消息] "
    elif msg_type == "location":
        prefix = "[位置消息] "
    elif msg_type == "link":
        prefix = "[链接消息] "
    elif msg_type == "event":
        event = msg_data.get("event", "unknown")
        prefix = f"[事件：{event}] "
    
    return f"{prefix}{content}"
