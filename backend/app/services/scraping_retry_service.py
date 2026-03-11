"""
Service for retrying failed article content scraping

This service handles background retry of articles where scraping failed
(original_content is too short or missing)
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.news import News
from app.services.news_fetcher import news_fetcher


class ScrapingRetryService:
    """Service to retry scraping for articles with insufficient content"""

    MAX_RETRIES = 5
    RETRY_INTERVALS = [5, 15, 60, 180, 360]  # minutes: 5min, 15min, 1h, 3h, 6h
    MIN_CONTENT_LENGTH = 200  # Minimum acceptable content length

    async def process_pending_batch(
        self,
        db: Session,
        batch_size: int = 10
    ) -> Dict[str, Any]:
        """
        Process a batch of articles that need scraping retry

        Args:
            db: Database session
            batch_size: Number of articles to process

        Returns:
            Dict with statistics
        """
        # Find articles that need retry:
        # 1. original_content is too short (< 200 chars)
        # 2. scraping_retry_count < MAX_RETRIES (or NULL)
        # 3. scraping_next_retry_at <= now (or NULL for first retry)
        # 4. Not from HackerNews (those don't have article content)

        now = datetime.now(timezone.utc)

        # Query for articles needing retry
        query = db.query(News).filter(
            func.length(News.original_content) < self.MIN_CONTENT_LENGTH,
            ~News.source_url.like('%news.ycombinator.com%'),  # Skip HN
            ~News.source_url.like('%reddit.com%')  # Skip Reddit
        )

        # Filter by retry count
        query = query.filter(
            (News.scraping_retry_count == None) |
            (News.scraping_retry_count < self.MAX_RETRIES)
        )

        # Filter by next retry time
        query = query.filter(
            (News.scraping_next_retry_at == None) |
            (News.scraping_next_retry_at <= now)
        )

        # Order by published_at (newest first) and limit
        articles = query.order_by(News.published_at.desc()).limit(batch_size).all()

        if not articles:
            return {
                "processed": 0,
                "success": 0,
                "failed": 0,
                "skipped": 0
            }

        print(f"\n{'='*80}")
        print(f"SCRAPING RETRY BATCH - Processing {len(articles)} articles")
        print(f"{'='*80}\n")

        success_count = 0
        failed_count = 0

        for article in articles:
            retry_count = article.scraping_retry_count or 0
            print(f"[Retry #{retry_count + 1}] {article.title[:60]}...")
            print(f"  URL: {article.source_url}")
            print(f"  Current content length: {len(article.original_content or '')}")

            try:
                # Attempt to scrape
                scraped_content = await news_fetcher.scrape_article_content(article.source_url)

                if scraped_content and len(scraped_content) >= self.MIN_CONTENT_LENGTH:
                    # Success!
                    article.original_content = scraped_content
                    article.scraping_retry_count = None  # Reset
                    article.scraping_next_retry_at = None
                    article.scraping_last_error = None

                    # Trigger GLM content generation
                    article.content_status = "pending"

                    success_count += 1
                    print(f"  ✓ Success! Scraped {len(scraped_content)} chars")

                else:
                    # Still failed - schedule next retry
                    article.scraping_retry_count = retry_count + 1
                    article.scraping_last_error = f"Content too short: {len(scraped_content or '')} chars"

                    if article.scraping_retry_count >= self.MAX_RETRIES:
                        # Max retries reached - mark as permanently failed
                        article.scraping_next_retry_at = None
                        print(f"  ✗ Max retries reached - giving up")
                    else:
                        # Schedule next retry
                        interval_minutes = self.RETRY_INTERVALS[min(retry_count, len(self.RETRY_INTERVALS) - 1)]
                        article.scraping_next_retry_at = now + timedelta(minutes=interval_minutes)
                        print(f"  ⟳ Retry scheduled in {interval_minutes} minutes")

                    failed_count += 1

            except Exception as e:
                # Error during scraping
                article.scraping_retry_count = retry_count + 1
                article.scraping_last_error = str(e)[:500]

                if article.scraping_retry_count >= self.MAX_RETRIES:
                    article.scraping_next_retry_at = None
                    print(f"  ✗ Error (max retries): {str(e)[:100]}")
                else:
                    interval_minutes = self.RETRY_INTERVALS[min(retry_count, len(self.RETRY_INTERVALS) - 1)]
                    article.scraping_next_retry_at = now + timedelta(minutes=interval_minutes)
                    print(f"  ✗ Error: {str(e)[:100]}")
                    print(f"  ⟳ Retry scheduled in {interval_minutes} minutes")

                failed_count += 1

            # Small delay between requests
            await asyncio.sleep(0.5)

        # Commit all changes
        db.commit()

        print(f"\n{'='*80}")
        print(f"SCRAPING RETRY COMPLETED")
        print(f"Success: {success_count} | Failed: {failed_count}")
        print(f"{'='*80}\n")

        return {
            "processed": len(articles),
            "success": success_count,
            "failed": failed_count,
            "skipped": 0
        }

    def get_pending_count(self, db: Session) -> int:
        """Get count of articles pending scraping retry"""
        now = datetime.now(timezone.utc)

        count = db.query(News).filter(
            func.length(News.original_content) < self.MIN_CONTENT_LENGTH,
            ~News.source_url.like('%news.ycombinator.com%'),
            ~News.source_url.like('%reddit.com%'),
            (News.scraping_retry_count == None) | (News.scraping_retry_count < self.MAX_RETRIES),
            (News.scraping_next_retry_at == None) | (News.scraping_next_retry_at <= now)
        ).count()

        return count


scraping_retry_service = ScrapingRetryService()
