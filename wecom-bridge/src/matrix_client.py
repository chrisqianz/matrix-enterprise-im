#!/usr/bin/env python3
"""
Matrix 客户端
封装 Matrix 客户端 API 调用
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from matrix_client.client import MatrixClient
from matrix_client.errors import MatrixError

logger = logging.getLogger(__name__)


class MatrixClientWrapper:
    """Matrix 客户端封装"""
    
    def __init__(self, homeserver_url: str, bridge_user: str, bridge_password: str):
        """
        初始化 Matrix 客户端
        
        Args:
            homeserver_url: Matrix 服务器 URL
            bridge_user: 桥接器用户 ID（如 @wecom_bridge:example.com）
            bridge_password: 桥接器用户密码
        """
        self.homeserver_url = homeserver_url
        self.bridge_user = bridge_user
        self.bridge_password = bridge_password
        self.client: Optional[MatrixClient] = None
        self._logged_in = False
    
    async def login(self):
        """登录 Matrix 服务器"""
        try:
            self.client = MatrixClient(self.homeserver_url, self.bridge_user)
            await self.client.login(self.bridge_password)
            self._logged_in = True
            logger.info(f"Matrix 桥接器登录成功：{self.bridge_user}")
        except Exception as e:
            logger.error(f"Matrix 登录失败：{e}")
            raise
    
    async def get_account_status(self) -> Dict[str, Any]:
        """获取账号状态"""
        if not self._logged_in:
            raise Exception("未登录")
        
        return {
            "user_id": self.bridge_user,
            "logged_in": self._logged_in,
            "homeserver": self.homeserver_url
        }
    
    async def send_message(self, room_id: str, msgtype: str, 
                          body: str, sender: Optional[str] = None) -> Dict[str, Any]:
        """
        发送消息到 Matrix 房间
        
        Args:
            room_id: 房间 ID
            msgtype: 消息类型（m.text/m.image 等）
            body: 消息内容
            sender: 发送者（可选）
        
        Returns:
            dict: 发送结果
        """
        if not self._logged_in:
            raise Exception("未登录")
        
        try:
            event_id = await self.client.send_message(room_id, msgtype, body)
            logger.info(f"发送消息到 {room_id}: {event_id}")
            return {
                "status": "sent",
                "event_id": event_id,
                "room_id": room_id
            }
        except MatrixError as e:
            logger.error(f"发送 Matrix 消息失败：{e}")
            raise
    
    async def send_text_message(self, room_id: str, content: str) -> Dict[str, Any]:
        """发送文本消息"""
        return await self.send_message(room_id, "m.text", content)
    
    async def send_markdown_message(self, room_id: str, content: str) -> Dict[str, Any]:
        """发送 Markdown 消息"""
        return await self.send_message(room_id, "m.text", content, format="org.matrix.custom.html")
    
    async def create_room(self, room_name: str, is_public: bool = False,
                         invitees: Optional[List[str]] = None) -> str:
        """
        创建 Matrix 房间
        
        Args:
            room_name: 房间名称
            is_public: 是否公开
            invitees: 邀请的用户列表
        
        Returns:
            str: 房间 ID
        """
        if not self._logged_in:
            raise Exception("未登录")
        
        try:
            room = await self.client.create_room(room_name, is_public=is_public)
            room_id = room.get_room_id()
            
            if invitees:
                for user_id in invitees:
                    await room.invite_user(user_id)
            
            logger.info(f"创建房间：{room_id}")
            return room_id
        except MatrixError as e:
            logger.error(f"创建房间失败：{e}")
            raise
    
    async def join_room(self, room_id_or_alias: str) -> str:
        """
        加入房间
        
        Args:
            room_id_or_alias: 房间 ID 或别名
        
        Returns:
            str: 房间 ID
        """
        if not self._logged_in:
            raise Exception("未登录")
        
        try:
            room = await self.client.join_room(room_id_or_alias)
            return room.get_room_id()
        except MatrixError as e:
            logger.error(f"加入房间失败：{e}")
            raise
    
    async def get_room_members(self, room_id: str) -> List[str]:
        """获取房间成员列表"""
        if not self._logged_in:
            raise Exception("未登录")
        
        try:
            room = self.client.get_room(room_id)
            members = await room.get_joined_members()
            return list(members.keys())
        except MatrixError as e:
            logger.error(f"获取房间成员失败：{e}")
            raise
    
    async def get_or_create_room(self, name: str, 
                                  invitees: Optional[List[str]] = None) -> str:
        """
        获取或创建房间
        
        Args:
            name: 房间名称
            invitees: 邀请的用户列表
        
        Returns:
            str: 房间 ID
        """
        # 这里可以扩展：先搜索已存在的房间
        # 如果不存在则创建
        return await self.create_room(name, invitees=invitees)
    
    async def listen_for_messages(self, callback):
        """
        监听消息
        
        Args:
            callback: 消息回调函数，接收 (room_id, event)
        """
        if not self._logged_in:
            raise Exception("未登录")
        
        async def on_message(room, event):
            if event["type"] == "m.room.message":
                await callback(room.room_id, event)
        
        self.client.add_event_listener(on_message, "room.message")
        await self.client.start_listening()
    
    async def leave_room(self, room_id: str):
        """离开房间"""
        if not self._logged_in:
            raise Exception("未登录")
        
        try:
            room = self.client.get_room(room_id)
            await room.leave()
            logger.info(f"离开房间：{room_id}")
        except MatrixError as e:
            logger.error(f"离开房间失败：{e}")
            raise
    
    async def get_room_history(self, room_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取房间历史消息
        
        Args:
            room_id: 房间 ID
            limit: 消息数量限制
        
        Returns:
            list: 消息列表
        """
        if not self._logged_in:
            raise Exception("未登录")
        
        try:
            room = self.client.get_room(room_id)
            events = await room.get_messages(limit=limit)
            return events.get("chunk", [])
        except MatrixError as e:
            logger.error(f"获取历史消息失败：{e}")
            raise
