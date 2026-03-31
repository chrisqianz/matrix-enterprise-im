-- ============================================================
-- 企业微信-Matrix 桥接服务 - 数据库迁移脚本
-- 版本：3.0.0
-- 日期：2026-03-30
-- ============================================================

-- ============================================================
-- 1. 用户映射表 (user_mapping)
-- ============================================================

CREATE TABLE IF NOT EXISTS user_mapping (
    id VARCHAR(64) PRIMARY KEY,
    matrix_user_id VARCHAR(255) NOT NULL,
    wecom_userid VARCHAR(100),
    wecom_external_userid VARCHAR(100),
    wecom_unionid VARCHAR(100),
    wecom_agentid VARCHAR(50),           -- ✅ 新增：应用 agentid
    
    -- ✅ 新增：用户类型
    user_type VARCHAR(20) DEFAULT 'puppet',  -- puppet, real, bot
    
    is_external BOOLEAN DEFAULT FALSE,
    nickname VARCHAR(255),
    avatar_url VARCHAR(500),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 软删除标志
    is_active BOOLEAN DEFAULT TRUE,
    deleted_at TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_user_mapping_matrix_user ON user_mapping(matrix_user_id);
CREATE INDEX IF NOT EXISTS idx_user_mapping_wecom_userid ON user_mapping(wecom_userid);
CREATE INDEX IF NOT EXISTS idx_user_mapping_external_userid ON user_mapping(wecom_external_userid);
CREATE INDEX IF NOT EXISTS idx_user_mapping_agentid ON user_mapping(wecom_agentid);

-- ✅ 唯一索引（并发安全）
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_mapping_matrix_unique ON user_mapping(matrix_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_mapping_wecom_unique ON user_mapping(wecom_userid, wecom_agentid);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_mapping_external_unique ON user_mapping(wecom_external_userid, wecom_agentid);

-- ============================================================
-- 2. Portal 映射表 (portal_mapping) - 新增核心表
-- ============================================================

CREATE TABLE IF NOT EXISTS portal_mapping (
    id VARCHAR(64) PRIMARY KEY,
    
    -- 会话信息
    conversation_id VARCHAR(100) NOT NULL,      -- 会话 ID（dm_zhangsan, external_ext123, group_chat123）
    conversation_type VARCHAR(20) NOT NULL,      -- dm, external, group
    
    -- Matrix 房间信息
    room_id VARCHAR(255) NOT NULL,               -- Matrix 房间 ID
    room_alias VARCHAR(255),                     -- 房间别名
    
    -- Puppet 用户
    puppet_user_id VARCHAR(255),                 -- Puppet 用户 ID
    
    -- 企业微信目标
    wecom_userid VARCHAR(100),                   -- 企业微信用户 ID（单聊）
    wecom_external_userid VARCHAR(100),          -- 外部联系人 ID
    wecom_group_id VARCHAR(100),                 -- 群 ID
    wecom_agentid VARCHAR(50),                   -- 应用 agentid
    
    -- 房间属性
    is_direct BOOLEAN DEFAULT TRUE,              -- 是否私聊
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 软删除
    is_active BOOLEAN DEFAULT TRUE,
    deleted_at TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_portal_conversation ON portal_mapping(conversation_id);
CREATE INDEX IF NOT EXISTS idx_portal_room_id ON portal_mapping(room_id);
CREATE INDEX IF NOT EXISTS idx_portal_room_alias ON portal_mapping(room_alias);
CREATE INDEX IF NOT EXISTS idx_portal_puppet_user ON portal_mapping(puppet_user_id);
CREATE INDEX IF NOT EXISTS idx_portal_wecom_userid ON portal_mapping(wecom_userid);
CREATE INDEX IF NOT EXISTS idx_portal_external_userid ON portal_mapping(wecom_external_userid);
CREATE INDEX IF NOT EXISTS idx_portal_group_id ON portal_mapping(wecom_group_id);

-- ✅ 唯一索引
CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_conversation_unique ON portal_mapping(conversation_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_room_unique ON portal_mapping(room_id);

-- ============================================================
-- 3. 消息映射表 (message_mapping) - 新增核心表
-- ============================================================

CREATE TABLE IF NOT EXISTS message_mapping (
    id VARCHAR(64) PRIMARY KEY,
    
    -- Matrix 事件信息
    matrix_event_id VARCHAR(255) NOT NULL,
    matrix_room_id VARCHAR(255),
    matrix_sender VARCHAR(255),
    matrix_event_type VARCHAR(50),
    
    -- 企业微信消息信息
    wecom_msg_id VARCHAR(100),
    wecom_conversation_id VARCHAR(100),
    wecom_msg_type VARCHAR(20),
    
    -- 同步方向
    direction VARCHAR(20) NOT NULL,              -- wecom_to_matrix, matrix_to_wecom
    
    -- 同步状态
    status VARCHAR(20) DEFAULT 'pending',         -- pending, success, failed
    error_message TEXT,                          -- 错误信息
    retry_count INTEGER DEFAULT 0,               -- 重试次数
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    synced_at TIMESTAMP                          -- 同步完成时间
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_message_matrix_event ON message_mapping(matrix_event_id);
CREATE INDEX IF NOT EXISTS idx_message_matrix_room ON message_mapping(matrix_room_id);
CREATE INDEX IF NOT EXISTS idx_message_wecom_msg ON message_mapping(wecom_msg_id);
CREATE INDEX IF NOT EXISTS idx_message_direction ON message_mapping(direction);
CREATE INDEX IF NOT EXISTS idx_message_status ON message_mapping(status);
CREATE INDEX IF NOT EXISTS idx_message_created_at ON message_mapping(created_at);

-- ✅ 唯一索引
CREATE UNIQUE INDEX IF NOT EXISTS idx_message_matrix_event_unique ON message_mapping(matrix_event_id);

-- ============================================================
-- 4. 归档表 (archive_message) - 如果不存在则创建
-- ============================================================

CREATE TABLE IF NOT EXISTS archive_message (
    id VARCHAR(64) PRIMARY KEY,
    
    -- 消息基本信息
    message_id VARCHAR(255) NOT NULL,
    msg_type VARCHAR(50) NOT NULL,
    content TEXT,
    
    -- 发送者信息
    sender_id VARCHAR(255),
    sender_name VARCHAR(255),
    sender_wecom_id VARCHAR(100),
    
    -- 接收者信息
    receiver_id VARCHAR(255),
    receiver_name VARCHAR(255),
    receiver_wecom_id VARCHAR(100),
    
    -- 来源平台信息
    source_platform VARCHAR(20) NOT NULL,        -- matrix, wecom
    source_room_id VARCHAR(255),
    source_event_id VARCHAR(255),
    source_msg_id VARCHAR(100),
    
    -- 目标平台信息
    target_platform VARCHAR(20),
    target_room_id VARCHAR(255),
    target_event_id VARCHAR(255),
    target_msg_id VARCHAR(100),
    
    -- 媒体文件信息
    media_url VARCHAR(500),
    media_type VARCHAR(50),
    media_size INTEGER,
    
    -- 元数据
    raw_data JSONB,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    archived_at TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_archive_message_id ON archive_message(message_id);
CREATE INDEX IF NOT EXISTS idx_archive_sender ON archive_message(sender_id);
CREATE INDEX IF NOT EXISTS idx_archive_source_platform ON archive_message(source_platform);
CREATE INDEX IF NOT EXISTS idx_archive_created_at ON archive_message(created_at);
CREATE INDEX IF NOT EXISTS idx_archive_source_event ON archive_message(source_event_id);
CREATE INDEX IF NOT EXISTS idx_archive_target_event ON archive_message(target_event_id);

-- ============================================================
-- 5. 迁移版本表 (schema_migrations)
-- ============================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(50) PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);

-- 记录当前迁移
INSERT INTO schema_migrations (version, description)
VALUES ('3.0.0', '初始 schema - Puppet/Portal/Message 核心表')
ON CONFLICT (version) DO NOTHING;

-- ============================================================
-- 6. 验证查询
-- ============================================================

-- 验证表是否创建成功
SELECT 
    'user_mapping' as table_name, COUNT(*) as row_count FROM user_mapping
UNION ALL
SELECT 'portal_mapping', COUNT(*) FROM portal_mapping
UNION ALL
SELECT 'message_mapping', COUNT(*) FROM message_mapping
UNION ALL
SELECT 'archive_message', COUNT(*) FROM archive_message;

-- 验证索引
SELECT 
    indexname, 
    tablename 
FROM pg_indexes 
WHERE schemaname = 'public' 
AND tablename IN ('user_mapping', 'portal_mapping', 'message_mapping', 'archive_message')
ORDER BY tablename, indexname;

-- ============================================================
-- 迁移完成
-- ============================================================

\echo '✅ 数据库迁移完成！'
\echo '创建表：user_mapping, portal_mapping, message_mapping, archive_message'
\echo '版本：3.0.0'
