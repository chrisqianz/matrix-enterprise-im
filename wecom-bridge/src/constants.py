#!/usr/bin/env python3
"""
常量定义 - 提取魔法字符串和配置
"""

from typing import Final

# ============================================================================
# Matrix Event Types
# ============================================================================

EVENT_TYPE_ROOM_MESSAGE: Final[str] = "m.room.message"
EVENT_TYPE_ROOM_MEMBER: Final[str] = "m.room.member"
EVENT_TYPE_ROOM_NAME: Final[str] = "m.room.name"
EVENT_TYPE_ROOM_CANONICAL_ALIAS: Final[str] = "m.room.canonical_alias"
EVENT_TYPE_SPACE_CHILD: Final[str] = "m.space.child"

# Message Types
MSGTYPE_TEXT: Final[str] = "m.text"
MSGTYPE_IMAGE: Final[str] = "m.image"
MSGTYPE_FILE: Final[str] = "m.file"
MSGTYPE_EMOTICON: Final[str] = "m.emoticon"

# Membership Types
MEMBERSHIP_JOIN: Final[str] = "join"
MEMBERSHIP_LEAVE: Final[str] = "leave"
MEMBERSHIP_BAN: Final[str] = "ban"
MEMBERSHIP_INVITE: Final[str] = "invite"

# ============================================================================
# Matrix API Endpoints
# ============================================================================

API_CLIENT_VERSIONS: Final[str] = "/_matrix/client/versions"
API_CLIENT_ROOMS_SEND: Final[str] = "/_matrix/client/v3/rooms/{room_id}/send/{msgtype}"
API_CLIENT_ROOMS_JOIN: Final[str] = "/_matrix/client/v3/join/{room_id}"
API_CLIENT_ROOMS_CREATE: Final[str] = "/_matrix/client/v3/createRoom"
API_CLIENT_USER_ACCOUNT: Final[str] = "/_matrix/client/v3/account/whoami"
API_CLIENT_USER_REGISTER: Final[str] = "/_matrix/client/v3/register"
API_CLIENT_ROOM_GET: Final[str] = "/_matrix/client/v3/rooms/{room_id}"
API_CLIENT_ROOM_MEMBERS: Final[str] = "/_matrix/client/v3/rooms/{room_id}/members"

# ============================================================================
# AppService Constants
# ============================================================================

AS_TRANSACTION_PATH: Final[str] = "/transactions/{txn_id}"
AS_SEND_QUERY_PATH: Final[str] = "/send_query/{query_type}/{namespace_index}/{param}"

# ============================================================================
# Puppet User Constants
# ============================================================================

PUPPET_PREFIX: Final[str] = "@wecom"
PUPPET_LOCALPART_PREFIX: Final[str] = "wecom_"
PUPPET_DISPLAY_NAME_PREFIX: Final[str] = "[企业微信] "

# ============================================================================
# Portal Room Constants
# ============================================================================

PORTAL_ROOM_NAME_PREFIX: Final[str] = "企业微信："
PORTAL_ROOM_TYPE: Final[str] = "m.room"

# ============================================================================
# Enterprise WeChat Constants
# ============================================================================

# Message Types
WECOMP_MSGTYPE_TEXT: Final[str] = "text"
WECOMP_MSGTYPE_IMAGE: Final[str] = "image"
WECOMP_MSGTYPE_VOICE: Final[str] = "voice"
WECOMP_MSGTYPE_VIDEO: Final[str] = "video"
WECOMP_MSGTYPE_FILE: Final[str] = "file"
WECOMP_MSGTYPE_LINK: Final[str] = "link"
WECOMP_MSGTYPE_APPMESSAGE: Final[str] = "appmessage"

# API Endpoints
WECOMP_API_BASE: Final[str] = "https://qyapi.weixin.qq.com/cgi-bin"
WECOMP_API_GET_TOKEN: Final[str] = "/gettoken"
WECOMP_API_SEND_MESSAGE: Final[str] = "/message/send"
WECOMP_API_GET_USER_INFO: Final[str] = "/user/getuserinfo"
WECOMP_API_GET_MESSAGE: Final[str] = "/message/get"

# ============================================================================
# Cache Configuration
# ============================================================================

DEFAULT_CACHE_TTL: Final[int] = 300  # 5 minutes
ACCESS_TOKEN_TTL: Final[int] = 2100   # 企业微信 access_token 有效期约 2 小时
IDEMPOTENCY_CACHE_TTL: Final[int] = 3600  # 1 hour
IDEMPOTENCY_CACHE_MAX_SIZE: Final[int] = 30000  # 支持 200 客户端

# ============================================================================
# Database Configuration
# ============================================================================

DATABASE_POOL_SIZE: Final[int] = 50  # 支持 200 客户端
DATABASE_MAX_OVERFLOW: Final[int] = 80  # 支持 200 客户端
DATABASE_POOL_TIMEOUT: Final[int] = 30
DATABASE_POOL_RECYCLE: Final[int] = 1800

# ============================================================================
# HTTP Configuration
# ============================================================================

HTTP_CONNECTION_TIMEOUT: Final[float] = 30.0
HTTP_SOCKET_TIMEOUT: Final[float] = 60.0
HTTP_MAX_CONNECTIONS: Final[int] = 300  # 支持 200 客户端
HTTP_KEEPALIVE_TIMEOUT: Final[float] = 15.0

# ============================================================================
# Logging Configuration
# ============================================================================

LOG_FORMAT: Final[str] = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"

# ============================================================================
# Health Check Configuration
# ============================================================================

HEALTH_CHECK_TIMEOUT: Final[float] = 5.0
