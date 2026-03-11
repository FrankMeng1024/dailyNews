"""
Quality level configuration for priority-based filtering and user preferences
"""
from typing import Dict
from enum import Enum


class QualityLevel(str, Enum):
    """3-tier quality level system for user preferences"""
    PREMIUM = "premium"    # 精选内容
    STANDARD = "standard"  # 标准阅读
    ALL = "all"            # 全部文章


# Default thresholds (will be overridden by statistics)
DEFAULT_QUALITY_THRESHOLDS = {
    QualityLevel.PREMIUM: 0.70,   # Top tier only (will be overridden by dynamic calculation)
    QualityLevel.STANDARD: 0.50,  # Standard + Premium (will be overridden by dynamic calculation)
    QualityLevel.ALL: 0.30,       # Fixed: filter out garbage content (score < 0.3)
}

# Display names for frontend
QUALITY_LEVEL_NAMES = {
    QualityLevel.PREMIUM: {"zh": "精选", "en": "Premium"},
    QualityLevel.STANDARD: {"zh": "标准", "en": "Standard"},
    QualityLevel.ALL: {"zh": "全部", "en": "All"},
}

# Description for each level
QUALITY_LEVEL_DESCRIPTIONS = {
    QualityLevel.PREMIUM: {
        "zh": "高质量深度内容，来自权威来源",
        "en": "High-quality in-depth content from authoritative sources"
    },
    QualityLevel.STANDARD: {
        "zh": "标准质量文章，适合日常阅读",
        "en": "Standard quality articles for daily reading"
    },
    QualityLevel.ALL: {
        "zh": "所有文章，包含社区讨论和简讯",
        "en": "All articles including community posts and brief news"
    },
}
