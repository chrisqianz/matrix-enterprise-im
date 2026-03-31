#!/usr/bin/env python3
"""
企业微信 API 客户端（优化版）
封装所有企业微信 API 调用

优化项：
1. ✅ 使用 requests.Session 复用连接池
2. ✅ 使用 constants 模块
3. ✅ 使用自定义异常
4. ✅ 改进的错误处理
"""

import requests
import hashlib
import time
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from constants import (
    WECOMP_API_BASE,
    WECOMP_API_GET_TOKEN,
    WECOMP_API_SEND_MESSAGE,
    WECOMP_API_GET_USER_INFO,
    WECOMP_API_GET_MESSAGE,
    HTTP_CONNECTION_TIMEOUT,
    HTTP_SOCKET_TIMEOUT,
)

from exceptions import WecomAPIError, WecomAuthError

logger = logging.getLogger(__name__)


class WecomClient:
    """企业微信 API 客户端（优化版）"""
    
    def __init__(
        self, 
        corp_id: str, 
        secret: str, 
        agent_id: int,
        connection_timeout: float = HTTP_CONNECTION_TIMEOUT,
        socket_timeout: float = HTTP_SOCKET_TIMEOUT,
    ):
        """
        初始化企业微信客户端
        
        Args:
            corp_id: 企业微信 corp_id
            secret: 应用 secret
            agent_id: 应用 agent_id
            connection_timeout: 连接超时（秒）
            socket_timeout: Socket 超时（秒）
        """
        self.corp_id = corp_id
        self.secret = secret
        self.agent_id = agent_id
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._api_base = WECOMP_API_BASE
        
        # ⚡ 连接池配置（复用连接）
        self._connection_timeout = connection_timeout
        self._socket_timeout = socket_timeout
        self._session: Optional[requests.Session] = None
    
    def _ensure_session(self) -> requests.Session:
        """
        确保 session 已初始化（懒加载）
        
        Returns:
            requests.Session: HTTP 会话
        """
        if self._session is None:
            self._session = requests.Session()
            
            # 配置连接池
            adapter = HTTPAdapter(
                max_retries=Retry(
                    total=3,
                    backoff_factor=0.3,
                    status_forcelist=[500, 502, 503, 504],
                ),
                pool_connections=10,
                pool_maxsize=20,
            )
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)
            
            self._session.headers.update({
                "User-Agent": "WecomMatrixBridge/1.0",
                "Content-Type": "application/json",
            })
            
            logger.info("WecomClient session 已初始化")
        
        return self._session
    
    def close(self):
        """关闭 session"""
        if self._session:
            self._session.close()
            logger.info("WecomClient session 已关闭")
    
    def _get_access_token(self) -> str:
        """
        获取 access_token（带缓存）
        
        Returns:
            str: access_token
            
        Raises:
            WecomAuthError: 认证失败
        """
        # 检查缓存是否有效（提前 5 分钟刷新）
        if (self._access_token and 
            self._token_expiry and 
            datetime.now() < self._token_expiry - timedelta(minutes=5)):
            return self._access_token
        
        # 获取新 token
        session = self._ensure_session()
        url = f"{self._api_base}{WECOMP_API_GET_TOKEN}"
        params = {
            "corpid": self.corp_id,
            "corpsecret": self.secret
        }
        
        try:
            response = session.get(
                url, 
                params=params, 
                timeout=(self._connection_timeout, self._socket_timeout)
            )
            response.raise_for_status()
            result = response.json()
            
            if result.get("errcode") != 0:
                raise WecomAuthError(
                    f"获取 access_token 失败：errcode={result.get('errcode')}, errmsg={result.get('errmsg')}"
                )
            
            self._access_token = result.get("access_token")
            # token 有效期 7200 秒，提前 6 分钟刷新
            self._token_expiry = datetime.now() + timedelta(seconds=7140)
            
            logger.debug("access_token 已刷新")
            return self._access_token
            
        except requests.RequestException as e:
            raise WecomAuthError(f"获取 access_token 网络错误：{e}")
    
    def _request(
        self, 
        method: str, 
        endpoint: str, 
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        require_token: bool = True
    ) -> Dict[str, Any]:
        """
        通用请求方法
        
        Args:
            method: HTTP 方法
            endpoint: API 端点
            params: 查询参数
            json_data: JSON 数据
            require_token: 是否需要 access_token
            
        Returns:
            dict: API 响应
            
        Raises:
            WecomAPIError: API 调用失败
            WecomAuthError: 认证失败
        """
        session = self._ensure_session()
        url = f"{self._api_base}{endpoint}"
        
        # 添加 access_token
        if require_token:
            params = params or {}
            params["access_token"] = self._get_access_token()
        
        try:
            response = session.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                timeout=(self._connection_timeout, self._socket_timeout),
            )
            response.raise_for_status()
            
            result = response.json()
            
            # 企业微信 API 错误处理
            if result.get("errcode") is not None and result.get("errcode") != 0:
                error_msg = f"errcode={result.get('errcode')}, errmsg={result.get('errmsg')}"
                
                # 特殊错误码处理
                if result.get("errcode") == 40014:  # invalid credential
                    raise WecomAuthError(f"认证失败：{error_msg}")
                elif result.get("errcode") == 60020:  # invalid user
                    raise WecomAPIError(f"用户不存在：{error_msg}", status_code=404)
                else:
                    raise WecomAPIError(f"企业微信 API 错误：{error_msg}", status_code=400)
            
            return result
            
        except requests.HTTPError as e:
            raise WecomAPIError(f"HTTP 错误：{e.response.status_code}", status_code=e.response.status_code)
        except requests.RequestException as e:
            raise WecomAPIError(f"网络错误：{e}", status_code=502)
    
    # ============================================================================
    # 消息发送 API
    # ============================================================================
    
    def send_text_message(
        self, 
        to_user: str, 
        content: str, 
        to_party: Optional[str] = None,
        to_tag: Optional[str] = None,
        safe: int = 0
    ) -> Dict[str, Any]:
        """
        发送文本消息
        
        Args:
            to_user: 接收者 userid，多个用 | 分隔
            content: 消息内容
            to_party: 接收部门 id，多个用 | 分隔
            to_tag: 接收标签 id，多个用 | 分隔
            safe: 是否作为安全消息发送，0-否，1-是
            
        Returns:
            dict: API 响应 {errcode: 0, errmsg: "ok"}
        """
        data = {
            "touser": to_user,
            "toparty": to_party or "",
            "totag": to_tag or "",
            "msgtype": "text",
            "agentid": self.agent_id,
            "text": {"content": content},
            "safe": safe
        }
        
        result = self._request("POST", WECOMP_API_SEND_MESSAGE, json_data=data)
        logger.debug(f"发送文本消息到 {to_user}: {result.get('errcode')}")
        return result
    
    def send_markdown_message(self, to_user: str, content: str) -> Dict[str, Any]:
        """发送 Markdown 消息"""
        data = {
            "touser": to_user,
            "msgtype": "markdown",
            "agentid": self.agent_id,
            "markdown": {"content": content}
        }
        
        result = self._request("POST", WECOMP_API_SEND_MESSAGE, json_data=data)
        logger.debug(f"发送 Markdown 消息到 {to_user}: {result.get('errcode')}")
        return result
    
    def send_image_message(self, to_user: str, media_id: str) -> Dict[str, Any]:
        """发送图片消息"""
        data = {
            "touser": to_user,
            "msgtype": "image",
            "agentid": self.agent_id,
            "image": {"media_id": media_id}
        }
        
        result = self._request("POST", WECOMP_API_SEND_MESSAGE, json_data=data)
        logger.debug(f"发送图片消息到 {to_user}: {result.get('errcode')}")
        return result
    
    def send_message_to_external(
        self, 
        external_userid: str, 
        content: str,
        msgtype: str = "text",
        userid: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        发送消息给外部联系人（微信用户）
        
        Args:
            external_userid: 外部联系人 userid
            content: 消息内容
            msgtype: 消息类型（text/markdown/image）
            userid: 企业成员 userid（可选，用于发送客户消息）
            
        Returns:
            dict: API 响应
        """
        if userid:
            # 发送客户消息（需要成员 userid）
            url = "/externalcontact/message/send"
            data = {
                "external_userid": external_userid,
                "userid": userid,
                "msgtype": msgtype,
                "agent_id": self.agent_id,
            }
            if msgtype == "text":
                data["text"] = {"content": content}
            elif msgtype == "markdown":
                data["markdown"] = {"content": content}
        else:
            # 发送应用消息给外部联系人
            url = "/externalcontact/message/sendv2"
            data = {
                "to_external_userid": external_userid,
                "msgtype": msgtype,
                "agentid": self.agent_id,
            }
            if msgtype == "text":
                data["text"] = {"content": content}
            elif msgtype == "markdown":
                data["markdown"] = {"content": content}
        
        result = self._request("POST", url, json_data=data)
        logger.debug(f"发送消息到外部联系人 {external_userid}: {result.get('errcode')}")
        return result
    
    # ============================================================================
    # 用户信息 API
    # ============================================================================
    
    def get_user_info(self, userid: str) -> Dict[str, Any]:
        """
        获取用户信息
        
        Args:
            userid: 用户 ID
            
        Returns:
            dict: 用户信息
        """
        result = self._request("GET", f"/user/get?userid={userid}")
        logger.debug(f"获取用户信息 {userid}: {result.get('errcode')}")
        return result
    
    def batch_get_user_info(self, userids: list) -> Dict[str, Any]:
        """
        批量获取用户信息
        
        Args:
            userids: 用户 ID 列表（最多 50 个）
            
        Returns:
            dict: 用户信息列表
        """
        data = {"userids": userids[:50]}  # 限制 50 个
        result = self._request("POST", "/user/batchget", json_data=data)
        logger.debug(f"批量获取用户信息 {len(userids)} 个：{result.get('errcode')}")
        return result
    
    # ============================================================================
    # 回调消息 API
    # ============================================================================
    
    def get_callback_message(self, msg_id: str) -> Dict[str, Any]:
        """
        获取回调消息详情
        
        Args:
            msg_id: 消息 ID
            
        Returns:
            dict: 消息详情
        """
        result = self._request("GET", f"/message/get?id={msg_id}")
        logger.debug(f"获取回调消息 {msg_id}: {result.get('errcode')}")
        return result
    
    # ============================================================================
    # 外部联系人 API
    # ============================================================================
    
    def get_external_contact(self, external_userid: str) -> Dict[str, Any]:
        """
        获取外部联系人详情
        
        Args:
            external_userid: 外部联系人 userid
            
        Returns:
            dict: 外部联系人信息
        """
        result = self._request("GET", f"/externalcontact/get?external_userid={external_userid}")
        logger.debug(f"获取外部联系人 {external_userid}: {result.get('errcode')}")
        return result
    
    def list_external_contact(self, userid: str, cursor: str = "") -> Dict[str, Any]:
        """
        获取企业成员的外部联系人列表
        
        Args:
            userid: 企业成员 userid
            cursor: 分页游标
            
        Returns:
            dict: 外部联系人列表
        """
        params = {"userid": userid}
        if cursor:
            params["cursor"] = cursor
        
        result = self._request("GET", "/externalcontact/list", params=params)
        logger.debug(f"获取外部联系人列表 {userid}: {result.get('errcode')}")
        return result
