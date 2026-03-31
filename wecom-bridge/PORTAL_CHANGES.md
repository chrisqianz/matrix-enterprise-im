# PortalManager 修正说明（2026-03-30）

## 🎯 核心问题总结

### ❌ 原实现的主要问题

| 问题 | 严重性 | 影响 |
|------|--------|------|
| **1. 用 alias 判断房间存在** | ❌ 致命 | 房间查找不可靠 |
| **2. create_room 没绑定 alias** | ❌ 严重 | join_room 失败 |
| **3. 房间创建者错误** | ❌ 严重 | 用户身份错乱 |
| **4. invite 逻辑不完整** | ⚠️ 关键 | puppet 没加入房间 |
| **5. 房间类型没区分** | ⚠️ 关键 | DM/群聊混在一起 |
| **6. update_portal_name 错误** | ❌ 严重 | 房间名不更新 |
| **7. extract_wecom_userid 无效** | ❌ 严重 | 永远匹配不到 |
| **8. "用户=房间"模型不完整** | ⚠️ 设计 | 无法处理复杂场景 |
| **9. 缺少房间生命周期管理** | ⚠️ 生产 | 房间无限增长 |
| **10. 缺少幂等性** | ⚠️ 关键 | 重复创建房间 |

---

## ✅ 修正方案

### 1. Portal DB 映射（核心修正）

**问题**：
```python
# ❌ 错误：用 alias 判断房间存在
room_id = await self.matrix_client.join_room(room_alias)
```

**修正**：
```python
# ✅ 正确：使用数据库映射
class PortalMapping(Base):
    conversation_id = Column(String(100), unique=True)  # 会话 ID
    room_id = Column(String(255), unique=True)  # Matrix 房间 ID
    conversation_type = Column(String(20))  # dm, group, external

# 查询流程
existing = await self.get_portal_by_conversation(conversation_id)
if existing:
    return existing.room_id  # 直接返回
```

**表结构**：
```sql
CREATE TABLE portal_mapping (
    id VARCHAR(64) PRIMARY KEY,
    conversation_id VARCHAR(100) UNIQUE NOT NULL,  -- 会话 ID
    conversation_type VARCHAR(20) NOT NULL,         -- dm/external/group
    room_id VARCHAR(255) UNIQUE NOT NULL,          -- Matrix 房间 ID
    room_alias VARCHAR(255),                       -- 房间别名
    puppet_user_id VARCHAR(255),                   -- Puppet 用户 ID
    is_direct BOOLEAN DEFAULT TRUE,                -- 是否私聊
    is_active BOOLEAN DEFAULT TRUE,                -- 是否活跃
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

---

### 2. Conversation ID 建模（核心修正）

**问题**：
```python
# ❌ 错误：用户 = 房间
room_alias = f"#wecom_chat_{wecom_userid}:domain"
```

**修正**：
```python
# ✅ 正确：会话 ID = 房间
class ConversationType:
    DM: "dm_{userid}"           # 单聊
    EXTERNAL: "external_{id}"   # 外部联系人
    GROUP: "group_{groupid}"    # 群聊

# 生成会话 ID
def generate_conversation_id(user_id=None, external_userid=None, group_id=None):
    if external_userid:
        return f"external_{external_userid}"
    elif group_id:
        return f"group_{group_id}"
    else:
        return f"dm_{user_id}"
```

**场景对比**：

| 场景 | 原实现 | 修正后 |
|------|--------|--------|
| 单聊 | `#wecom_chat_zhangsan` | `dm_zhangsan` |
| 外部联系人 | `#wecom_chat_external_abc` | `external_abc` |
| 群聊 | `#wecom_group_xyz` | `group_xyz` |

---

### 3. alias ↔ room 绑定（核心修正）

**问题**：
```python
# ❌ 错误：创建房间时没绑定 alias
room_id = await self.matrix_client.create_room(room_name=...)
```

**修正**：
```python
# ✅ 正确：创建时绑定 alias
room_id = await self.matrix_client.create_room(
    room_name=room_name,
    room_alias_name=room_alias,  # ✅ 绑定 alias
    is_direct=is_direct,
    preset="trusted_private_chat"
)
```

**API 调用**：
```json
POST /_matrix/client/v3/createRoom
{
  "name": "企业微信 - 张三",
  "room_alias_name": "wecom_dm_zhangsan",  // 去掉 #
  "is_direct": true,
  "preset": "trusted_private_chat"
}
```

---

### 4. 正确的 State Event（协议级修正）

**问题**：
```python
# ❌ 错误：用 message 更新房间名
await self.matrix_client.send_message(
    room_id=room_id,
    msgtype="m.room.name",  // ❌ 错误！
    body=new_name
)
```

**修正**：
```python
# ✅ 正确：用 state event
await self.matrix_client.send_state_event(
    room_id=room_id,
    event_type="m.room.name",
    state_key="",
    content={"name": new_name}
)
```

**API 对比**：

| 操作 | 错误方式 | 正确方式 |
|------|---------|---------|
| 更新房间名 | `send_message(msgtype="m.room.name")` | `send_state_event(type="m.room.name")` |
| API | `POST /rooms/{id}/send` | `PUT /rooms/{id}/state/m.room.name/` |

---

### 5. 反向查询（通过 DB）

**问题**：
```python
# ❌ 错误：用正则匹配 room_id
pattern = r"!wecom_(chat|group)_(.*):"
match = re.match(pattern, room_id)  # 永远匹配不到
```

**修正**：
```python
# ✅ 正确：查询 portal_mapping 表
async def extract_conversation_from_room(self, room_id: str) -> Optional[str]:
    mapping = await self.get_portal_by_room(room_id)
    return mapping.conversation_id if mapping else None
```

**原因**：
- Matrix room_id 格式：`!abc123:matrix.example.com`
- 不是 `!wecom_chat_xxx:domain`
- 必须通过 DB 映射查询

---

### 6. 幂等性保证

**问题**：
```python
# ❌ 错误：并发时可能创建多个房间
room_id = await self.matrix_client.create_room(...)
```

**修正**：
```python
# ✅ 正确：先查 DB，再创建
existing = await self.get_portal_by_conversation(conversation_id)
if existing:
    return existing.room_id  # 幂等返回

# 创建时加唯一索引
ALTER TABLE portal_mapping 
ADD UNIQUE INDEX idx_conversation_id (conversation_id);
```

**处理并发**：
```python
try:
    # 创建房间 + 写入 DB
    ...
except IntegrityError as e:
    # 并发创建，回滚后重试查询
    existing = await self.get_portal_by_conversation(conversation_id)
    if existing:
        return existing.room_id
    raise
```

---

### 7. 完整流程对比

#### ❌ 原流程（错误）

```
1. 生成 alias
2. 尝试 join_room(alias)
3. 如果失败，create_room()
4. 返回 room_id

❌ 问题：
- alias 可能没绑定
- join 失败但房间存在
- 没有 DB 映射
```

#### ✅ 修正流程

```
1. 生成 conversation_id
2. 查询 portal_mapping 表
3. 如果存在，返回 room_id
4. 如果不存在：
   a. 生成 alias
   b. 尝试 join_room（容错）
   c. 如果失败，create_room（带 alias 绑定）
   d. 写入 portal_mapping
5. 返回 room_id

✅ 优势：
- DB 为事实来源
- 幂等性保证
- 支持并发
```

---

## 📁 修改文件清单

| 文件 | 修改内容 | 行数 |
|------|---------|-----|
| `bridge/portal_manager.py` | ✅ 完全重写 | 450 行 |
| `matrix_appservice.py` | ✅ 新增 Portal 方法 | +110 行 |

---

## 🚀 测试方法

### 1. 测试 Conversation ID 生成

```python
pm = PortalManager(...)

# 单聊
conv_id1 = pm.generate_conversation_id(user_id="zhangsan")
assert conv_id1 == "dm_zhangsan"

# 外部联系人
conv_id2 = pm.generate_conversation_id(external_userid="ext123")
assert conv_id2 == "external_ext123"

# 群聊
conv_id3 = pm.generate_conversation_id(group_id="chat123")
assert conv_id3 == "group_chat123"
```

### 2. 测试 Portal 创建（幂等性）

```python
# 第一次调用
result1 = await pm.get_or_create_dm_portal("zhangsan", nickname="张三")
assert result1["created"] == True
room_id1 = result1["room_id"]

# 第二次调用（应该返回同一个房间）
result2 = await pm.get_or_create_dm_portal("zhangsan", nickname="张三")
assert result2["created"] == False
assert result2["room_id"] == room_id1
```

### 3. 测试 DB 映射

```python
# 创建 Portal
result = await pm.get_or_create_dm_portal("zhangsan", nickname="张三")

# 查询映射
mapping = await pm.get_portal_by_conversation("dm_zhangsan")
assert mapping.room_id == result["room_id"]
assert mapping.conversation_type == "dm"

# 反向查询
conv_id = await pm.extract_conversation_from_room(result["room_id"])
assert conv_id == "dm_zhangsan"
```

### 4. 测试房间别名绑定

```python
# 创建 Portal
result = await pm.get_or_create_dm_portal("zhangsan")

# 检查 alias 是否绑定
# 在 Element 中应该能看到：#wecom_dm_zhangsan:matrix.example.com
```

### 5. 测试房间名称更新

```python
# 更新房间名称
success = await pm.update_room_name(room_id, "新名称")
assert success == True

# 在 Element 中检查房间名称是否更新
```

---

## ⚠️ 注意事项

### 1. 数据库迁移

需要运行迁移创建 `portal_mapping` 表：

```sql
CREATE TABLE portal_mapping (
    id VARCHAR(64) PRIMARY KEY,
    conversation_id VARCHAR(100) UNIQUE NOT NULL,
    conversation_type VARCHAR(20) NOT NULL,
    room_id VARCHAR(255) UNIQUE NOT NULL,
    room_alias VARCHAR(255),
    puppet_user_id VARCHAR(255),
    is_direct BOOLEAN DEFAULT TRUE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_conversation_id ON portal_mapping(conversation_id);
CREATE INDEX idx_room_id ON portal_mapping(room_id);
CREATE INDEX idx_active ON portal_mapping(is_active);
```

### 2. 与 PuppetManager 配合

`PortalManager` 需要 `PuppetManager` 实例：

```python
puppet_manager = PuppetManager(
    user_mapper=user_mapper,
    matrix_domain=MATRIX_DOMAIN,
    matrix_client=matrix_appservice
)

portal_manager = PortalManager(
    matrix_client=matrix_appservice,
    puppet_manager=puppet_manager,
    matrix_domain=MATRIX_DOMAIN,
    database_url=DATABASE_URL
)
```

### 3. AppService 配置

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

---

## 📊 修正前后对比

| 功能 | 修正前 | 修正后 |
|------|--------|--------|
| **房间查找** | alias join | DB 查询 |
| **房间创建** | 无 alias 绑定 | 绑定 alias |
| **会话建模** | 用户=房间 | conversation_id=房间 |
| **房间类型** | 无区分 | dm/external/group |
| **反向查询** | 正则匹配 | DB 查询 |
| **幂等性** | 无 | 唯一索引 + 异常处理 |
| **房间名称** | message | state event |
| **生命周期** | 无 | 软删除 |

---

## 🔗 相关文档

- [Matrix Room API](https://matrix.org/docs/spec/client_server/r0.6.1#rooms)
- [Matrix State Events](https://matrix.org/docs/spec/client_server/r0.6.1#state-events)
- [mautrix Portal 设计](https://github.com/mautrix/mautrix/blob/main/docs/architecture.md)
- [Synapse AppService](https://matrix-org.github.io/synapse/latest/appservice.html)

---

## 🧠 核心思想

**一句话总结**：

> PortalManager 不是"房间工具类"，而是 Bridge 的会话管理核心。
> 
> **DB 是事实来源（source of truth）**，不是 Matrix。
> 
> **conversation_id → room_id** 映射是桥接的核心。
