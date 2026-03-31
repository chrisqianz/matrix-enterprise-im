#!/usr/bin/env python3
"""
Matrix AppService 客户端（优化版）
用于与 Synapse 通信（AppService 模式）

优化项：
1. ✅ HTTP 连接池复用（aiohttp.ClientSession 生命周期管理）
2. ✅ 使用 constants 模块
3. ✅ 使用自定义异常
"""

import aiohttp
import logging
from typing import Optional, Dict, Any
from aiohttp import ClientTimeout

from constants import (
    HTTP_CONNECTION_TIMEOUT,
    HTTP_SOCKET_TIMEOUT,
    HTTP_MAX_CONNECTIONS,
    HTTP_KEEPALIVE_TIMEOUT,
    API_CLIENT_VERSIONS,
    API_CLIENT_ROOMS_SEND,
    API_CLIENT_ROOMS_CREATE,
    API_CLIENT_ROOM_GET,
    API_CLIENT_ROOM_MEMBERS,
    API_CLIENT_USER_ACCOUNT,
    API_CLIENT_USER_REGISTER,
)

from exceptions import MatrixAPIError, MatrixAuthError, MatrixNotFoundError

logger = logging.getLogger(__name__)


class MatrixAppService:
    """Matrix AppService 客户端（支持 Puppet 管理 - 优化版）"""
    
    def __init__(
        self, 
        homeserver_url: str, 
        as_token: str, 
        hs_token: str,
        puppet_prefix: str = "@wecom",
        connection_timeout: float = HTTP_CONNECTION_TIMEOUT,
        socket_timeout: float = HTTP_SOCKET_TIMEOUT,
        max_connections: int = HTTP_MAX_CONNECTIONS,
        keepalive_timeout: float = HTTP_KEEPALIVE_TIMEOUT,
    ):
        """
        初始化 Matrix AppService 客户端
        
        Args:
            homeserver_url: Matrix 服务器 URL
            as_token: AppService Token
            hs_token: Homeserver Token
            puppet_prefix: Puppet 用户前缀
            connection_timeout: 连接超时（秒）
            socket_timeout: Socket 超时（秒）
            max_connections: 最大连接数
            keepalive_timeout: Keepalive 超时（秒）
        """
        self.homeserver_url = homeserver_url.rstrip("/")
        self.as_token = as_token
        self.hs_token = hs_token
        self.puppet_prefix = puppet_prefix
        
        # ⚡ 连接池配置
        self._connection_timeout = connection_timeout
        self._socket_timeout = socket_timeout
        self._max_connections = max_connections
        self._keepalive_timeout = keepalive_timeout
        
        # ⚡ 复用 session（生命周期与应用一致）
        self._session: Optional[aiohttp.ClientSession] = None
        self._initialized = False
        self._closed = False
    
    async def _ensure_session(self) -> aiohttp.ClientSession:
        """
        确保 session 已初始化（懒加载）
        
        Returns:
            aiohttp.ClientSession: HTTP 会话
        """
        if self._session is None or self._session.closed:
            timeout = ClientTimeout(
                connect=self._connection_timeout,
                socket=self._socket_timeout,
                total=None  # 无总超时
            )
            
            connector = aiohttp.TCPConnector(
                limit=self._max_connections,  # 最大连接数
                limit_per_host=self._max_connections,
                keepalive_timeout=self._keepalive_timeout,
                force_close=False,  # 复用连接
            )
            
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    "Authorization": f"Bearer {self.as_token}",
                    "Content-Type": "application/json",
                    "User-Agent": "WecomMatrixBridge/1.0",
                },
            )
            logger.info(f"MatrixAppService session 已初始化，max_connections={self._max_connections}")
        
        return self._session
    
    async def close(self):
        """关闭 session（应用关闭时调用）"""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("MatrixAppService session 已关闭")
            self._closed = True
    
    async def __aenter__(self):
        """异步上下文管理器进入"""
        await self._ensure_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        await self.close()
    
    # ============================================================================
    # 核心 API 方法（使用连接池）
    # ============================================================================
    
    async def get_account_status(self) -> Dict[str, Any]:
        """
        获取账号状态（健康检查）
        
        Returns:
            dict: {"status": "ok", "versions": [...]}
        
        Raises:
            MatrixAPIError: API 调用失败
            MatrixAuthError: 认证失败
        """
        session = await self._ensure_session()
        
        try:
            url = f"{self.homeserver_url}{API_CLIENT_VERSIONS}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return {"status": "ok", "versions": data.get("versions", [])}
                elif response.status == 401:
                    raise MatrixAuthError(f"Matrix 认证失败：{response.status}")
                else:
                    raise MatrixAPIError(
                        f"获取账号状态失败：{response.status}", 
                        status_code=response.status
                    )
        except aiohttp.ClientError as e:
            raise MatrixAPIError(f"Matrix API 连接失败：{e}", status_code=502)
    
    async def send_message(
        self,
        room_id: str,
        msgtype: str,
        body: str,
        sender: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        发送消息到 Matrix 房间
        
        Args:
            room_id: 房间 ID
            msgtype: 消息类型（m.text/m.image 等）
            body: 消息内容
            sender: 发送者（可选）
            
        Returns:
            dict: 发送结果 {event_id, ...}
            
        Raises:
            MatrixAPIError: API 调用失败
            MatrixAuthError: 认证失败
            MatrixNotFoundError: 房间不存在
        """
        session = await self._ensure_session()
        
        try:
            url = f"{self.homeserver_url}{API_CLIENT_ROOMS_SEND.format(room_id=room_id, msgtype='m.room.message')}"
            
            data = {
                "msgtype": msgtype,
                "body": body
            }
            if sender:
                data["sender"] = sender
            
            async with session.post(url, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.debug(f"发送消息到 {room_id}: {result.get('event_id')}")
                    return result
                elif response.status == 401:
                    raise MatrixAuthError(f"Matrix 认证失败：{response.status}")
                elif response.status == 404:
                    raise MatrixNotFoundError(f"房间不存在：{room_id}")
                else:
                    error_text = await response.text()
                    raise MatrixAPIError(
                        f"发送 Matrix 消息失败：{response.status} - {error_text}", 
                        status_code=response.status
                    )
        except aiohttp.ClientError as e:
            raise MatrixAPIError(f"Matrix API 连接失败：{e}", status_code=502)
    
    async def send_text_message(self, room_id: str, content: str, sender: Optional[str] = None) -> Dict[str, Any]:
        """发送文本消息（使用 bot 身份）"""
        return await self.send_message(room_id, "m.text", content, sender=sender)
    
    async def send_message_as_user(
        self,
        room_id: str,
        sender: str,
        content: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        以指定用户身份发送消息（Puppet 发送）
        
        这是 Puppet 机制的核心：
        AppService 可以代表其管辖的用户发送消息
        
        Args:
            room_id: 房间 ID
            sender: 发送者用户 ID（Puppet）
            content: 消息内容 {msgtype, body, ...}
            
        Returns:
            dict: 发送结果 {event_id, ...}
            
        Raises:
            MatrixAPIError: API 调用失败
        """
        session = await self._ensure_session()
        
        try:
            url = f"{self.homeserver_url}{API_CLIENT_ROOMS_SEND.format(room_id=room_id, msgtype='m.room.message')}"
            
            # 确保消息内容完整
            message_data = content.copy() if isinstance(content, dict) else {
                "msgtype": "m.text",
                "body": content
            }
            message_data["sender"] = sender
            
            async with session.post(url, json=message_data) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.debug(f"Puppet 发送消息：{sender} -> {room_id}, event_id={result.get('event_id')}")
                    return result
                elif response.status == 401:
                    raise MatrixAuthError(f"Matrix 认证失败：{response.status}")
                elif response.status == 404:
                    raise MatrixNotFoundError(f"房间不存在：{room_id}")
                else:
                    error_text = await response.text()
                    raise MatrixAPIError(
                        f"Puppet 发送消息失败：{response.status} - {error_text}", 
                        status_code=response.status
                    )
        except aiohttp.ClientError as e:
            raise MatrixAPIError(f"Matrix API 连接失败：{e}", status_code=502)
    
    async def create_room(
        self,
        name: Optional[str] = None,
        is_direct: bool = False,
        inviteeslist: Optional[list] = None,
        visibility: str = "private",
        preset: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        创建房间
        
        Args:
            name: 房间名称
            is_direct: 是否私聊
            inviteeslist: 邀请的用户列表
            visibility: 可见性（private/public）
            preset: 房间预设（trusted_private_chat/private_chat/room_type_modern/room_type_town_square）
            
        Returns:
            dict: 创建结果 {room_id, ...}
            
        Raises:
            MatrixAPIError: API 调用失败
        """
        session = await self._ensure_session()
        
        try:
            url = f"{self.homeserver_url}{API_CLIENT_ROOMS_CREATE}"
            
            data = {
                "visibility": visibility,
            }
            
            if name:
                data["name"] = name
            
            if preset:
                data["preset"] = preset
            elif is_direct:
                data["preset"] = "trusted_private_chat"
            
            if inviteeslist:
                data["invite"] = inviteeslist
            
            async with session.post(url, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"创建房间：{result.get('room_id')}, name={name}")
                    return result
                elif response.status == 401:
                    raise MatrixAuthError(f"Matrix 认证失败：{response.status}")
                else:
                    error_text = await response.text()
                    raise MatrixAPIError(
                        f"创建房间失败：{response.status} - {error_text}", 
                        status_code=response.status
                    )
        except aiohttp.ClientError as e:
            raise MatrixAPIError(f"Matrix API 连接失败：{e}", status_code=502)
    
    async def join_room(self, room_id_or_alias: str) -> Dict[str, Any]:
        """
        加入房间
        
        Args:
            room_id_or_alias: 房间 ID 或别名
            
        Returns:
            dict: 加入结果 {room_id, ...}
            
        Raises:
            MatrixAPIError: API 调用失败
            MatrixNotFoundError: 房间不存在
        """
        session = await self._ensure_session()
        
        try:
            url = f"{self.homeserver_url}{API_CLIENT_ROOMS_JOIN.format(room_id=room_id_or_alias)}"
            
            async with session.post(url) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.debug(f"加入房间：{result.get('room_id')}")
                    return result
                elif response.status == 401:
                    raise MatrixAuthError(f"Matrix 认证失败：{response.status}")
                elif response.status == 404:
                    raise MatrixNotFoundError(f"房间不存在：{room_id_or_alias}")
                else:
                    error_text = await response.text()
                    raise MatrixAPIError(
                        f"加入房间失败：{response.status} - {error_text}", 
                        status_code=response.status
                    )
        except aiohttp.ClientError as e:
            raise MatrixAPIError(f"Matrix API 连接失败：{e}", status_code=502)
    
    async def get_room_info(self, room_id: str) -> Dict[str, Any]:
        """
        获取房间信息
        
        Args:
            room_id: 房间 ID
            
        Returns:
            dict: 房间信息
            
        Raises:
            MatrixAPIError: API 调用失败
            MatrixNotFoundError: 房间不存在
        """
        session = await self._ensure_session()
        
        try:
            url = f"{self.homeserver_url}{API_CLIENT_ROOM_GET.format(room_id=room_id)}"
            
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 401:
                    raise MatrixAuthError(f"Matrix 认证失败：{response.status}")
                elif response.status == 404:
                    raise MatrixNotFoundError(f"房间不存在：{room_id}")
                else:
                    error_text = await response.text()
                    raise MatrixAPIError(
                        f"获取房间信息失败：{response.status} - {error_text}", 
                        status_code=response.status
                    )
        except aiohttp.ClientError as e:
            raise MatrixAPIError(f"Matrix API 连接失败：{e}", status_code=502)
    
    async def get_room_members(self, room_id: str) -> list:
        """
        获取房间成员列表
        
        Args:
            room_id: 房间 ID
            
        Returns:
            list: 成员列表
            
        Raises:
            MatrixAPIError: API 调用失败
            MatrixNotFoundError: 房间不存在
        """
        session = await self._ensure_session()
        
        try:
            url = f"{self.homeserver_url}{API_CLIENT_ROOM_MEMBERS.format(room_id=room_id)}?membership=join"
            
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("members", [])
                elif response.status == 401:
                    raise MatrixAuthError(f"Matrix 认证失败：{response.status}")
                elif response.status == 404:
                    raise MatrixNotFoundError(f"房间不存在：{room_id}")
                else:
                    error_text = await response.text()
                    raise MatrixAPIError(
                        f"获取房间成员失败：{response.status} - {error_text}", 
                        status_code=response.status
                    )
        except aiohttp.ClientError as e:
            raise MatrixAPIError(f"Matrix API 连接失败：{e}", status_code=502)
    
    async def whoami(self) -> Dict[str, Any]:
        """
        获取当前用户信息
        
        Returns:
            dict: 用户信息 {user_id, ...}
            
        Raises:
            MatrixAPIError: API 调用失败
            MatrixAuthError: 认证失败
        """
        session = await self._ensure_session()
        
        try:
            url = f"{self.homeserver_url}{API_CLIENT_USER_ACCOUNT}"
            
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 401:
                    raise MatrixAuthError(f"Matrix 认证失败：{response.status}")
                else:
                    error_text = await response.text()
                    raise MatrixAPIError(
                        f"获取用户信息失败：{response.status} - {error_text}", 
                        status_code=response.status
                    )
        except aiohttp.ClientError as e:
            raise MatrixAPIError(f"Matrix API 连接失败：{e}", status_code=502)
    
    async def register_user(self, username: str, password: str, displayname: Optional[str] = None) -> Dict[str, Any]:
        """
        注册用户（用于创建 Puppet 用户）
        
        Args:
            username: 用户名（不含 domain）
            password: 密码
            displayname: 显示名称
            
        Returns:
            dict: 注册结果 {user_id, access_token, ...}
            
        Raises:
            MatrixAPIError: API 调用失败
        """
        session = await self._ensure_session()
        
        try:
            url = f"{self.homeserver_url}{API_CLIENT_USER_REGISTER}"
            
            data = {
                "username": username,
                "password": password,
                "type": "m.login.password",
            }
            
            if displayname:
                data["displayname"] = displayname
            
            async with session.post(url, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"注册用户：{result.get('user_id')}")
                    return result
                else:
                    error_text = await response.text()
                    raise MatrixAPIError(
                        f"注册用户失败：{response.status} - {error_text}", 
                        status_code=response.status
                    )
        except aiohttp.ClientError as e:
            raise MatrixAPIError(f"Matrix API 连接失败：{e}", status_code=502)
