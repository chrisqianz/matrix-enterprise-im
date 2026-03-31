#!/usr/bin/env python3
"""
自定义异常层次结构
"""

from typing import Optional


class BridgeError(Exception):
    """桥接服务基础异常"""
    
    def __init__(self, message: str, status_code: int = 500, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        result = {
            "error": self.__class__.__name__,
            "message": self.message,
            "status_code": self.status_code,
        }
        if self.details:
            result["details"] = self.details
        return result


class WecomAPIError(BridgeError):
    """企业微信 API 调用失败"""
    
    def __init__(self, message: str, status_code: int = 502, details: Optional[dict] = None):
        super().__init__(message, status_code, details)


class WecomAuthError(WecomAPIError):
    """企业微信认证失败（access_token 过期或无效）"""
    
    def __init__(self, message: str = "企业微信认证失败", status_code: int = 401):
        super().__init__(message, status_code)


class WecomNotFoundError(WecomAPIError):
    """企业微信资源未找到"""
    
    def __init__(self, message: str, status_code: int = 404):
        super().__init__(message, status_code)


class MatrixAPIError(BridgeError):
    """Matrix API 调用失败"""
    
    def __init__(self, message: str, status_code: int = 502, details: Optional[dict] = None):
        super().__init__(message, status_code, details)


class MatrixAuthError(MatrixAPIError):
    """Matrix 认证失败"""
    
    def __init__(self, message: str = "Matrix 认证失败", status_code: int = 401):
        super().__init__(message, status_code)


class MatrixNotFoundError(MatrixAPIError):
    """Matrix 资源未找到"""
    
    def __init__(self, message: str, status_code: int = 404):
        super().__init__(message, status_code)


class UserMappingError(BridgeError):
    """用户映射相关错误"""
    
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message, status_code)


class UserMappingNotFoundError(UserMappingError):
    """用户映射未找到"""
    
    def __init__(self, matrix_user_id: str, status_code: int = 404):
        message = f"用户映射未找到：{matrix_user_id}"
        super().__init__(message, status_code, details={"matrix_user_id": matrix_user_id})


class PortalError(BridgeError):
    """Portal 房间相关错误"""
    
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message, status_code)


class PortalNotFoundError(PortalError):
    """Portal 房间未找到"""
    
    def __init__(self, conversation_id: str, status_code: int = 404):
        message = f"Portal 房间未找到：{conversation_id}"
        super().__init__(message, status_code, details={"conversation_id": conversation_id})


class PuppetError(BridgeError):
    """虚拟用户相关错误"""
    
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message, status_code)


class PuppetNotFoundError(PuppetError):
    """虚拟用户未找到"""
    
    def __init__(self, wecom_userid: str, status_code: int = 404):
        message = f"虚拟用户未找到：{wecom_userid}"
        super().__init__(message, status_code, details={"wecom_userid": wecom_userid})


class MessageSyncError(BridgeError):
    """消息同步相关错误"""
    
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message, status_code)


class MessageLoopDetectedError(MessageSyncError):
    """检测到消息循环"""
    
    def __init__(self, message_id: str, path: list):
        message = f"检测到消息循环：{message_id}, path: {' -> '.join(path)}"
        super().__init__(message, status_code=400, details={"message_id": message_id, "path": path})


class DatabaseError(BridgeError):
    """数据库操作失败"""
    
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message, status_code)


class ArchiveError(BridgeError):
    """消息归档相关错误"""
    
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message, status_code)


class ValidationError(BridgeError):
    """请求参数验证失败"""
    
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message, status_code)


class ConfigurationError(BridgeError):
    """配置错误"""
    
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message, status_code)
