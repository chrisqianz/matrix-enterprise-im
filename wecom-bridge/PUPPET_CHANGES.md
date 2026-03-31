# PuppetManager 修正说明（2026-03-30）

## 🎯 核心问题总结

### ❌ 原实现的主要问题

1. **致命：虚拟用户只是数据库记录**
   - 只调用 `create_mapping(...)`
   - Matrix 中用户不存在
   - 所有消息发送失败

2. **致命：用户 ID 清洗不合规**
   - 简单替换 `@`、`#`、`:`
   - Matrix 用户 ID 规则：`[a-z0-9._=-]+`
   - 可能注册失败

3. **关键：缺少用户存在性校验**
   - 数据库有 ≠ Matrix 有
   - 必须调用 Matrix API 检查

4. **关键：缺少 AppService Puppet 控制**
   - 没有实现 `GET /_matrix/app/v1/users/{userId}`
   - Synapse 无法确认用户归属

5. **关键：Profile 不同步**
   - 只更新数据库
   - Matrix 中看不到昵称/头像

6. **设计问题：硬删除**
   - 直接删除数据库记录
   - Matrix 用户残留

7. **性能问题：缺少缓存**
   - 每次查询数据库
   - 高并发打爆数据库

---

## ✅ 修正方案

### 1. 真正的 Matrix 用户创建

**问题**：
```python
# ❌ 错误：只创建数据库记录
mapping = await self.user_mapper.create_mapping(...)
```

**修正**：
```python
# ✅ 正确：通过 AppService 自动注册
await self._ensure_matrix_user_exists(puppet_user_id)
```

**实现**：
- 调用 `GET /_matrix/app/v1/users/{userId}` 检查存在性
- 如果不存在，通过事务触发自动注册
- Synapse 会在首次收到事件时自动创建用户

**文件**：
- `matrix_appservice.py` - `user_exists()`、`ensure_user_registered()`

---

### 2. 用户 ID 正则清洗

**问题**：
```python
# ❌ 错误：简单替换
clean_userid = wecom_userid.replace('@', '_').replace('#', '_').replace(':', '_')
```

**修正**：
```python
# ✅ 正确：正则清洗（符合 Matrix 规范）
clean_userid = re.sub(r'[^a-z0-9._=-]', '_', wecom_userid.lower())
```

**原因**：
- Matrix 用户 ID 规则：`[a-z0-9._=-]+`
- 原实现可能保留非法字符导致注册失败

**文件**：
- `puppet_manager.py` - `generate_puppet_user_id()`

---

### 3. 用户存在性校验

**问题**：
```python
# ❌ 错误：只检查数据库
existing = await self.user_mapper.get_wecom_user(puppet_user_id)
if existing:
    return  # 假设 Matrix 也有
```

**修正**：
```python
# ✅ 正确：检查 Matrix
if existing:
    matrix_exists = await self._ensure_matrix_user_exists(puppet_user_id)
    return {"exists": True, "matrix_exists": matrix_exists}
```

**文件**：
- `puppet_manager.py` - `_ensure_matrix_user_exists()`
- `matrix_appservice.py` - `user_exists()`

---

### 4. AppService Puppet 控制端点

**新增端点**：

| 端点 | 方法 | 用途 |
|------|------|------|
| `GET /_matrix/app/v1/users/{userId}` | GET | 检查用户是否存在 |
| `POST /_matrix/app/v1/transactions/{txn_id}` | POST | 触发用户自动注册 |
| `PUT /_matrix/client/r0/profile/{userId}/displayname` | PUT | 设置显示名 |
| `PUT /_matrix/client/r0/profile/{userId}/avatar_url` | PUT | 设置头像 |

**文件**：
- `matrix_appservice.py` - Puppet 管理方法

---

### 5. Profile 同步到 Matrix

**问题**：
```python
# ❌ 错误：只更新数据库
await self.user_mapper.update_user_info(...)
```

**修正**：
```python
# ✅ 正确：同步到 Matrix
await self.user_mapper.update_user_info(...)  # 更新数据库
await self._sync_profile_to_matrix(...)       # 同步 Matrix
```

**实现**：
```python
async def _sync_profile_to_matrix(self, puppet_user_id, nickname, avatar_url):
    if nickname:
        await self.matrix_client.set_displayname(puppet_user_id, nickname)
    if avatar_url:
        await self.matrix_client.set_avatar_url(puppet_user_id, avatar_url)
```

**文件**：
- `puppet_manager.py` - `_sync_profile_to_matrix()`
- `matrix_appservice.py` - `set_displayname()`、`set_avatar_url()`

---

### 6. 软删除

**问题**：
```python
# ❌ 错误：硬删除
session.delete(mapping)
```

**修正**：
```python
# ✅ 正确：软删除
mapping.is_active = False
mapping.deleted_at = datetime.utcnow()
```

**数据库变更**：
```python
# 新增字段
is_active = Column(Boolean, default=True)  # 是否活跃
deleted_at = Column(DateTime)  # 删除时间
```

**文件**：
- `user_mapper.py` - `soft_delete_mapping()`
- `puppet_manager.py` - `delete_puppet()`（调用软删除）

---

### 7. LRU 缓存层

**问题**：
```python
# ❌ 错误：每次查询数据库
await self.user_mapper.get_wecom_user(...)
```

**修正**：
```python
# ✅ 正确：先查缓存
if wecom_userid in self._user_cache:
    return self._user_cache[wecom_userid]

# 查询数据库后写入缓存
self._cache_set(wecom_userid, result)
```

**实现**：
- 简单 LRU 缓存（最大 1000 条）
- 生产环境建议用 Redis

**文件**：
- `puppet_manager.py` - `_cache_set()`、`_cache_get()`

---

### 8. 外部联系人 ID 命名优化

**问题**：
```python
# ❌ 不清晰：external_{id}
puppet_user_id = self.generate_puppet_user_id(f"external_{external_userid}")
# 结果：@wecom_external_abc123:domain
```

**修正**：
```python
# ✅ 清晰：使用 is_external 参数
puppet_user_id = self.generate_puppet_user_id(external_userid, is_external=True)
# 结果：@wecom_ext_abc123:domain
```

**命名规则**：
- 内部用户：`@wecom_{userid}:domain`
- 外部用户：`@wecom_ext_{userid}:domain`

**文件**：
- `puppet_manager.py` - `generate_puppet_user_id()`、`get_or_create_external_puppet()`

---

## 📁 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `bridge/puppet_manager.py` | ✅ 完全重写（9 项修正） |
| `bridge/user_mapper.py` | ✅ 新增软删除字段和方法 |
| `matrix_appservice.py` | ✅ 新增 Puppet 管理方法 |

---

## 🚀 测试方法

### 1. 测试用户 ID 生成

```python
pm = PuppetManager(user_mapper, "matrix.example.com")

# 内部用户
uid1 = pm.generate_puppet_user_id("zhangsan@company.com", is_external=False)
assert uid1 == "@wecom_zhangsan_company_com:matrix.example.com"

# 外部用户
uid2 = pm.generate_puppet_user_id("external123", is_external=True)
assert uid2 == "@wecom_ext_external123:matrix.example.com"
```

### 2. 测试用户创建

```python
result = await pm.get_or_create_puppet(
    wecom_userid="zhangsan",
    nickname="张三",
    avatar_url="mxc://..."
)

assert result["user_id"] == "@wecom_zhangsan:matrix.example.com"
assert result["created"] == True
assert result["matrix_exists"] == True  # ✅ Matrix 中已创建
```

### 3. 测试 Profile 同步

```python
# 在 Matrix 客户端检查
# 用户 @wecom_zhangsan:matrix.example.com 应该显示：
# - 昵称：张三
# - 头像：已设置
```

### 4. 测试软删除

```python
await pm.delete_puppet("@wecom_zhangsan:matrix.example.com")

# 检查数据库
mapping = await user_mapper.get_wecom_user("@wecom_zhangsan:matrix.example.com")
assert mapping.is_active == False
assert mapping.deleted_at is not None
```

### 5. 测试缓存

```python
# 第一次调用（查询数据库）
result1 = await pm.get_or_create_puppet("zhangsan")

# 第二次调用（从缓存返回）
result2 = await pm.get_or_create_puppet("zhangsan")

assert result1["user_id"] == result2["user_id"]
# 应该更快（没有数据库查询）
```

---

## ⚠️ 注意事项

### 1. Matrix 客户端配置

`PuppetManager` 需要传入 `matrix_client` 参数：

```python
puppet_manager = PuppetManager(
    user_mapper=user_mapper,
    matrix_domain=MATRIX_DOMAIN,
    matrix_client=matrix_appservice  # ✅ 必须传入
)
```

### 2. AppService 配置

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
```

### 3. 数据库迁移

需要运行迁移添加新字段：

```sql
ALTER TABLE user_mapping 
ADD COLUMN is_active BOOLEAN DEFAULT TRUE,
ADD COLUMN deleted_at TIMESTAMP;
```

### 4. 生产环境缓存

当前使用简单 LRU 缓存，生产环境建议：

```python
# 使用 Redis
import redis
redis_client = redis.Redis()

async def get_from_cache(key):
    data = redis_client.get(key)
    return json.loads(data) if data else None

async def set_to_cache(key, value):
    redis_client.setex(key, 3600, json.dumps(value))
```

---

## 📊 修正前后对比

| 功能 | 修正前 | 修正后 |
|------|--------|--------|
| **用户创建** | 只存数据库 | 数据库 + Matrix |
| **用户 ID 清洗** | 简单替换 | 正则 `[a-z0-9._=-]` |
| **存在性校验** | 无 | Matrix API 检查 |
| **Puppet 控制** | 无 | AppService 端点 |
| **Profile 同步** | 只更新 DB | DB + Matrix API |
| **删除方式** | 硬删除 | 软删除（inactive） |
| **缓存** | 无 | LRU cache |
| **外部用户 ID** | `external_{id}` | `@wecom_ext_{id}` |

---

## 🔗 相关文档

- [Matrix AppService 规范](https://matrix.org/docs/spec/client_server/r0.6.1#server-to-server)
- [Synapse AppService 配置](https://matrix-org.github.io/synapse/latest/appservice.html)
- [mautrix 桥接最佳实践](https://github.com/mautrix/mautrix)
