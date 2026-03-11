"""
动态配置服务 - 从数据库读取配置，支持运行时修改

所有硬编码的魔法数字都提取到这里，通过数据库存储支持动态调整
"""

from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
import json
import time
import logging

from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

# 默认配置值（代码中的 fallback）
DEFAULT_CONFIG = {
    # 内容长度阈值
    "min_content_length": 200,          # 最小有效内容长度
    "min_summary_length": 50,           # 最小摘要长度
    "min_paragraph_length": 30,         # 最小段落长度
    "min_fallback_paragraph_length": 50,  # 回退时最小段落长度
    "min_paragraphs_for_fallback": 3,   # 回退时最少段落数

    # 内容截断限制
    "max_content_for_scrape": 8000,     # 爬取内容最大长度
    "max_content_for_glm_prompt": 4000, # GLM 提示词中内容最大长度
    "max_description_length": 500,      # 描述最大长度
    "max_error_message_length": 500,    # 错误信息最大长度

    # 批处理大小
    "scrape_batch_size": 5,             # 爬虫并发批次大小
    "translate_batch_size": 8,          # 翻译批次大小
    "glm_content_batch_size": 1,        # GLM 内容生成批次大小

    # API 超时设置 (秒)
    "scrape_timeout": 30,               # 爬虫超时
    "glm_api_timeout": 90,              # GLM API 超时
    "glm_tts_timeout": 300,             # GLM TTS 超时
    "image_extract_timeout": 15,        # 图片提取超时

    # 重试配置
    "glm_retry_intervals": [1, 3, 6, 9, 12],      # GLM 重试间隔（分钟）
    "scrape_retry_intervals": [5, 15, 60, 180, 360],  # 爬虫重试间隔（分钟）
    "title_retry_intervals": [1, 3, 6, 9, 12],    # 标题翻译重试间隔（分钟）
    "max_retries": 5,                   # 最大重试次数
}


class ConfigService:
    """动态配置服务 - 从数据库读取，支持运行时修改"""

    CONFIG_KEY = "fetch_config"
    _cache: Dict[str, Any] = {}
    _cache_time: float = 0
    CACHE_TTL = 60  # 缓存60秒

    @classmethod
    def get(cls, db: Session, key: str, default: Any = None) -> Any:
        """获取配置值

        Args:
            db: 数据库会话
            key: 配置键
            default: 默认值（如果未提供，使用 DEFAULT_CONFIG 中的值）

        Returns:
            配置值
        """
        config = cls._load_config(db)
        if default is not None:
            return config.get(key, default)
        return config.get(key, DEFAULT_CONFIG.get(key))

    @classmethod
    def get_all(cls, db: Session) -> Dict[str, Any]:
        """获取所有配置"""
        return cls._load_config(db)

    @classmethod
    def set(cls, db: Session, key: str, value: Any) -> None:
        """设置配置值

        Args:
            db: 数据库会话
            key: 配置键
            value: 配置值
        """
        config = cls._load_config(db)
        config[key] = value
        cls._save_config(db, config)
        logger.info(f"Config updated: {key} = {value}")

    @classmethod
    def set_many(cls, db: Session, updates: Dict[str, Any]) -> None:
        """批量设置配置值

        Args:
            db: 数据库会话
            updates: 配置更新字典
        """
        config = cls._load_config(db)
        config.update(updates)
        cls._save_config(db, config)
        logger.info(f"Config batch updated: {list(updates.keys())}")

    @classmethod
    def reset_to_default(cls, db: Session, key: Optional[str] = None) -> None:
        """重置配置到默认值

        Args:
            db: 数据库会话
            key: 要重置的配置键，如果为 None 则重置所有
        """
        if key is None:
            cls._save_config(db, DEFAULT_CONFIG.copy())
            logger.info("All config reset to default")
        else:
            config = cls._load_config(db)
            if key in DEFAULT_CONFIG:
                config[key] = DEFAULT_CONFIG[key]
                cls._save_config(db, config)
                logger.info(f"Config {key} reset to default: {DEFAULT_CONFIG[key]}")

    @classmethod
    def _load_config(cls, db: Session) -> Dict[str, Any]:
        """从数据库加载配置（带缓存）"""
        now = time.time()

        # 检查缓存是否有效
        if cls._cache and (now - cls._cache_time) < cls.CACHE_TTL:
            return cls._cache.copy()

        try:
            record = db.query(SystemConfig).filter(
                SystemConfig.key == cls.CONFIG_KEY
            ).first()

            if record and record.value:
                # 合并默认配置和数据库配置
                db_config = json.loads(record.value)
                cls._cache = {**DEFAULT_CONFIG, **db_config}
            else:
                cls._cache = DEFAULT_CONFIG.copy()

            cls._cache_time = now
            return cls._cache.copy()

        except Exception as e:
            logger.error(f"Failed to load config from database: {e}")
            # 出错时返回默认配置
            return DEFAULT_CONFIG.copy()

    @classmethod
    def _save_config(cls, db: Session, config: Dict[str, Any]) -> None:
        """保存配置到数据库"""
        from datetime import datetime, timezone

        try:
            record = db.query(SystemConfig).filter(
                SystemConfig.key == cls.CONFIG_KEY
            ).first()

            if record:
                record.value = json.dumps(config, ensure_ascii=False)
                record.updated_at = datetime.now(timezone.utc)
            else:
                record = SystemConfig(
                    key=cls.CONFIG_KEY,
                    value=json.dumps(config, ensure_ascii=False)
                )
                db.add(record)

            db.commit()

            # 更新缓存
            cls._cache = config.copy()
            cls._cache_time = time.time()

        except Exception as e:
            logger.error(f"Failed to save config to database: {e}")
            db.rollback()
            raise

    @classmethod
    def invalidate_cache(cls) -> None:
        """使缓存失效，强制下次从数据库读取"""
        cls._cache = {}
        cls._cache_time = 0

    @classmethod
    def get_defaults(cls) -> Dict[str, Any]:
        """获取默认配置（不需要数据库连接）"""
        return DEFAULT_CONFIG.copy()
