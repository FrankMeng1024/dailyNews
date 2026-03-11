-- AI News Database Schema
-- 开发和生产环境统一使用此脚本初始化数据库
-- 修改表结构时，直接修改此文件中的 CREATE TABLE 语句

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
    importance_threshold DECIMAL(3, 2),  -- DEPRECATED, kept for compatibility
    quality_level VARCHAR(20) DEFAULT 'standard',  -- NEW: premium/standard/all
    theme VARCHAR(6),
    audio_language VARCHAR(9),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_user_settings_user_id ON user_settings (user_id);

-- ============================================
-- 3. 新闻表（核心表）
-- ============================================
CREATE TABLE IF NOT EXISTS news (
    -- 基础字段
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id VARCHAR(128) UNIQUE,  -- URL 的 MD5 hash，用于去重
    title VARCHAR(512) NOT NULL,
    title_zh VARCHAR(512),  -- 中文翻译标题

    -- 来源信息
    source_name VARCHAR(128) NOT NULL,
    source_url VARCHAR(1024),
    author VARCHAR(256),

    -- 内容字段
    content TEXT,  -- GLM 生成的摘要（用于展示）
    summary TEXT,  -- 已废弃，保留兼容
    original_content TEXT,  -- 完整抓取的文章内容
    content_status VARCHAR(32) DEFAULT 'pending',  -- pending/generating/ready/failed
    image_url VARCHAR(1024),

    -- 时间戳（全部使用 UTC 时区）
    published_at DATETIME NOT NULL,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 评分字段
    api_score DECIMAL(5, 4),  -- NewsAPI 相关性评分
    glm_score DECIMAL(5, 4),  -- GLM 重要性评分
    final_score DECIMAL(5, 4),  -- 综合质量评分 (0-1)

    -- 质量评分细分（新增）
    source_authority_score DECIMAL(5, 4),  -- 来源权威性 (40%)
    content_depth_score DECIMAL(5, 4),  -- 内容深度 (25%)
    timeliness_score DECIMAL(5, 4),  -- 时效性 (15%)
    ai_relevance_score DECIMAL(5, 4),  -- AI 相关性 (10%)
    technical_credibility_score DECIMAL(5, 4),  -- 技术可信度 (10%)
    quality_breakdown JSON,  -- 质量评分详细breakdown

    -- 内容分析
    entity_count INTEGER DEFAULT 0,  -- 技术实体计数
    content_length INTEGER DEFAULT 0,  -- 内容字符数

    -- 内容类型和格式
    source_type VARCHAR(32) DEFAULT 'news',  -- news/blog/paper/discussion/podcast/video
    content_format VARCHAR(32) DEFAULT 'text',  -- text/audio/video/mixed
    media_duration INTEGER,  -- 媒体时长（秒）
    is_verified BOOLEAN DEFAULT 0,  -- 是否为验证来源
    source_tier INTEGER DEFAULT 3,  -- 来源优先级 (1=最高, 4=最低)

    -- 分类
    category VARCHAR(64) DEFAULT 'ai',

    -- GLM 重试机制
    glm_retry_count INTEGER DEFAULT 0,
    glm_last_error VARCHAR(512),
    glm_next_retry_at DATETIME
);

-- 新闻表索引
CREATE INDEX IF NOT EXISTS ix_news_published_at ON news (published_at);
CREATE INDEX IF NOT EXISTS ix_news_fetched_at ON news (fetched_at);
CREATE INDEX IF NOT EXISTS ix_news_category ON news (category);
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
-- 5. 拉取历史表
-- ============================================
CREATE TABLE IF NOT EXISTS fetch_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetch_type VARCHAR(32),  -- rss/newsapi/manual
    source_name VARCHAR(128),
    started_at DATETIME NOT NULL,
    completed_at DATETIME,
    status VARCHAR(32) DEFAULT 'running',  -- running/completed/failed
    articles_found INTEGER DEFAULT 0,
    articles_new INTEGER DEFAULT 0,
    articles_filtered INTEGER DEFAULT 0,  -- 被质量过滤的数量
    error_message TEXT,
    fetch_metadata JSON  -- 额外的元数据
);

CREATE INDEX IF NOT EXISTS ix_fetch_history_fetch_type ON fetch_history (fetch_type);
CREATE INDEX IF NOT EXISTS ix_fetch_history_source_name ON fetch_history (source_name);

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
    status VARCHAR(10) DEFAULT 'pending',  -- pending/processing/completed/failed
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
CREATE INDEX IF NOT EXISTS ix_audio_recordings_is_favorite ON audio_recordings (is_favorite);

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
-- 8. 内容重试历史表
-- ============================================
CREATE TABLE IF NOT EXISTS retry_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_type VARCHAR(50),  -- 'auto' or 'manual'
    processed_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_retry_history_trigger_type ON retry_history (trigger_type);
CREATE INDEX IF NOT EXISTS ix_retry_history_created_at ON retry_history (created_at);
