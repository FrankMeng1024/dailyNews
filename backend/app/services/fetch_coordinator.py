"""
Fetch coordinator service for managing time-window based incremental fetching

Handles:
- Last fetch time tracking
- Time-window based fetching with safety overlap
- Priority-based source limiting
- Quality filtering
"""

import json
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.system_config import SystemConfig, FetchHistory
from app.models.news import News
from app.config_sources.source_config import (
    get_source_authority,
    get_fetch_limit,
    SourceTier,
    MIN_QUALITY_SCORE_ARCHIVE,
    DEDUPLICATION_WINDOW_DAYS
)


class FetchCoordinator:
    """Coordinates time-window based fetching with quality control"""

    # Safety overlap to prevent missing articles due to timing issues
    OVERLAP_WINDOW_MINUTES = 30

    # Maximum age of articles to fetch (1 day / 24 hours)
    # This ensures we only fetch recent news, even if last fetch was long ago
    MAX_FETCH_AGE_DAYS = 1

    # Config keys
    CONFIG_KEY_LAST_FETCH = "last_successful_fetch_time"
    CONFIG_KEY_LAST_FETCH_RSS = "last_successful_fetch_time_rss"
    CONFIG_KEY_LAST_FETCH_NEWSAPI = "last_successful_fetch_time_newsapi"

    def __init__(self, db: Session):
        self.db = db

    def get_last_fetch_time(self, fetch_type: str = "all") -> datetime:
        """
        Get the last successful fetch time

        Args:
            fetch_type: Type of fetch (all/rss/newsapi)

        Returns:
            Last fetch time (UTC timezone-aware)
        """
        # Choose config key based on fetch type
        if fetch_type == "rss":
            config_key = self.CONFIG_KEY_LAST_FETCH_RSS
        elif fetch_type == "newsapi":
            config_key = self.CONFIG_KEY_LAST_FETCH_NEWSAPI
        else:
            config_key = self.CONFIG_KEY_LAST_FETCH

        config = self.db.query(SystemConfig).filter(
            SystemConfig.key == config_key
        ).first()

        if config and config.value:
            # Parse ISO format datetime
            last_fetch = datetime.fromisoformat(config.value)
            # Ensure UTC timezone
            if not last_fetch.tzinfo:
                last_fetch = last_fetch.replace(tzinfo=timezone.utc)
            return last_fetch

        # Default: 24 hours ago
        return datetime.now(timezone.utc) - timedelta(days=1)

    def update_last_fetch_time(self, fetch_time: datetime, fetch_type: str = "all"):
        """
        Update the last successful fetch time

        Args:
            fetch_time: Fetch completion time (UTC)
            fetch_type: Type of fetch (all/rss/newsapi)
        """
        # Choose config key based on fetch type
        if fetch_type == "rss":
            config_key = self.CONFIG_KEY_LAST_FETCH_RSS
        elif fetch_type == "newsapi":
            config_key = self.CONFIG_KEY_LAST_FETCH_NEWSAPI
        else:
            config_key = self.CONFIG_KEY_LAST_FETCH

        # Ensure UTC timezone
        if not fetch_time.tzinfo:
            fetch_time = fetch_time.replace(tzinfo=timezone.utc)

        config = self.db.query(SystemConfig).filter(
            SystemConfig.key == config_key
        ).first()

        if config:
            config.value = fetch_time.isoformat()
            config.updated_at = datetime.now(timezone.utc)
        else:
            config = SystemConfig(
                key=config_key,
                value=fetch_time.isoformat()
            )
            self.db.add(config)

        self.db.commit()

    def get_fetch_time_window(
        self,
        fetch_type: str = "all",
        custom_since: Optional[datetime] = None
    ) -> Dict[str, datetime]:
        """
        Get the time window for fetching (with safety overlap)

        Args:
            fetch_type: Type of fetch (all/rss/newsapi)
            custom_since: Custom start time (overrides last_fetch_time)

        Returns:
            Dict with 'start', 'end', 'overlap_start'
        """
        end_time = datetime.now(timezone.utc)

        if custom_since:
            last_fetch = custom_since
        else:
            last_fetch = self.get_last_fetch_time(fetch_type)

        # Add safety overlap (30 minutes earlier)
        overlap_start = last_fetch - timedelta(minutes=self.OVERLAP_WINDOW_MINUTES)

        # Don't go beyond max age
        max_age_start = end_time - timedelta(days=self.MAX_FETCH_AGE_DAYS)
        if overlap_start < max_age_start:
            overlap_start = max_age_start

        return {
            'start': last_fetch,
            'end': end_time,
            'overlap_start': overlap_start  # Use this for actual fetching
        }

    def create_fetch_record(
        self,
        fetch_type: str,
        source_name: str = "all"
    ) -> FetchHistory:
        """
        Create a new fetch history record

        Args:
            fetch_type: Type of fetch (rss/newsapi/manual)
            source_name: Source identifier

        Returns:
            FetchHistory record
        """
        record = FetchHistory(
            fetch_type=fetch_type,
            source_name=source_name,
            started_at=datetime.now(timezone.utc),
            status="running"
        )
        self.db.add(record)
        self.db.commit()
        return record

    def should_fetch_source(
        self,
        source_name: str,
        current_count: int
    ) -> bool:
        """
        Check if should continue fetching from a source based on tier limits

        Args:
            source_name: Name of the source
            current_count: Number of articles already fetched from this source

        Returns:
            True if should continue fetching
        """
        source_info = get_source_authority(source_name)
        tier = source_info['tier']
        limit = get_fetch_limit(tier)

        # No limit (tier 1)
        if limit is None:
            return True

        # Check if under limit
        return current_count < limit

    def is_duplicate(
        self,
        external_id: str,
        published_at: datetime,
        dedup_window_days: int = DEDUPLICATION_WINDOW_DAYS
    ) -> bool:
        """
        Check if article is a duplicate within the deduplication window

        Args:
            external_id: External ID (URL hash)
            published_at: Published time
            dedup_window_days: Deduplication window in days

        Returns:
            True if duplicate found
        """
        # Check by external_id
        exists = self.db.query(News).filter(
            News.external_id == external_id
        ).first()

        if not exists:
            return False

        # If found, check if within dedup window
        if not published_at.tzinfo:
            published_at = published_at.replace(tzinfo=timezone.utc)

        window_start = datetime.now(timezone.utc) - timedelta(days=dedup_window_days)

        # If existing article is old (outside window), allow "refresh"
        if exists.published_at < window_start:
            return False

        return True

    def filter_by_time_window(
        self,
        articles: List[Dict],
        time_window: Dict[str, datetime]
    ) -> List[Dict]:
        """
        Filter articles by time window

        Args:
            articles: List of article dicts with 'published_at'
            time_window: Time window from get_fetch_time_window()

        Returns:
            Filtered list of articles
        """
        filtered = []
        overlap_start = time_window['overlap_start']
        end_time = time_window['end']

        for article in articles:
            published = article.get('published_at')
            if not published:
                continue

            # Ensure timezone-aware
            if not published.tzinfo:
                published = published.replace(tzinfo=timezone.utc)

            # Check if within window
            if overlap_start <= published <= end_time:
                filtered.append(article)

        return filtered

    def get_fetch_statistics(
        self,
        hours: int = 24,
        fetch_type: Optional[str] = None
    ) -> Dict:
        """
        Get fetch statistics for the last N hours

        Args:
            hours: Number of hours to look back
            fetch_type: Optional filter by fetch type

        Returns:
            Dict with statistics
        """
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

        query = self.db.query(FetchHistory).filter(
            FetchHistory.started_at >= since
        )

        if fetch_type:
            query = query.filter(FetchHistory.fetch_type == fetch_type)

        records = query.all()

        total_fetches = len(records)
        successful = len([r for r in records if r.status == "completed"])
        failed = len([r for r in records if r.status == "failed"])
        total_found = sum(r.articles_found or 0 for r in records)
        total_new = sum(r.articles_new or 0 for r in records)
        total_filtered = sum(r.articles_filtered or 0 for r in records)

        return {
            'period_hours': hours,
            'total_fetches': total_fetches,
            'successful': successful,
            'failed': failed,
            'articles_found': total_found,
            'articles_new': total_new,
            'articles_filtered': total_filtered,
            'success_rate': round(successful / total_fetches * 100, 2) if total_fetches > 0 else 0
        }

    def cleanup_old_duplicates(
        self,
        keep_days: int = DEDUPLICATION_WINDOW_DAYS
    ) -> int:
        """
        Clean up old articles outside deduplication window (optional maintenance)

        Args:
            keep_days: Number of days to keep

        Returns:
            Number of articles deleted
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)

        # Only delete articles with very low quality scores
        deleted = self.db.query(News).filter(
            News.published_at < cutoff,
            News.final_score < MIN_QUALITY_SCORE_ARCHIVE
        ).delete()

        self.db.commit()
        return deleted


def get_fetch_coordinator(db: Session) -> FetchCoordinator:
    """Get fetch coordinator instance"""
    return FetchCoordinator(db)
