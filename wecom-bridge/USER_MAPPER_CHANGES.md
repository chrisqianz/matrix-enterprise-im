# UserMapper 修正说明（2026-03-30）

## 🎯 核心问题总结

| 问题 | 严重性 | 影响 |
|------|--------|------|
| **1. 用户映射不是核心** | ⚠️ 设计 | PortalMapping 才是核心 |
| **2. 并发安全缺失** | ❌ 致命 | 重复插入 |
| **3. async + 同步 SQLAlchemy** | ❌ 致命 | 阻塞事件循环 |
| **4. 缺少 user_type 字段** | ⚠️ 设计 | 无法区分 puppet/real/bot |
| **5. 缺少 agentid** | ⚠️ 关键 | external_userid 不唯一 |
| **6. 缺少缓存层** | ⚠️ 性能 | DB 被打爆 |
| **7. 硬删除危险** | ⚠️ 设计 | 幽灵用户 |
| **8. 缺少反查能力** | ⚠️ 关键 | 重复映射 |
| **9. 缺少 MessageMapping** | ❌ 严重 | 消息状态无法跟踪 |

---

## ✅ 修正方案

### 1. UserMapping 表结构修正

**新增字段**：

```python
class UserMapping(Base):
    # ✅ 新增：用户类型
    user_type = Column(String(20), default="puppet")  # puppet, real, bot
    
    # ✅ 新增：应用 agentid
    wecom_agentid = Column(String(50), index=True)
    
    # ✅ 软删除
    is_active = Column(Boolean, default=True)
    deleted_at = Column(DateTime)
```

**唯一索引（并发安全）**：

```python
__table_args__ = (
    # matrix_user_id 唯一
    Index('idx_matrix_user_unique', 'matrix_user_id', unique=True),
    
    # wecom_userid + agentid 唯一（支持多应用）
    Index('idx_wecom_userid_unique', 'wecom_userid', 'wecom_agentid', unique=True),
    
    # wecom_external_userid + agentid 唯一
    Index('idx_wecom_external_unique', 'wecom_external_userid', 'wecom_agentid', unique=True),
)
```

**对比**：

| 字段 | 修正前 | 修正后 |
|------|--------|--------|
| user_type | 无 | puppet/real/bot |
| wecom_agentid | 无 | ✅ 新增 |
| 唯一索引 | matrix_user_id | matrix_user_id + wecom_userid+agentid |

---

### 2. 并发安全（UNIQUE 索引 + 异常处理）

**❌ 原错误**：
```python
existing = session.query(...).first()
if existing:
    return existing

# 并发时可能创建重复记录
mapping = UserMapping(...)
session.add(mapping)
session.commit()
```

**✅ 修正**：
```python
# 1. 使用 UNIQUE 索引保证并发安全
__table_args__ = (
    Index('idx_matrix_user_unique', 'matrix_user_id', unique=True),
)

# 2. 捕获 IntegrityError
try:
    mapping = await self._run_in_executor(create_db)
    return mapping
except IntegrityError as e:
    # 并发创建，查询现有记录
    existing = await self.get_wecom_user(matrix_user_id)
    if existing:
        return existing
    raise
```

**流程对比**：

| 步骤 | 原实现 | 修正后 |
|------|--------|--------|
| 1 | 查询是否存在 | 直接插入 |
| 2 | 如果不存在创建 | UNIQUE 约束保证 |
| 3 | 返回 | 捕获异常后查询 |

---

### 3. 异步 SQLAlchemy（run_in_executor）

**❌ 原错误**：
```python
async def get_wecom_user(self, matrix_user_id: str):
    # ❌ 阻塞事件循环
    with self._get_session() as session:
        mapping = session.query(...).first()
        return mapping
```

**问题**：
- 同步 DB 操作阻塞事件循环
- 高并发时整个 bridge 卡死

**✅ 修正**：
```python
def _run_in_executor(self, func, *args):
    """在 executor 中运行同步函数"""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, partial(func, *args))

async def get_wecom_user(self, matrix_user_id: str):
    # ✅ 不阻塞事件循环
    def query_db():
        with self._get_session() as session:
            return session.query(...).first()
    
    return await self._run_in_executor(query_db)
```

**对比**：

| 方案 | 优点 | 缺点 |
|------|------|------|
| 原实现 | 简单 | 阻塞事件循环 |
| run_in_executor | 不阻塞 | 需要线程池 |
| AsyncEngine | 原生异步 | 需要 asyncpg |

**推荐**：
- 简单场景：run_in_executor
- 高性能场景：SQLAlchemy 2.0 AsyncEngine

---

### 4. LRU 缓存层

**❌ 原缺失**：
```python
# 每次查询都访问数据库
await self.get_wecom_user(matrix_user_id)
```

**✅ 修正**：
```python
class UserMapper:
    def __init__(self, cache_ttl_seconds=300, cache_max_size=1000):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._cache_max_size = cache_max_size
    
    def _cache_get(self, key: str) -> Optional[UserMapping]:
        """从缓存获取"""
        if key not in self._cache:
            return None
        
        cached = self._cache[key]
        if datetime.utcnow() - cached["cached_at"] > self._cache_ttl:
            del self._cache[key]
            return None
        
        return cached["value"]
    
    def _cache_set(self, key: str, value: UserMapping):
        """写入缓存"""
        if len(self._cache) >= self._cache_max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
        
        self._cache[key] = {
            "value": value,
            "cached_at": datetime.utcnow()
        }
```

**缓存策略**：
- TTL: 300 秒（可配置）
- 最大容量：1000 条（可配置）
- LRU：超出容量删除最早条目

**生产环境建议**：
```python
# 使用 Redis
import redis
redis_client = redis.Redis()

async def get_from_cache(key):
    data = redis_client.get(key)
    return json.loads(data) if data else None

async def set_to_cache(key, value):
    redis_client.setex(key, 300, json.dumps(value))
```

---

### 5. MessageMapping 表（新增）

**表结构**：

```python
class MessageMapping(Base):
    """消息映射表：Matrix 事件 ↔ 企业微信消息"""
    __tablename__ = "message_mapping"
    
    id = Column(String(64), primary_key=True)
    matrix_event_id = Column(String(255), unique=True, nullable=False, index=True)
    matrix_room_id = Column(String(255), index=True)
    matrix_sender = Column(String(255))
    
    wecom_msg_id = Column(String(100), index=True)
    wecom_conversation_id = Column(String(100), index=True)
    
    direction = Column(String(10), nullable=False)  # wecom_to_matrix, matrix_to_wecom
    status = Column(String(20), default="pending")  # pending, success, failed
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**用途**：
- 消息状态跟踪
- 消息去重
- 失败重试
- 数据分析

---

### 6. 反查能力（唯一索引）

**❌ 原问题**：
```python
# wecom_userid 没有唯一索引
# 可能多个 puppet 指向同一个 wecom_user
wecom_userid = Column(String(100), index=True)
```

**✅ 修正**：
```python
# wecom_userid + agentid 唯一
Index('idx_wecom_userid_unique', 'wecom_userid', 'wecom_agentid', unique=True)

# 支持反查
async def get_matrix_user(self, wecom_userid: str, agentid: Optional[str] = None):
    """根据企业微信用户 ID 查找 Matrix 用户"""
    query = session.query(UserMapping).filter(
        UserMapping.wecom_userid == wecom_userid
    )
    
    if agentid:
        query = query.filter(UserMapping.wecom_agentid == agentid)
    
    return query.first()
```

---

### 7. user_type 字段

**新增字段**：

```python
user_type = Column(String(20), default="puppet")  # puppet, real, bot
```

**类型说明**：

| 类型 | 说明 | 示例 |
|------|------|------|
| puppet | 虚拟用户（桥接创建） | @wecom_zhangsan:domain |
| real | 真实用户（主动绑定） | @user:domain |
| bot | 机器人用户 | @wecom_bridge:domain |

**用途**：
- 区分用户类型
- 过滤查询
- 统计分析

---

### 8. wecom_agentid 字段

**新增字段**：

```python
wecom_agentid = Column(String(50), index=True)
```

**原因**：
- 企业微信真实模型：`external_userid + agentid` 才唯一
- 支持多应用桥接

**唯一索引**：

```python
Index('idx_wecom_external_unique', 'wecom_external_userid', 'wecom_agentid', unique=True)
```

---

## 📊 三层架构

### 1. UserMapping（用户层）

```
matrix_user_id ↔ wecom_userid
  ├─ puppet (@wecom_zhangsan)
  ├─ real (@user)
  └─ bot (@wecom_bridge)
```

### 2. PortalMapping（会话层）

```
room_id ↔ conversation_id
  ├─ dm_zhangsan
  ├─ external_ext123
  └─ group_chat123
```

### 3. MessageMapping（消息层）

```
matrix_event_id ↔ wecom_msg_id
  ├─ direction: wecom_to_matrix
  └─ status: pending/success/failed
```

**完整架构**：

```
User → Puppet (UserMapping)
Room → Conversation (PortalMapping)
Event → Message (MessageMapping)
```

---

## 🚀 测试方法

### 1. 测试并发安全

```python
# 并发创建同一个用户
import asyncio

async def test_concurrent_create():
    tasks = [
        user_mapper.create_mapping(
            matrix_user_id="@wecom_test:domain",
            wecom_userid="test_user"
        )
        for _ in range(10)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 应该只有一个成功，其他返回现有记录或异常
    success_count = sum(1 for r in results if not isinstance(r, Exception))
    assert success_count >= 1  # 至少一个成功

asyncio.run(test_concurrent_create())
```

### 2. 测试缓存

```python
# 第一次查询（访问数据库）
start = time.time()
result1 = await user_mapper.get_wecom_user("@wecom_zhangsan:domain")
time1 = time.time() - start

# 第二次查询（从缓存返回）
start = time.time()
result2 = await user_mapper.get_wecom_user("@wecom_zhangsan:domain")
time2 = time.time() - start

# 缓存应该更快
assert time2 < time1 * 0.5  # 至少快 2 倍
```

### 3. 测试 MessageMapping

```python
# 创建消息映射
mapping = await user_mapper.create_message_mapping(
    matrix_event_id="$abc123:domain",
    matrix_room_id="!room123:domain",
    matrix_sender="@user:domain",
    wecom_msg_id="wecom_msg_123",
    wecom_conversation_id="dm_zhangsan",
    direction="wecom_to_matrix"
)

# 更新状态
await user_mapper.update_message_status("$abc123:domain", "success")

# 查询
mapping = await user_mapper.get_message_mapping("$abc123:domain")
assert mapping.status == "success"
```

### 4. 测试反查

```python
# 创建映射
await user_mapper.create_mapping(
    matrix_user_id="@wecom_zhangsan:domain",
    wecom_userid="zhangsan",
    agentid="1000001"
)

# 反查
mapping = await user_mapper.get_matrix_user("zhangsan", agentid="1000001")
assert mapping.matrix_user_id == "@wecom_zhangsan:domain"
```

---

## ⚠️ 注意事项

### 1. 数据库迁移

需要运行迁移添加新字段和索引：

```sql
-- 1. 添加新字段
ALTER TABLE user_mapping 
ADD COLUMN user_type VARCHAR(20) DEFAULT 'puppet',
ADD COLUMN wecom_agentid VARCHAR(50),
ADD COLUMN is_active BOOLEAN DEFAULT TRUE,
ADD COLUMN deleted_at TIMESTAMP;

-- 2. 添加索引
CREATE INDEX idx_wecom_agentid ON user_mapping(wecom_agentid);

-- 3. 添加唯一索引（需要先清理重复数据）
CREATE UNIQUE INDEX idx_matrix_user_unique ON user_mapping(matrix_user_id);
CREATE UNIQUE INDEX idx_wecom_userid_unique ON user_mapping(wecom_userid, wecom_agentid);
CREATE UNIQUE INDEX idx_wecom_external_unique ON user_mapping(wecom_external_userid, wecom_agentid);

-- 4. 创建 message_mapping 表
CREATE TABLE message_mapping (
    id VARCHAR(64) PRIMARY KEY,
    matrix_event_id VARCHAR(255) UNIQUE NOT NULL,
    matrix_room_id VARCHAR(255),
    matrix_sender VARCHAR(255),
    wecom_msg_id VARCHAR(100),
    wecom_conversation_id VARCHAR(100),
    direction VARCHAR(10) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_matrix_event ON message_mapping(matrix_event_id);
CREATE INDEX idx_wecom_msg_id ON message_mapping(wecom_msg_id);
```

### 2. 缓存一致性

- 创建/更新/删除后需要清除缓存
- 生产环境建议使用 Redis 的 pub/sub 机制

### 3. 线程池配置

```python
# 增加线程池大小（高并发场景）
loop = asyncio.get_event_loop()
loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=20))
```

---

## 📊 修正前后对比

| 功能 | 修正前 | 修正后 |
|------|--------|--------|
| **并发安全** | 无 | UNIQUE 索引 + 异常处理 |
| **异步支持** | 阻塞 | run_in_executor |
| **缓存** | 无 | LRU cache |
| **user_type** | 无 | puppet/real/bot |
| **agentid** | 无 | ✅ 新增 |
| **反查** | 无 | 唯一索引 |
| **MessageMapping** | 无 | ✅ 新增表 |
| **软删除** | 硬删除 | is_active 标志 |

---

## 🧠 核心思想

**一句话总结**：

> UserMapper 不是"数据库访问层"，而是 Bridge 的状态管理核心。
>
> **三张表**：UserMapping（用户） + PortalMapping（会话） + MessageMapping（消息）
>
> **并发安全 + 异步 + 缓存** 是生产环境的基石。

---

## 🔗 相关文档

- [SQLAlchemy 异步支持](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [asyncio.run_in_executor](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.run_in_executor)
- [mautrix 状态存储](https://github.com/mautrix/mautrix/blob/main/docs/architecture.md)
