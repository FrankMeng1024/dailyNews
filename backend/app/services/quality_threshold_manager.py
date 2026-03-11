"""
Manages dynamic quality thresholds based on actual score distribution
"""
import json
from typing import Dict, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.news import News
from app.models.system_config import SystemConfig
from app.config_sources.quality_levels import (
    QualityLevel,
    DEFAULT_QUALITY_THRESHOLDS
)


class QualityThresholdManager:
    """Calculate and store quality level thresholds based on actual data distribution"""

    CONFIG_KEY = "quality_thresholds"

    @staticmethod
    def calculate_thresholds(db: Session) -> Dict[str, float]:
        """
        Calculate thresholds based on score distribution
        Uses terciles (33rd and 67th percentiles) of actual scores

        Note:
        - PREMIUM and STANDARD use dynamic percentiles (67th and 33rd)
        - ALL is fixed at 0.30 to filter out truly low-quality content

        Args:
            db: Database session

        Returns:
            Dict mapping quality levels to score thresholds
        """
        # Get all scores, ordered
        scores = db.query(News.final_score)\
            .filter(News.final_score.isnot(None))\
            .order_by(News.final_score)\
            .all()

        if not scores or len(scores) < 10:
            # Not enough data, use defaults
            return DEFAULT_QUALITY_THRESHOLDS

        score_list = [s[0] for s in scores]
        count = len(score_list)

        # Calculate tercile thresholds
        premium_idx = int(count * 0.67)  # Top 33%
        standard_idx = int(count * 0.33)  # Top 67%

        thresholds = {
            QualityLevel.PREMIUM: round(score_list[premium_idx], 2),
            QualityLevel.STANDARD: round(score_list[standard_idx], 2),
            QualityLevel.ALL: 0.30,  # Fixed threshold to filter garbage content
        }

        return thresholds

    @staticmethod
    def save_thresholds(db: Session, thresholds: Dict[str, float]):
        """Save thresholds to system_config table"""
        config = db.query(SystemConfig)\
            .filter(SystemConfig.key == QualityThresholdManager.CONFIG_KEY)\
            .first()

        if not config:
            config = SystemConfig(key=QualityThresholdManager.CONFIG_KEY)
            db.add(config)

        # Convert enum keys to strings and Decimal values to float
        serializable_thresholds = {
            (k.value if hasattr(k, 'value') else k): float(v)
            for k, v in thresholds.items()
        }
        config.value = json.dumps(serializable_thresholds)
        db.commit()

    @staticmethod
    def get_thresholds(db: Session) -> Dict[str, float]:
        """Get current thresholds from system_config or defaults"""
        config = db.query(SystemConfig)\
            .filter(SystemConfig.key == QualityThresholdManager.CONFIG_KEY)\
            .first()

        if config and config.value:
            try:
                return json.loads(config.value)
            except:
                pass

        return DEFAULT_QUALITY_THRESHOLDS

    @staticmethod
    def get_score_statistics(db: Session) -> Dict:
        """Get statistical summary of scores for admin dashboard"""
        stats = db.query(
            func.count(News.id).label('total'),
            func.min(News.final_score).label('min'),
            func.max(News.final_score).label('max'),
            func.avg(News.final_score).label('avg')
        ).filter(News.final_score.isnot(None)).first()

        if not stats or not stats.total:
            return {
                "total": 0,
                "min_score": 0,
                "max_score": 0,
                "avg_score": 0,
                "thresholds": DEFAULT_QUALITY_THRESHOLDS,
                "distribution": {
                    QualityLevel.PREMIUM: 0,
                    QualityLevel.STANDARD: 0,
                    QualityLevel.ALL: 0,
                }
            }

        thresholds = QualityThresholdManager.get_thresholds(db)

        # Count articles in each tier
        premium_count = db.query(News).filter(
            News.final_score >= thresholds[QualityLevel.PREMIUM]
        ).count()

        standard_count = db.query(News).filter(
            News.final_score >= thresholds[QualityLevel.STANDARD],
            News.final_score < thresholds[QualityLevel.PREMIUM]
        ).count()

        all_count = db.query(News).filter(
            News.final_score < thresholds[QualityLevel.STANDARD]
        ).count()

        return {
            "total": stats.total,
            "min_score": round(stats.min, 4) if stats.min else 0,
            "max_score": round(stats.max, 4) if stats.max else 0,
            "avg_score": round(stats.avg, 4) if stats.avg else 0,
            "thresholds": thresholds,
            "distribution": {
                QualityLevel.PREMIUM: premium_count,
                QualityLevel.STANDARD: standard_count,
                QualityLevel.ALL: all_count,
            }
        }
