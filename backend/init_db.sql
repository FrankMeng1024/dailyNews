-- AI News Database Schema v2
-- 新版状态机架构
-- processing_status: created → fetching → verifying → translating → refining → complete
-- visibility_status: inactive → active / skip / failed

-- ============================================
-- 1. 用户表
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    openid VARCHAR(64) NOT NULL UNIQUE,
    session_key VARCHAR(128),
    nickname VARCHAR(64),
    avatar_url VARCHAR(512),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_openid ON users (openid);

-- ============================================
-- 2. 用户设置表
-- ============================================
CREATE TABLE IF NOT EXISTS user_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    fetch_hours JSON NOT NULL,
    importance_threshold DECIMAL(3, 2),
    quality_level VARCHAR(20) DEFAULT 'standard',
    theme VARCHAR(6),
    audio_language VARCHAR(9),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_user_settings_user_id ON user_settings (user_id);

-- ============================================
-- 3. 新闻表（核心表 - 新版状态机）
-- ============================================
CREATE TABLE IF NOT EXISTS news (
    -- 基础字段
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id VARCHAR(128) UNIQUE,

    -- 标题
    title VARCHAR(512) NOT NULL,
    title_zh VARCHAR(512),

    -- 来源
    source_name VARCHAR(128) NOT NULL,
    source_url VARCHAR(1024),
    author VARCHAR(256),

    -- 内容
    original_content TEXT,
    content TEXT,
    summary TEXT,
    image_url VARCHAR(1024),

    -- 时间
    published_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 状态机核心字段
    processing_status VARCHAR(32) DEFAULT 'created',
    visibility_status VARCHAR(32) DEFAULT 'inactive',

    -- 错误信息（统一）
    last_error VARCHAR(512),
    error_step VARCHAR(32),
    retry_count INTEGER DEFAULT 0,

    -- 评分
    quality_score DECIMAL(5, 4),
    source_authority_score DECIMAL(5, 4),
    content_depth_score DECIMAL(5, 4),
    timeliness_score DECIMAL(5, 4),

    -- 验证
    verification_score DECIMAL(5, 4),
    verification_result JSON,

    -- 元数据
    source_type VARCHAR(32) DEFAULT 'news',
    source_tier INTEGER DEFAULT 3
);

-- 新闻表索引
CREATE INDEX IF NOT EXISTS ix_news_published_at ON news (published_at);
CREATE INDEX IF NOT EXISTS ix_news_created_at ON news (created_at);
CREATE INDEX IF NOT EXISTS ix_news_processing_status ON news (processing_status);
CREATE INDEX IF NOT EXISTS ix_news_visibility_status ON news (visibility_status);
CREATE INDEX IF NOT EXISTS ix_news_source_type ON news (source_type);
CREATE INDEX IF NOT EXISTS ix_news_source_tier ON news (source_tier);

-- ============================================
-- 4. 系统配置表
-- ============================================
CREATE TABLE IF NOT EXISTS system_config (
    key VARCHAR(128) PRIMARY KEY,
    value TEXT,
    updated_at DATETIME,
    created_at DATETIME
);

-- ============================================
-- 5. 拉取历史表（新版）
-- ============================================
CREATE TABLE IF NOT EXISTS fetch_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id VARCHAR(64) UNIQUE,

    -- 统计
    found_count INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0,
    skip_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,

    -- 状态
    status VARCHAR(32) DEFAULT 'running',
    error_message TEXT,

    -- 时间
    started_at DATETIME NOT NULL,
    completed_at DATETIME
);

CREATE INDEX IF NOT EXISTS ix_fetch_history_task_id ON fetch_history (task_id);
CREATE INDEX IF NOT EXISTS ix_fetch_history_status ON fetch_history (status);

-- ============================================
-- 6. 音频记录表
-- ============================================
CREATE TABLE IF NOT EXISTS audio_recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title VARCHAR(256) NOT NULL,
    file_path VARCHAR(512) NOT NULL,
    file_size INTEGER,
    duration INTEGER,
    language VARCHAR(9) NOT NULL,
    status VARCHAR(10) DEFAULT 'pending',
    error_message TEXT,
    transcript JSON,
    is_favorite BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_audio_recordings_user_id ON audio_recordings (user_id);
CREATE INDEX IF NOT EXISTS ix_audio_recordings_status ON audio_recordings (status);
CREATE INDEX IF NOT EXISTS ix_audio_recordings_created_at ON audio_recordings (created_at);

-- ============================================
-- 7. 音频-新闻关联表
-- ============================================
CREATE TABLE IF NOT EXISTS audio_news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audio_id INTEGER NOT NULL,
    news_id INTEGER NOT NULL,
    display_order INTEGER NOT NULL,
    FOREIGN KEY(audio_id) REFERENCES audio_recordings (id) ON DELETE CASCADE,
    FOREIGN KEY(news_id) REFERENCES news (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_audio_news_audio_id ON audio_news (audio_id);
CREATE INDEX IF NOT EXISTS ix_audio_news_news_id ON audio_news (news_id);

-- ============================================
-- 8. 重试历史表
-- ============================================
CREATE TABLE IF NOT EXISTS retry_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_type VARCHAR(50),
    processed_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_retry_history_created_at ON retry_history (created_at);
