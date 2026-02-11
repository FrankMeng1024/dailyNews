-- AI News Database Schema

-- Users table (WeChat authentication)
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    openid VARCHAR(64) NOT NULL UNIQUE COMMENT 'WeChat OpenID',
    session_key VARCHAR(128) COMMENT 'WeChat session key (encrypted)',
    nickname VARCHAR(64) DEFAULT NULL,
    avatar_url VARCHAR(512) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_openid (openid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- User settings table
CREATE TABLE IF NOT EXISTS user_settings (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL UNIQUE,
    fetch_hours JSON NOT NULL DEFAULT ('["8", "12", "18"]') COMMENT 'Hours to auto-fetch (24h format)',
    importance_threshold DECIMAL(3,2) DEFAULT 0.50 COMMENT 'Min importance score (0.00-1.00)',
    theme ENUM('light', 'dark', 'system') DEFAULT 'system',
    audio_language ENUM('zh', 'en', 'bilingual') DEFAULT 'zh',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- News articles table
CREATE TABLE IF NOT EXISTS news (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    external_id VARCHAR(128) UNIQUE COMMENT 'NewsAPI article ID or URL hash',
    title VARCHAR(512) NOT NULL,
    source_name VARCHAR(128) NOT NULL,
    source_url VARCHAR(1024),
    author VARCHAR(256),
    content TEXT COMMENT 'Original article content',
    summary TEXT COMMENT 'GLM-generated summary',
    image_url VARCHAR(1024),
    published_at TIMESTAMP NOT NULL,
    api_score DECIMAL(5,4) DEFAULT NULL COMMENT 'NewsAPI relevance score',
    glm_score DECIMAL(5,4) DEFAULT NULL COMMENT 'GLM importance score (0-1)',
    final_score DECIMAL(5,4) DEFAULT NULL COMMENT 'Hybrid importance score',
    category VARCHAR(64) DEFAULT 'ai' COMMENT 'News category for future extension',
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_published_at (published_at DESC),
    INDEX idx_final_score (final_score DESC),
    INDEX idx_category (category),
    INDEX idx_fetched_at (fetched_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Audio recordings table
CREATE TABLE IF NOT EXISTS audio_recordings (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    title VARCHAR(256) NOT NULL COMMENT 'Auto-generated or user-defined title',
    file_path VARCHAR(512) NOT NULL COMMENT 'Relative path to audio file',
    file_size BIGINT DEFAULT 0 COMMENT 'File size in bytes',
    duration INT DEFAULT 0 COMMENT 'Duration in seconds',
    language ENUM('zh', 'en', 'bilingual') NOT NULL DEFAULT 'zh',
    status ENUM('pending', 'processing', 'completed', 'failed') DEFAULT 'pending',
    error_message TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Audio-News junction table (many-to-many)
CREATE TABLE IF NOT EXISTS audio_news (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    audio_id BIGINT NOT NULL,
    news_id BIGINT NOT NULL,
    display_order INT NOT NULL DEFAULT 0 COMMENT 'Order of news in audio',
    FOREIGN KEY (audio_id) REFERENCES audio_recordings(id) ON DELETE CASCADE,
    FOREIGN KEY (news_id) REFERENCES news(id) ON DELETE CASCADE,
    UNIQUE KEY uk_audio_news (audio_id, news_id),
    INDEX idx_audio_id (audio_id),
    INDEX idx_news_id (news_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
