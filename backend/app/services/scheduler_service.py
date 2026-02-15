from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from typing import List, Optional
from datetime import datetime
import pytz
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service for managing scheduled news fetch jobs"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            timezone=pytz.timezone(settings.TIMEZONE)
        )
        self._is_running = False

    def start(self):
        """Start the scheduler"""
        if not self._is_running:
            self.scheduler.start()
            self._is_running = True
            logger.info("Scheduler started")

            # Add GLM retry job (runs every minute)
            self.scheduler.add_job(
                self._retry_glm_content_task,
                trigger=IntervalTrigger(minutes=1),
                id="glm_retry_task",
                replace_existing=True,
                name="Retry GLM content generation"
            )
            logger.info("Added GLM retry job (every 1 minute)")

    def shutdown(self):
        """Shutdown the scheduler"""
        if self._is_running:
            self.scheduler.shutdown(wait=False)
            self._is_running = False
            logger.info("Scheduler shutdown")

    def add_fetch_job(self, user_id: int, hour: int) -> str:
        """
        Add a scheduled news fetch job for a user

        Args:
            user_id: User ID
            hour: Hour to run (0-23)

        Returns:
            Job ID
        """
        job_id = f"fetch_news_user_{user_id}_hour_{hour}"

        # Remove existing job if any
        self.remove_job(job_id)

        # Add new job
        self.scheduler.add_job(
            self._fetch_news_task,
            trigger=CronTrigger(hour=hour, minute=0),
            id=job_id,
            args=[user_id],
            replace_existing=True,
            name=f"Fetch news for user {user_id} at {hour}:00"
        )

        logger.info(f"Added fetch job: {job_id}")
        return job_id

    def remove_job(self, job_id: str) -> bool:
        """
        Remove a scheduled job

        Args:
            job_id: Job ID to remove

        Returns:
            True if job was removed, False if not found
        """
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Removed job: {job_id}")
            return True
        except:
            return False

    def update_user_schedule(self, user_id: int, hours: List[int]):
        """
        Update all scheduled jobs for a user

        Args:
            user_id: User ID
            hours: List of hours to schedule (0-23)
        """
        # Remove all existing jobs for this user
        existing_jobs = self.scheduler.get_jobs()
        for job in existing_jobs:
            if job.id.startswith(f"fetch_news_user_{user_id}_"):
                self.scheduler.remove_job(job.id)

        # Add new jobs
        for hour in hours:
            self.add_fetch_job(user_id, hour)

    def get_user_jobs(self, user_id: int) -> List[dict]:
        """
        Get all scheduled jobs for a user

        Args:
            user_id: User ID

        Returns:
            List of job info dicts
        """
        jobs = []
        for job in self.scheduler.get_jobs():
            if job.id.startswith(f"fetch_news_user_{user_id}_"):
                jobs.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None
                })
        return jobs

    async def _fetch_news_task(self, user_id: int):
        """
        Background task to fetch news for a user

        Args:
            user_id: User ID
        """
        from app.database import SessionLocal
        from app.services.news_fetcher import news_fetcher
        from app.services.glm_service import glm_service
        from app.models.news import News

        logger.info(f"Starting scheduled news fetch for user {user_id}")

        db = SessionLocal()
        try:
            # Fetch news
            fetched_count = await news_fetcher.fetch_and_save_news(db, page_size=50)
            logger.info(f"Fetched {fetched_count} new articles")

            # Score unscored news
            if fetched_count > 0:
                unscored_news = db.query(News).filter(News.glm_score == None).all()
                if unscored_news:
                    await glm_service.score_and_update_news(db, unscored_news)
                    logger.info(f"Scored {len(unscored_news)} articles")

        except Exception as e:
            logger.error(f"Error in scheduled fetch: {str(e)}")
        finally:
            db.close()

    async def _retry_glm_content_task(self):
        """
        Background task to retry GLM content generation for failed news items.
        Runs every minute, processes news where:
        - content_status = 'pending'
        - glm_next_retry_at <= now
        - glm_retry_count < 5
        """
        from app.database import SessionLocal
        from app.services.news_fetcher import news_fetcher
        from app.models.news import News

        db = SessionLocal()
        try:
            now = datetime.utcnow()

            # Find news items ready for retry
            retry_news = db.query(News).filter(
                News.content_status == "pending",
                News.glm_next_retry_at != None,
                News.glm_next_retry_at <= now,
                News.glm_retry_count < 5
            ).limit(10).all()

            if not retry_news:
                return

            news_ids = [n.id for n in retry_news]
            logger.info(f"Retrying GLM content for {len(news_ids)} news items: {news_ids}")

            # Generate content
            generated = await news_fetcher.generate_content_for_news(db, news_ids)
            logger.info(f"GLM retry completed: {generated}/{len(news_ids)} succeeded")

        except Exception as e:
            logger.error(f"Error in GLM retry task: {str(e)}")
        finally:
            db.close()


scheduler_service = SchedulerService()
