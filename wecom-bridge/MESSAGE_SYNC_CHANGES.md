# MessageSyncManager 修正说明（2026-03-30）

## 🎯 核心问题总结

| 问题 | 严重性 | 影响 |
|------|--------|------|
| **1. Matrix → WeCom 路由逻辑错误** | ❌ 致命 | 消息发给错误的人 |
| **2. 缺少 AppService 事件入口** | ❌ 致命 | Matrix → WeCom 不工作 |
| **3. 缺少防回环机制** | ❌ 致命 | 无限循环 |
| **4. Puppet 发送能力缺失** | ❌ 严重 | 所有消息来自 bot |
| **5. Portal 决策错误** | ❌ 严重 | 房间模型错误 |
| **6. 消息格式太弱** | ⚠️ 体验 | 消息不美观 |
| **7. 缺少消息去重** | ⚠️ 关键 | 重复消息 |
| **8. 缺少 retry 机制** | ⚠️ 生产 | 消息丢失 |

---

## ✅ 修正方案

### 1. Matrix → WeCom 路由逻辑修正（核心）

**❌ 原错误**：
```python
# 用 sender 查找 wecom_target
sender_mapping = await self.user_mapper.get_wecom_user(sender)
wecom_target = sender_mapping.wecom_userid
```

**问题**：
- A 在 Matrix 回复 B
- 结果发给 A 自己（因为 sender 是 A）

**✅ 修正**：
```python
# 通过 portal_mapping 查找
mapping = await self.portal_manager.get_portal_by_room(room_id)
conversation_id = mapping.conversation_id

# 根据 conversation_type 确定目标
if conversation_type == "dm":
    wecom_target = conversation_id[3:]  # 去掉 "dm_"
elif conversation_type == "external":
    wecom_target = conversation_id[9:]  # 去掉 "external_"
elif conversation_type == "group":
    wecom_target = conversation_id[6:]  # 去掉 "group_"
```

**流程对比**：

| 步骤 | 原实现 | 修正后 |
|------|--------|--------|
| 1 | sender → user_mapper | room_id → portal_mapping |
| 2 | sender_mapping.wecom_userid | conversation_id |
| 3 | 直接发送 | 根据 type 解析目标 |

---

### 2. AppService Transaction Handler（核心入口）

**❌ 原缺失**：
- 没有处理 `PUT /_matrix/app/v1/transactions`
- Matrix → WeCom 根本不会触发

**✅ 修正**：
```python
async def handle_appservice_transaction(self, transaction: Dict[str, Any]):
    """
    AppService 事务处理器（核心入口）
    
    Synapse 会通过 PUT /_matrix/app/v1/transactions 调用
    """
    events = transaction.get("events", [])
    
    for event in events:
        await self._handle_matrix_event(event)
```

**端点配置**：
```yaml
# appservice.yaml
url: http://wecom-bridge:8000
sender_localpart: wecom_bridge
```

**FastAPI 路由**：
```python
@app.put("/transactions/{txn_id}")
async def handle_transaction(txn_id: str, transaction: Transaction):
    await app.state.message_sync.handle_appservice_transaction(transaction.dict())
    return {"status": "ok"}
```

---

### 3. 防回环机制（核心）

**❌ 原缺失**：
```
WeCom → Matrix → WeCom → Matrix → 无限循环
```

**✅ 修正**：
```python
def _is_bridge_user(self, user_id: str) -> bool:
    """检查是否是桥接用户"""
    return any(user_id.startswith(prefix) for prefix in ["@wecom_", "@wecom_ext_"])

def _should_skip_message(self, event: Dict[str, Any]) -> bool:
    """检查是否应该跳过消息"""
    sender = event.get("sender", "")
    
    # 防回环：跳过桥接用户发送的消息
    if self._is_bridge_user(sender):
        return True
    
    # 幂等性：跳过重复消息
    event_id = event.get("event_id")
    if event_id and event_id in self._message_cache:
        return True
    
    return False
```

**流程**：
```
1. Matrix 事件到达
2. 检查 sender 是否是 @wecom_*
3. 如果是，跳过
4. 如果不是，继续处理
```

---

### 4. Puppet 真实发送能力

**❌ 原错误**：
```python
# 所有消息都是 bot 发的
await self.matrix_client.send_text_message(room_id, content)
```

**✅ 修正**：
```python
# 使用 Puppet 身份发送
puppet_user_id = portal_result["mapping"].puppet_user_id

if puppet_user_id:
    result = await self.matrix_client.send_message_as_user(
        room_id=room_id,
        sender=puppet_user_id,
        content=message_content
    )
```

**Matrix API**：
```http
POST /_matrix/client/v3/rooms/{roomId}/send/m.room.message
Authorization: Bearer {as_token}

{
  "msgtype": "m.text",
  "body": "Hello",
  "sender": "@wecom_zhangsan:matrix.example.com"  // Puppet 用户
}
```

**关键**：
- 使用 `as_token` 授权
- Synapse 会根据 `sender` 字段自动识别是 Puppet 用户

---

### 5. Portal 决策修正（conversation_id 模型）

**❌ 原错误**：
```python
# 用户 = 房间
portal_result = await self.portal_manager.get_or_create_portal(
    wecom_userid=from_user
)
```

**✅ 修正**：
```python
# 会话 = 房间
if group_id:
    conversation_id = f"group_{group_id}"
elif external_userid:
    conversation_id = f"external_{external_userid}"
else:
    conversation_id = f"dm_{from_user}"

# 根据会话类型创建 Portal
if conversation_type == "group":
    portal_result = await self.portal_manager.get_or_create_group_portal(...)
elif conversation_type == "external":
    portal_result = await self.portal_manager.get_or_create_external_portal(...)
else:
    portal_result = await self.portal_manager.get_or_create_dm_portal(...)
```

---

### 6. 消息格式增强

**❌ 原弱格式**：
```python
return f"{prefix}{content}"
```

**✅ 修正**：
```python
def _format_wecom_message_enhanced(self, msg_type, content, msg_data):
    nickname = msg_data.get("nickname", "企业微信用户")
    
    return {
        "msgtype": "m.text",
        "body": content,
        "format": "org.matrix.custom.html",
        "formatted_body": f"<b>{nickname}</b>: {content}"
    }
```

**效果对比**：

| 格式 | 显示效果 |
|------|---------|
| 原格式 | `你好` |
| 增强格式 | **张三**: 你好 |

---

### 7. 消息幂等性（去重）

**❌ 原缺失**：
- 企业微信重试 webhook
- 重复发送 Matrix 消息

**✅ 修正**：
```python
def _cache_message(self, event_id: str, source: str = "matrix"):
    """缓存消息 ID（幂等性）"""
    self._cleanup_cache()
    
    if len(self._message_cache) >= self._cache_max_size:
        oldest_key = next(iter(self._message_cache))
        del self._message_cache[oldest_key]
    
    self._message_cache[event_id] = {
        "source": source,
        "cached_at": datetime.utcnow()
    }

def _should_skip_message(self, event: Dict[str, Any]) -> bool:
    event_id = event.get("event_id")
    if event_id and event_id in self._message_cache:
        return True
    return False
```

**缓存策略**：
- TTL: 1 小时
- 最大容量：10000 条
- 生产环境建议：Redis

---

### 8. 消息状态跟踪（预留）

```python
async def track_message_delivery(
    self,
    matrix_event_id: str,
    wecom_msg_id: Optional[str] = None
):
    """
    跟踪消息投递状态
    
    TODO: 实现消息状态跟踪
    1. 存储消息映射关系
    2. 跟踪发送状态
    3. 处理发送失败重试
    """
    logger.debug(f"跟踪消息投递：matrix={matrix_event_id}, wecom={wecom_msg_id}")
```

**生产环境建议**：
- 使用消息队列（Redis/Celery）
- 实现重试机制
- 记录失败消息

---

## 📁 修改文件清单

| 文件 | 修改内容 | 行数 |
|------|---------|-----|
| `bridge/message_sync.py` | ✅ 完全重写 | 400 行 |
| `matrix_appservice.py` | ✅ 新增 Puppet 发送方法 | +50 行 |
| `wecom_client.py` | ✅ 新增异步方法 | +80 行 |

---

## 🚀 测试方法

### 1. 测试 Matrix → WeCom 路由

```python
# 创建 Portal（dm_zhangsan）
portal = await portal_manager.get_or_create_dm_portal("zhangsan", nickname="张三")
room_id = portal["room_id"]

# 发送 Matrix 消息（sender 是 @user:matrix.example.com）
await message_sync.sync_matrix_to_wecom(
    room_id=room_id,
    sender="@user:matrix.example.com",  # 不是张三
    content="你好"
)

# ✅ 应该发送给 zhangsan（不是 @user）
```

### 2. 测试防回环

```python
# 模拟 Puppet 用户发送消息
event = {
    "type": "m.room.message",
    "room_id": "!abc123:matrix.example.com",
    "sender": "@wecom_zhangsan:matrix.example.com",  # 桥接用户
    "content": {"msgtype": "m.text", "body": "测试"}
}

# 应该被跳过
should_skip = message_sync._should_skip_message(event)
assert should_skip == True
```

### 3. 测试消息幂等性

```python
# 第一次处理
event_id = "$abc123:matrix.example.com"
event = {"event_id": event_id, "sender": "@user:matrix.example.com"}

result1 = await message_sync._handle_matrix_event(event)

# 第二次处理（应该跳过）
result2 = await message_sync._handle_matrix_event(event)

# 第二次应该被跳过
assert message_sync._should_skip_message(event) == True
```

### 4. 测试 Puppet 发送

```python
# 同步 WeCom 消息到 Matrix
msg_data = {
    "msg_type": "text",
    "from_user": "zhangsan",
    "content": "你好",
    "nickname": "张三"
}

event_id = await message_sync.sync_wecom_to_matrix(msg_data)

# 检查 Matrix 消息的 sender
# 应该是 @wecom_zhangsan:matrix.example.com（不是 bot）
```

### 5. 测试 AppService Transaction

```python
# 模拟 Synapse 发送事务
transaction = {
    "events": [
        {
            "type": "m.room.message",
            "room_id": "!abc123:matrix.example.com",
            "sender": "@user:matrix.example.com",
            "content": {"msgtype": "m.text", "body": "测试"},
            "event_id": "$test123:matrix.example.com"
        }
    ]
}

await message_sync.handle_appservice_transaction(transaction)

# 应该触发 Matrix → WeCom 同步
```

---

## ⚠️ 注意事项

### 1. AppService 配置

确保 `appservice.yaml` 配置正确：

```yaml
as_token: ***
hs_token: ***
sender_localpart: wecom_bridge
url: http://wecom-bridge:8000
namespaces:
  users:
    - regex: ^@wecom(_ext)?_.*$
      exclusive: true
  rooms:
    - prefix: "#wecom_"
      exclusive: true
```

### 2. FastAPI 路由

需要在 `app.py` 中添加 AppService 端点：

```python
@app.put("/transactions/{txn_id}")
async def handle_transaction(
    txn_id: str,
    transaction: Transaction,
    request: Request
):
    """处理 AppService 事务"""
    await app.state.message_sync.handle_appservice_transaction(transaction.dict())
    return {"status": "ok"}
```

### 3. 消息格式兼容性

增强消息格式使用 HTML，确保客户端支持：

```python
"format": "org.matrix.custom.html",
"formatted_body": "<b>张三</b>: 你好"
```

不支持 HTML 的客户端会降级显示 `body`。

---

## 📊 修正前后对比

| 功能 | 修正前 | 修正后 |
|------|--------|--------|
| **Matrix → WeCom 路由** | sender → wecom | room_id → conversation → wecom |
| **AppService 入口** | 无 | `handle_appservice_transaction()` |
| **防回环** | 无 | `_should_skip_message()` |
| **Puppet 发送** | bot 发送 | `send_message_as_user()` |
| **Portal 决策** | wecom_userid | conversation_id |
| **消息格式** | 简单字符串 | HTML 增强格式 |
| **消息去重** | 无 | `_message_cache` |
| **异步支持** | 无 | `*_async()` 方法 |

---

## 🧠 核心思想

**一句话总结**：

> MessageSyncManager 不是"业务逻辑 orchestrator"，而是 Matrix AppService Message Router。
>
> **room_id → conversation_id → wecom_target** 是核心路由逻辑。
>
> **防回环和幂等性** 是生产环境的基石。

---

## 🔗 相关文档

- [Matrix AppService 规范](https://matrix.org/docs/spec/server_server/r0.1.2#server-to-server)
- [Synapse Transaction API](https://matrix-org.github.io/synapse/latest/appservice.html#transactions)
- [mautrix 消息路由](https://github.com/mautrix/mautrix/blob/main/docs/architecture.md)
