#!/usr/bin/env python3
"""
Debug fetch to see quality scores
"""
import sys
sys.path.insert(0, 'backend')

import asyncio
from app.database import SessionLocal
from app.services.news_fetcher import NewsFetcher
from app.models.news import News
from app.services.quality_scorer import quality_scorer
from datetime import datetime, timezone

async def debug_fetch():
    db = SessionLocal()
    fetcher = NewsFetcher(db)

    print("🔍 Debug: Fetching 3 RSS articles...")
    articles = await fetcher.fetch_rss_feeds(limit_per_source=3)
    print(f"Found {len(articles)} articles\n")

    if not articles:
        print("No articles fetched!")
        return

    # Test first 3 articles
    for i, article in enumerate(articles[:3]):
        print(f"=== Article {i+1}/{min(3, len(articles))} ===")
        print(f"Title: {article.get('title', 'NO TITLE')[:60]}")
        print(f"Source: {article.get('source', 'NO SOURCE')}")

        # Check content
        description = article.get("description", "") or article.get("summary", "") or ""
        scraped_content = article.get("scraped_content")
        original_content = scraped_content if scraped_content else (description if len(description) > 50 else None)

        print(f"Has scraped_content: {bool(scraped_content)} ({len(scraped_content) if scraped_content else 0} chars)")
        print(f"Has description: {bool(description)} ({len(description)} chars)")
        print(f"Final original_content: {bool(original_content)} ({len(original_content) if original_content else 0} chars)")

        # Would it be filtered for lacking content?
        if not original_content and not description:
            print("❌ FILTERED: No original_content AND no description")
            continue

        # Create news object
        news = News(
            external_id=f'debug_{i}',
            title=article.get('title', 'Test'),
            source_name=article.get('source', 'Unknown'),
            published_at=datetime.now(timezone.utc),
            original_content=original_content,
            summary=description[:500] if description else None,
            is_verified=article.get('is_verified', False),
            ai_relevance_score=0.7 if article.get('is_verified') else 0.5
        )

        # Calculate quality score
        quality_scorer.calculate_comprehensive_score(news)

        print(f"\n📊 Quality Scores:")
        print(f"  Source Authority: {news.source_authority_score:.3f}")
        print(f"  Content Depth: {news.content_depth_score:.3f}")
        print(f"  Timeliness: {news.timeliness_score:.3f}")
        print(f"  AI Relevance: {news.ai_relevance_score:.3f}")
        print(f"  Technical Credibility: {news.technical_credibility_score:.3f}")
        print(f"  FINAL SCORE: {news.final_score:.3f}")
        print(f"  Threshold: 0.25")

        if news.final_score >= 0.25:
            print(f"  ✅ PASSES (would be saved)")
        else:
            print(f"  ❌ FAILS (would be filtered)")

        print()

    db.close()

if __name__ == "__main__":
    asyncio.run(debug_fetch())
