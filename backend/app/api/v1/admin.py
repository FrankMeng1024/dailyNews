"""
Admin API - 管理员接口（需要创作者代码验证）
"""

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Any, Dict
from pydantic import BaseModel
import logging
import asyncio
import json
import uuid

from app.database import get_db, SessionLocal
from app.services.content_retry_service import content_retry_service
from app.services.config_service import ConfigService, DEFAULT_CONFIG
from app.services.error_tracking_service import error_tracker
from app.services.quality_scorer import quality_scorer
from app.services.verification_service import get_verification_service
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# 创作者代码（从环境变量读取，默认值）
CREATOR_CODE = getattr(settings, 'CREATOR_CODE', 'creator2026')

# 全局事件队列 - 用于 SSE 实时推送
fetch_events: Dict[str, asyncio.Queue] = {}

# 全局任务状态 - 用于跟踪当前抓取任务
current_fetch_task: Dict[str, Any] = {
    "task_id": None,
    "is_running": False,
    "current_stage": None,  # fetching / verifying / translating / refining
    "started_at": None,
    "last_error": None,
    "source_status": {},  # 各信息源状态
    "stats": {}  # 统计数据
}


def verify_creator_code(x_creator_code: str = Header(...)):
    """验证创作者代码"""
    if x_creator_code != CREATOR_CODE:
        raise HTTPException(status_code=403, detail="Invalid creator code")
    return True


class RetryRequest(BaseModel):
    """手动重试请求"""
    news_ids: List[int]


@router.post("/verify-code")
async def verify_code(code: str):
    """验证创作者代码"""
    if code == CREATOR_CODE:
        return {"valid": True, "message": "Creator code verified"}
    return {"valid": False, "message": "Invalid creator code"}


# ========== SSE 实时 Fetch 功能 ==========

@router.get("/fetch-status")
async def get_fetch_status(_: bool = Depends(verify_creator_code)):
    """获取当前抓取任务状态"""
    return {
        "is_running": current_fetch_task["is_running"],
        "task_id": current_fetch_task["task_id"],
        "current_stage": current_fetch_task["current_stage"],
        "started_at": current_fetch_task["started_at"],
        "last_error": current_fetch_task["last_error"],
        "source_status": current_fetch_task.get("source_status", {}),
        "stats": current_fetch_task.get("stats", {})
    }


@router.get("/current-state")
async def get_current_state(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """
    获取当前系统状态，用于页面刷新后恢复

    返回:
    - is_fetching: 是否正在抓取
    - task_id: 当前任务ID
    - current_stage: 当前阶段
    - source_status: 各信息源状态
    - processing_news: 正在处理的新闻列表
    - stats: 统计数据
    """
    from app.models.news import News

    # 获取正在处理的新闻（非 ready 状态）
    processing_news = db.query(News).filter(
        News.processing_status.in_(['fetching', 'verifying', 'translating', 'refining', 'failed'])
    ).order_by(News.created_at.desc()).limit(100).all()

    # 格式化新闻列表
    news_list = []
    for news in processing_news:
        news_list.append({
            "id": news.id,
            "title": news.title[:60] if news.title else "",
            "title_zh": news.title_zh[:60] if news.title_zh else None,
            "source": news.source_name[:20] if news.source_name else "",
            "processing_status": news.processing_status,
            "verification_status": news.verification_status,
            "is_verified": news.verification_status == "verified",
            "created_at": news.created_at.isoformat() if news.created_at else None
        })

    # 获取统计数据
    stats = {
        "fetching": db.query(func.count(News.id)).filter(News.processing_status == "fetching").scalar() or 0,
        "verifying": db.query(func.count(News.id)).filter(News.processing_status == "verifying").scalar() or 0,
        "translating": db.query(func.count(News.id)).filter(News.processing_status == "translating").scalar() or 0,
        "refining": db.query(func.count(News.id)).filter(News.processing_status == "refining").scalar() or 0,
        "failed": db.query(func.count(News.id)).filter(News.processing_status == "failed").scalar() or 0,
        "ready": db.query(func.count(News.id)).filter(News.processing_status == "ready").scalar() or 0
    }

    return {
        "is_fetching": current_fetch_task["is_running"],
        "task_id": current_fetch_task["task_id"],
        "current_stage": current_fetch_task["current_stage"],
        "source_status": current_fetch_task.get("source_status", {}),
        "processing_news": news_list,
        "stats": stats
    }


@router.get("/processing-stats")
async def get_processing_stats(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取各处理状态的数量统计"""
    from app.models.news import News
    from datetime import datetime, timezone, timedelta

    # 今天的开始时间
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    stats = {
        "fetching": db.query(func.count(News.id)).filter(News.processing_status == "fetching").scalar() or 0,
        "verifying": db.query(func.count(News.id)).filter(News.processing_status == "verifying").scalar() or 0,
        "translating": db.query(func.count(News.id)).filter(News.processing_status == "translating").scalar() or 0,
        "refining": db.query(func.count(News.id)).filter(News.processing_status == "refining").scalar() or 0,
        "failed": db.query(func.count(News.id)).filter(News.processing_status == "failed").scalar() or 0,
        "ready": db.query(func.count(News.id)).filter(News.processing_status == "ready").scalar() or 0,
        "ready_today": db.query(func.count(News.id)).filter(
            News.processing_status == "ready",
            News.created_at >= today_start
        ).scalar() or 0,
        "verified_count": db.query(func.count(News.id)).filter(
            News.verification_status == "verified"
        ).scalar() or 0
    }

    # 计算总数和处理中数量
    stats["total"] = sum([stats["fetching"], stats["verifying"], stats["translating"],
                         stats["refining"], stats["failed"], stats["ready"]])
    stats["processing"] = sum([stats["fetching"], stats["verifying"], stats["translating"], stats["refining"]])

    return stats


@router.get("/fetch-stream/{task_id}")
async def fetch_stream(task_id: str):
    """SSE 流式返回 fetch 进度"""
    async def event_generator():
        queue = fetch_events.get(task_id)
        if not queue:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Task not found'})}\n\n"
            return

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get('type') == 'complete' or event.get('type') == 'error':
                    break
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


@router.post("/fetch-news")
async def admin_fetch_news(
    force: bool = Query(False, description="强制抓取，忽略时间限制"),
    _: bool = Depends(verify_creator_code)
):
    """开发者模式 fetch，返回 task_id 用于 SSE 订阅"""
    # 检查是否有正在运行的任务
    if current_fetch_task["is_running"]:
        raise HTTPException(
            status_code=409,
            detail="已有任务正在运行，请等待完成"
        )

    task_id = str(uuid.uuid4())
    fetch_events[task_id] = asyncio.Queue()

    # 启动后台任务
    asyncio.create_task(do_fetch_with_events(task_id, force))

    return {"task_id": task_id, "message": "Fetch started"}


async def do_fetch_with_events(task_id: str, force: bool):
    """带事件推送的 fetch 任务"""
    global current_fetch_task
    from app.services.news_fetcher import news_fetcher
    from app.models.news import News
    from app.models.system_config import FetchHistory
    from datetime import datetime, timezone
    import hashlib

    queue = fetch_events.get(task_id)
    if not queue:
        return

    # 设置全局任务状态
    current_fetch_task = {
        "task_id": task_id,
        "is_running": True,
        "current_stage": "fetching",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "last_error": None,
        "source_status": {},
        "stats": {}
    }

    async def emit(event_type: str, **data):
        await queue.put({"type": event_type, **data})

    db = SessionLocal()
    fetch_history = None

    try:
        await emit("start", message="开始抓取新闻...")

        # 读取 dev_config.py 配置（与 news_fetcher.py 保持一致）
        try:
            import sys
            import os
            # admin.py 在 backend/app/api/v1/admin.py，dev_config.py 在 News/dev_config.py
            # 需要 5 层 dirname: v1 -> api -> app -> backend -> News
            news_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
            if news_root not in sys.path:
                sys.path.insert(0, news_root)
            from dev_config import FETCH_LIMIT
        except ImportError:
            FETCH_LIMIT = -1

        if FETCH_LIMIT > 0:
            per_source = max(1, FETCH_LIMIT // 4)
        else:
            per_source = 15  # 默认值

        logger.info(f"[DEV] Fetch limit from dev_config: {FETCH_LIMIT}, per_source: {per_source}")

        # 记录 fetch 历史
        fetch_history = FetchHistory(
            fetch_type="manual_dev",
            source_name="all",
            status="running",
            started_at=datetime.now(timezone.utc)
        )
        db.add(fetch_history)
        db.commit()

        all_articles = []

        # 1. 抓取 Hacker News
        await emit("source_start", source="hackernews", message="正在获取 Hacker News...")
        try:
            hn_articles = await news_fetcher.fetch_hackernews_ai(limit=per_source)
            await emit("source_complete", source="hackernews", count=len(hn_articles),
                       articles=[{"title": a.get("title", "")[:60], "source": "HN"} for a in hn_articles[:5]])
            all_articles.extend(hn_articles)
        except Exception as e:
            logger.error(f"HN fetch error: {e}")
            await emit("source_error", source="hackernews", error=str(e)[:100])

        # 2. 抓取 Reddit
        await emit("source_start", source="reddit", message="正在获取 Reddit AI...")
        try:
            reddit_articles = await news_fetcher.fetch_reddit_ai(limit=per_source)
            await emit("source_complete", source="reddit", count=len(reddit_articles),
                       articles=[{"title": a.get("title", "")[:60], "source": "Reddit"} for a in reddit_articles[:5]])
            all_articles.extend(reddit_articles)
        except Exception as e:
            logger.error(f"Reddit fetch error: {e}")
            await emit("source_error", source="reddit", error=str(e)[:100])

        # 3. 抓取 RSS
        await emit("source_start", source="rss", message="正在获取 RSS 订阅...")
        try:
            rss_articles = await news_fetcher.fetch_rss_feeds(limit_per_source=per_source)
            await emit("source_complete", source="rss", count=len(rss_articles),
                       articles=[{"title": a.get("title", "")[:60], "source": "RSS"} for a in rss_articles[:5]])
            all_articles.extend(rss_articles)
        except Exception as e:
            logger.error(f"RSS fetch error: {e}")
            await emit("source_error", source="rss", error=str(e)[:100])

        # 4. 抓取 NewsAPI
        await emit("source_start", source="newsapi", message="正在获取 NewsAPI...")
        try:
            # 检查 API 密钥是否配置
            if not news_fetcher.api_key or news_fetcher.api_key == "your_newsapi_key_here":
                await emit("source_error", source="newsapi", error="API密钥未配置")
            else:
                newsapi_articles = await news_fetcher.fetch_newsapi_ai(page_size=per_source)
                await emit("source_complete", source="newsapi", count=len(newsapi_articles),
                           articles=[{"title": a.get("title", "")[:60], "source": "NewsAPI"} for a in newsapi_articles[:5]])
                all_articles.extend(newsapi_articles)
        except Exception as e:
            logger.error(f"NewsAPI fetch error: {e}")
            await emit("source_error", source="newsapi", error=str(e)[:100])

        # 处理和保存
        await emit("processing", message=f"处理 {len(all_articles)} 篇文章...")

        new_count = 0
        duplicate_count = 0
        filtered_count = 0

        for article in all_articles:
            try:
                # 生成 external_id
                url = article.get("url") or article.get("link") or ""
                title = article.get("title") or ""
                external_id = hashlib.md5(f"{url}{title}".encode()).hexdigest()

                # 检查是否已存在
                existing = db.query(News).filter(News.external_id == external_id).first()
                if existing:
                    duplicate_count += 1
                    continue

                # 判断内容是否足够（>=200字符算抓取成功）
                content = article.get("content", "") or ""
                content_length = len(content)
                scrape_success = content_length >= 200

                # 创建新闻记录
                news = News(
                    external_id=external_id,
                    title=title[:500],
                    source_name=article.get("source_name", "Unknown")[:100],
                    source_url=url[:1000],
                    author=article.get("author", "")[:200] if article.get("author") else None,
                    original_content=content[:50000] if content else None,
                    summary=article.get("description", "")[:2000] if article.get("description") else None,
                    image_url=article.get("image_url", "")[:1000] if article.get("image_url") else None,
                    published_at=article.get("published_at") or datetime.now(timezone.utc),
                    source_type=article.get("source_type", "news"),
                    # 抓取失败的文章，content_status 设为 scrape_failed，等待重试抓取
                    content_status="pending" if scrape_success else "scrape_failed",
                    title_status="pending",
                    # 设置初始 processing_status
                    processing_status="fetching",
                    verification_status="pending"
                )

                # Calculate quality score
                quality_scorer.calculate_comprehensive_score(news)

                db.add(news)
                db.flush()  # 立即获取 news.id，否则 emit 时 id 为 None
                new_count += 1

                # 每保存一条发送事件（包含 processing_status）
                await emit("article_saved",
                    news_id=news.id,
                    title=title[:50],
                    source=article.get("source", article.get("source_name", "Unknown"))[:20],
                    processing_status="fetching",
                    is_verified=False,
                    scrape_status="success" if scrape_success else "failed"
                )

            except Exception as e:
                logger.error(f"Save article error: {e}")
                filtered_count += 1

        db.commit()

        # ========== 获取所有新保存的文章ID ==========
        all_new_ids = []
        for article in all_articles:
            url = article.get("url") or article.get("link") or ""
            title = article.get("title") or ""
            external_id = hashlib.md5(f"{url}{title}".encode()).hexdigest()
            news = db.query(News).filter(News.external_id == external_id).first()
            if news:
                all_new_ids.append(news.id)

        # ========== 新增：处理初始内容足够的文章 ==========
        # 这些文章不需要抓取全文，直接进入验证阶段
        articles_with_content = db.query(News).filter(
            News.id.in_(all_new_ids),
            News.processing_status == "fetching",
            func.length(News.original_content) >= 200
        ).all()

        for news in articles_with_content:
            news.processing_status = "verifying"
            await emit("status_change",
                news_id=news.id,
                old_status="fetching",
                new_status="verifying"
            )

        if articles_with_content:
            db.commit()
            logger.info(f"Moved {len(articles_with_content)} articles with sufficient content to verifying")
        # ========== 处理结束 ==========

        # ========== 批量抓取全文 ==========
        # 筛选需要抓取全文的文章（original_content < 200字符）
        articles_to_scrape = db.query(News).filter(
            News.id.in_(all_new_ids),
            News.processing_status == "fetching",  # 只处理还在 fetching 状态的
            (News.original_content == None) | (func.length(News.original_content) < 200)
        ).all()

        if articles_to_scrape:
            await emit("batch_start", batch_type="scraping", count=len(articles_to_scrape),
                       message=f"正在抓取 {len(articles_to_scrape)} 篇全文...")
            scrape_success = 0
            for news in articles_to_scrape:
                try:
                    scraped = await news_fetcher.scrape_article_content(news.source_url)
                    if scraped and len(scraped) >= 200:
                        news.original_content = scraped
                        news.content_status = "pending"
                        news.processing_status = "verifying"  # 抓取成功，进入验证阶段
                        scrape_success += 1
                    else:
                        # 抓取失败，尝试使用 summary 作为备用内容
                        # 对于 JS 渲染的网站（OpenAI、DeepMind 等），summary 通常来自 RSS/API
                        fallback_content = news.summary or ""
                        if len(fallback_content) >= 100:
                            # summary 足够长，使用它作为 original_content
                            news.original_content = fallback_content
                            news.content_status = "pending"
                            news.processing_status = "verifying"
                            scrape_success += 1
                            logger.info(f"Using summary as fallback for {news.source_url[:50]}")
                        else:
                            error_msg = f"Content too short: {len(scraped or '')} chars, summary: {len(fallback_content)} chars"
                            news.content_status = "scrape_failed"
                            news.processing_status = "failed"
                            news.scraping_last_error = error_msg
                            # 发送失败状态变更事件
                            await emit("status_change",
                                news_id=news.id,
                                old_status="fetching",
                                new_status="failed",
                                error=error_msg
                            )
                except Exception as e:
                    # 异常时也尝试 summary 备用
                    fallback_content = news.summary or ""
                    if len(fallback_content) >= 100:
                        news.original_content = fallback_content
                        news.content_status = "pending"
                        news.processing_status = "verifying"
                        scrape_success += 1
                        logger.info(f"Using summary as fallback after error for {news.source_url[:50]}")
                    else:
                        error_msg = str(e)[:500]
                        news.content_status = "scrape_failed"
                        news.processing_status = "failed"
                        news.scraping_last_error = error_msg
                        logger.error(f"Scrape error for {news.source_url}: {e}")
                        # 发送失败状态变更事件
                        await emit("status_change",
                            news_id=news.id,
                            old_status="fetching",
                            new_status="failed",
                            error=error_msg
                        )
            db.commit()
            await emit("batch_complete", batch_type="scraping", success=scrape_success)
        # ========== 抓取全文结束 ==========

        # ========== 新增：验证阶段 ==========
        # 获取需要验证的文章（processing_status == "verifying"）
        articles_to_verify = db.query(News).filter(
            News.id.in_(all_new_ids),
            News.processing_status == "verifying"
        ).all()

        translated_count = 0  # 用于记录「新增」数量

        if articles_to_verify:
            current_fetch_task["current_stage"] = "verifying"
            await emit("batch_start", batch_type="verification", count=len(articles_to_verify),
                       message=f"正在验证 {len(articles_to_verify)} 篇新闻...")

            verification_service = get_verification_service()
            verify_success = 0

            for news in articles_to_verify:
                try:
                    result = await verification_service.verify_news(news)
                    news.verification_status = "verified" if result.is_verified else "failed"
                    news.verification_score = result.confidence_score
                    news.verification_sources = result.details
                    news.verification_error = result.error
                    # 验证完成后进入翻译阶段（不管验证成功失败）
                    news.processing_status = "translating"
                    if result.is_verified:
                        verify_success += 1
                    # 发送状态变更事件
                    await emit("status_change",
                        news_id=news.id,
                        old_status="verifying",
                        new_status="translating",
                        is_verified=result.is_verified,
                        confidence=result.confidence_score
                    )
                except Exception as e:
                    logger.error(f"Verification error for news {news.id}: {e}")
                    news.verification_status = "failed"
                    news.verification_error = str(e)[:500]
                    news.processing_status = "translating"  # 验证失败也继续

            db.commit()
            await emit("batch_complete", batch_type="verification", success=verify_success)
        # ========== 验证阶段结束 ==========

        # 获取需要翻译的文章（processing_status == "translating"）
        new_news_ids = [n.id for n in db.query(News).filter(
            News.id.in_(all_new_ids),
            News.processing_status == "translating"
        ).all()]

        # 并行执行翻译和内容生成（它们互不依赖）
        if new_news_ids:
            # 更新阶段状态为翻译
            current_fetch_task["current_stage"] = "translating"

            await emit("batch_start", batch_type="title_translation", count=len(new_news_ids), message=f"正在翻译 {len(new_news_ids)} 条标题...")

            # 先执行翻译
            async def translate_task():
                try:
                    return await news_fetcher._translate_titles_for_news(db, new_news_ids)
                except Exception as e:
                    logger.error(f"Title translation error: {e}")
                    return None, str(e)[:100]

            title_result = await translate_task()

            # 发送翻译完成通知
            if isinstance(title_result, tuple):
                await emit("batch_complete", batch_type="title_translation", success=0, error=title_result[1])
            else:
                await emit("batch_complete", batch_type="title_translation", success=title_result or 0)

            # 翻译完成后，更新 processing_status
            # 翻译成功的进入 refining
            translated_news = db.query(News).filter(
                News.id.in_(new_news_ids),
                News.title_status == "ready"
            ).all()

            translated_count = len(translated_news)
            for news in translated_news:
                news.processing_status = "refining"
                await emit("status_change",
                    news_id=news.id,
                    old_status="translating",
                    new_status="refining"
                )

            # 翻译失败的设为 failed（包括 pending 状态，因为 pending 表示等待重试）
            failed_translation = db.query(News).filter(
                News.id.in_(new_news_ids),
                News.title_status.in_(["failed", "pending"])  # 添加 pending
            ).all()

            for news in failed_translation:
                news.processing_status = "failed"
                error_msg = news.title_last_error or "Title translation failed or pending retry"
                await emit("status_change",
                    news_id=news.id,
                    old_status="translating",
                    new_status="failed",
                    error=error_msg
                )

            db.commit()

            # 更新阶段状态为精炼
            current_fetch_task["current_stage"] = "refining"

            # 获取需要精炼的文章ID
            refining_news_ids = [n.id for n in translated_news]

            if refining_news_ids:
                await emit("batch_start", batch_type="content_generation", count=len(refining_news_ids), message=f"正在精炼 {len(refining_news_ids)} 条内容...")

                async def content_task():
                    try:
                        return await news_fetcher.generate_content_for_news(db, refining_news_ids, language="zh")
                    except Exception as e:
                        logger.error(f"Content generation error: {e}")
                        return None, str(e)[:100]

                content_result = await content_task()

                if isinstance(content_result, tuple):
                    await emit("batch_complete", batch_type="content_generation", success=0, error=content_result[1])
                else:
                    await emit("batch_complete", batch_type="content_generation", success=content_result or 0)

                # 精炼完成后，更新 processing_status
                # 成功的设为 ready
                refined_news = db.query(News).filter(
                    News.id.in_(refining_news_ids),
                    News.content_status == "ready"
                ).all()

                for news in refined_news:
                    news.processing_status = "ready"
                    await emit("status_change",
                        news_id=news.id,
                        old_status="refining",
                        new_status="ready"
                    )

                # 失败的设为 failed（包括 pending 状态，因为 pending 表示等待重试）
                failed_news = db.query(News).filter(
                    News.id.in_(refining_news_ids),
                    News.content_status.in_(["failed", "pending"])  # 添加 pending
                ).all()

                for news in failed_news:
                    news.processing_status = "failed"
                    error_msg = news.glm_last_error or "Content generation failed or pending retry"
                    await emit("status_change",
                        news_id=news.id,
                        old_status="refining",
                        new_status="failed",
                        error=error_msg
                    )

                db.commit()

        # 检查是否所有文章都处于终态（ready/failed）
        # 只有全部完成才发送 complete 事件
        if all_new_ids:
            still_processing = db.query(News).filter(
                News.id.in_(all_new_ids),
                News.processing_status.in_(['fetching', 'verifying', 'translating', 'refining'])
            ).count()

            if still_processing > 0:
                logger.warning(f"Still processing {still_processing} articles, waiting...")
                # 等待处理完成（最多等待 5 分钟）
                for _ in range(60):  # 60 * 5秒 = 5分钟
                    await asyncio.sleep(5)
                    still_processing = db.query(News).filter(
                        News.id.in_(all_new_ids),
                        News.processing_status.in_(['fetching', 'verifying', 'translating', 'refining'])
                    ).count()
                    if still_processing == 0:
                        break
                    await emit("heartbeat", still_processing=still_processing)

        # 重新统计最终结果
        final_ready = db.query(News).filter(
            News.id.in_(all_new_ids),
            News.processing_status == "ready"
        ).count() if all_new_ids else 0

        final_failed = db.query(News).filter(
            News.id.in_(all_new_ids),
            News.processing_status == "failed"
        ).count() if all_new_ids else 0

        # 更新 fetch 历史
        if fetch_history:
            fetch_history.status = "completed"
            fetch_history.completed_at = datetime.now(timezone.utc)
            fetch_history.articles_found = len(all_articles)
            # 新增 = 成功处理的数量
            fetch_history.articles_new = final_ready
            fetch_history.articles_filtered = filtered_count + final_failed
            db.commit()

        await emit("complete", success=True,
                   translated_count=final_ready,
                   new_count=final_ready,
                   failed_count=final_failed,
                   duplicate_count=duplicate_count,
                   filtered_count=filtered_count,
                   total=len(all_articles))

        # 完成，更新全局状态
        current_fetch_task["is_running"] = False
        current_fetch_task["current_stage"] = None

        logger.info(f"Dev fetch completed: {new_count} new, {duplicate_count} duplicates, {filtered_count} filtered")

    except Exception as e:
        logger.error(f"Fetch error: {e}", exc_info=True)
        await emit("error", message=str(e)[:200])

        # 错误，更新全局状态
        current_fetch_task["is_running"] = False
        current_fetch_task["current_stage"] = None
        current_fetch_task["last_error"] = str(e)[:200]

        if fetch_history:
            fetch_history.status = "failed"
            fetch_history.error_message = str(e)[:500]
            fetch_history.completed_at = datetime.now(timezone.utc)
            db.commit()

    finally:
        db.close()
        # 延迟清理队列，让客户端有时间接收最后的消息
        await asyncio.sleep(2)
        if task_id in fetch_events:
            del fetch_events[task_id]


@router.get("/content-status")
async def get_content_status(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取内容状态统计"""
    stats = content_retry_service.get_content_status_stats(db)
    return stats


@router.get("/retry-list")
async def get_retry_list(
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取重试列表"""
    retry_list = content_retry_service.get_retry_list(db, status, limit)
    return {"items": retry_list, "total": len(retry_list)}


@router.post("/manual-retry")
async def manual_retry(
    request: RetryRequest,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """手动重试指定新闻"""
    result = await content_retry_service.manual_retry(db, request.news_ids)
    return result


@router.post("/reset-all-failed")
async def reset_all_failed(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """重置所有failed状态的新闻"""
    count = await content_retry_service.reset_all_failed(db)
    return {"reset_count": count, "message": f"Reset {count} failed news items"}


@router.post("/retry-all-pending")
async def retry_all_pending(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """一键重试所有pending新闻"""
    result = await content_retry_service.process_pending_batch(db, batch_size=50, trigger_type="manual")
    return {
        "processed": result["processed"],
        "success": result["success"],
        "failed": result["failed"],
        "message": f"处理了 {result['processed']} 条，成功 {result['success']} 条"
    }


@router.get("/retry-history")
async def get_retry_history(
    limit: int = 20,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取重试历史"""
    from app.models.retry_history import RetryHistory
    history = db.query(RetryHistory).order_by(RetryHistory.created_at.desc()).limit(limit).all()
    return {"items": [
        {
            "id": h.id,
            "trigger_type": h.trigger_type,
            "processed": h.processed_count,
            "success": h.success_count,
            "failed": h.failed_count,
            "error": h.error_message,
            "created_at": h.created_at.isoformat() if h.created_at else None
        }
        for h in history
    ]}


@router.get("/failed-news")
async def get_failed_news(
    failure_type: Optional[str] = None,  # "scraping_failed", "glm_failed", or None for all
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """
    获取所有失败的新闻，区分抓取失败和精炼失败

    失败定义：
    - scraping_failed: original_content < 200字符
    - glm_failed: original_content >= 200字符 但 content_status != 'ready'
    """
    from app.models.news import News
    from sqlalchemy import or_, func, and_

    # Base query - all news that are not fully recovered
    query = db.query(News).filter(
        or_(
            # Scraping failed: content too short
            func.length(News.original_content) < 200,
            # GLM failed: has content but not ready
            and_(
                func.length(News.original_content) >= 200,
                News.content_status != 'ready'
            )
        )
    )

    # Filter by failure type if specified
    if failure_type == "scraping_failed":
        query = db.query(News).filter(
            func.length(News.original_content) < 200
        )
    elif failure_type == "glm_failed":
        query = db.query(News).filter(
            func.length(News.original_content) >= 200,
            News.content_status != 'ready'
        )

    # Get total count
    total = query.count()

    # Get paginated results
    news_list = query.order_by(News.published_at.desc()).offset(offset).limit(limit).all()

    # Format response
    items = []
    for news in news_list:
        items.append({
            "id": news.id,
            "title": news.title,
            "title_zh": news.title_zh,
            "source_name": news.source_name,
            "source_url": news.source_url,
            "published_at": news.published_at.isoformat() if news.published_at else None,
            "failure_type": news.get_failure_type(),
            "failure_details": news.get_retry_info(),
            "content_status": news.content_status,
            "original_content_length": len(news.original_content) if news.original_content else 0,
            "created_at": news.created_at.isoformat() if news.created_at else None
        })

    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "summary": {
            "scraping_failed": db.query(News).filter(func.length(News.original_content) < 200).count(),
            "glm_failed": db.query(News).filter(
                func.length(News.original_content) >= 200,
                News.content_status != 'ready'
            ).count()
        }
    }


@router.post("/retry-single")
async def retry_single_article(
    news_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """
    重试单篇文章

    根据失败类型自动选择重试scraping或GLM
    """
    from app.models.news import News
    from app.services.news_fetcher import news_fetcher
    from app.services.scraping_retry_service import scraping_retry_service

    news = db.query(News).filter(News.id == news_id).first()
    if not news:
        raise HTTPException(status_code=404, detail="News not found")

    failure_type = news.get_failure_type()

    if failure_type == "scraping_failed":
        # Retry scraping
        try:
            scraped_content = await news_fetcher.scrape_article_content(news.source_url)

            if scraped_content and len(scraped_content) >= 200:
                news.original_content = scraped_content
                news.scraping_retry_count = 0
                news.scraping_next_retry_at = None
                news.scraping_last_error = None
                news.content_status = "pending"  # Trigger GLM generation
                db.commit()

                return {
                    "success": True,
                    "message": "Scraping succeeded, GLM generation queued",
                    "content_length": len(scraped_content)
                }
            else:
                news.scraping_retry_count = (news.scraping_retry_count or 0) + 1
                news.scraping_last_error = f"Content too short: {len(scraped_content or '')} chars"
                db.commit()

                return {
                    "success": False,
                    "message": "Scraping failed - content too short",
                    "content_length": len(scraped_content or '')
                }
        except Exception as e:
            news.scraping_retry_count = (news.scraping_retry_count or 0) + 1
            news.scraping_last_error = str(e)[:500]
            db.commit()

            return {
                "success": False,
                "message": f"Scraping error: {str(e)[:100]}"
            }

    elif failure_type == "glm_failed":
        # Retry GLM generation
        result = await content_retry_service.manual_retry(db, [news_id])
        return result

    else:
        return {
            "success": False,
            "message": "No failure detected - article is already recovered"
        }


@router.post("/retry-all-scraping-failed")
async def retry_all_scraping_failed(
    batch_size: int = 20,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """
    批量重试所有抓取失败的文章

    只处理 original_content < 200 字符的文章
    """
    from app.services.scraping_retry_service import scraping_retry_service

    result = await scraping_retry_service.process_pending_batch(db, batch_size=batch_size)

    return {
        "processed": result["processed"],
        "success": result["success"],
        "failed": result["failed"],
        "message": f"处理了 {result['processed']} 条，成功 {result['success']} 条"
    }


@router.get("/fetch-history")
async def get_fetch_history(
    limit: int = 20,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取fetch历史记录"""
    from app.models.system_config import FetchHistory

    history_list = db.query(FetchHistory).order_by(
        FetchHistory.started_at.desc()
    ).limit(limit).all()

    items = []
    for h in history_list:
        duration = None
        if h.completed_at and h.started_at:
            duration = (h.completed_at - h.started_at).total_seconds()

        items.append({
            "id": h.id,
            "fetch_type": h.fetch_type,
            "source_name": h.source_name,
            "status": h.status,
            "articles_found": h.articles_found,
            "articles_new": h.articles_new,
            "articles_filtered": h.articles_filtered,
            "error_message": h.error_message,
            "started_at": h.started_at.isoformat() if h.started_at else None,
            "completed_at": h.completed_at.isoformat() if h.completed_at else None,
            "duration_seconds": round(duration, 1) if duration else None
        })

    return {"items": items, "total": len(items)}


@router.get("/next-retry-time")
async def get_next_retry_time(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取下次自动重试时间"""
    from app.models.news import News
    from datetime import datetime, timezone

    # 查询最近的一个需要重试的新闻
    next_news = db.query(News).filter(
        News.content_status == "pending",
        News.glm_next_retry_at != None
    ).order_by(News.glm_next_retry_at.asc()).first()

    if not next_news or not next_news.glm_next_retry_at:
        return {"next_retry_at": None, "seconds_until_retry": None}

    now = datetime.now(timezone.utc)
    seconds_until = max(0, (next_news.glm_next_retry_at - now).total_seconds())

    return {
        "next_retry_at": next_news.glm_next_retry_at.isoformat(),
        "seconds_until_retry": int(seconds_until)
    }


# ========== Title Translation Admin APIs ==========

@router.get("/title-status")
async def get_title_status(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取标题翻译状态统计"""
    stats = content_retry_service.get_title_status_stats(db)
    return stats


@router.get("/title-retry-list")
async def get_title_retry_list(
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取标题翻译重试列表"""
    retry_list = content_retry_service.get_title_retry_list(db, status, limit)
    return {"items": retry_list, "total": len(retry_list)}


@router.post("/manual-retry-titles")
async def manual_retry_titles(
    request: RetryRequest,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """手动重试指定新闻的标题翻译"""
    result = await content_retry_service.manual_retry_titles(db, request.news_ids)
    return result


@router.post("/reset-all-failed-titles")
async def reset_all_failed_titles(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """重置所有标题翻译failed状态的新闻"""
    count = await content_retry_service.reset_all_failed_titles(db)
    return {"reset_count": count, "message": f"Reset {count} failed title translations"}


@router.post("/retry-all-pending-titles")
async def retry_all_pending_titles(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """一键重试所有pending标题翻译"""
    result = await content_retry_service.process_pending_titles(db, batch_size=50)
    return {
        "processed": result["processed"],
        "success": result["success"],
        "failed": result["failed"],
        "message": f"处理了 {result['processed']} 条，成功 {result['success']} 条"
    }


# ========== Configuration Management APIs ==========

@router.get("/config")
async def get_config(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取所有配置"""
    config = ConfigService.get_all(db)
    return {
        "config": config,
        "defaults": DEFAULT_CONFIG
    }


@router.put("/config/{key}")
async def update_config(
    key: str,
    value: Any,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """更新单个配置"""
    if key not in DEFAULT_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown config key: {key}")

    ConfigService.set(db, key, value)
    logger.info(f"Config updated: {key} = {value}")
    return {"success": True, "key": key, "value": value}


# ========== Error Details APIs ==========

@router.get("/error-details/{news_id}")
async def get_error_details(
    news_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取单条新闻的详细错误信息"""
    from app.models.news import News

    news = db.query(News).filter(News.id == news_id).first()
    if not news:
        raise HTTPException(status_code=404, detail="News not found")

    return news.get_detailed_error_info()


@router.post("/retry-specific")
async def retry_specific(
    news_id: int = Query(..., description="News ID to retry"),
    retry_type: str = Query(..., description="Type: scraping, glm, or title"),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """针对性重试特定失败类型

    Args:
        news_id: 新闻ID
        retry_type: 重试类型 (scraping/glm/title)
    """
    from app.models.news import News
    from app.services.news_fetcher import news_fetcher
    from app.services.scraping_retry_service import scraping_retry_service

    news = db.query(News).filter(News.id == news_id).first()
    if not news:
        raise HTTPException(status_code=404, detail="News not found")

    # 检查是否可以重试
    can_retry = news._can_retry()
    if not can_retry.get(retry_type if retry_type != "title" else "title", False):
        return {
            "success": False,
            "message": f"Cannot retry {retry_type}: max retries reached or already succeeded"
        }

    result = {"success": False, "message": "Unknown retry type"}

    if retry_type == "scraping":
        # 重置重试计数
        news.reset_retry_counts("scraping")
        db.commit()

        # 触发爬虫重试
        try:
            scraped_content = await news_fetcher.scrape_article_content(news.source_url, db)
            if scraped_content and len(scraped_content) >= 200:
                news.original_content = scraped_content
                news.content_status = "pending"  # 触发 GLM 生成
                db.commit()
                result = {
                    "success": True,
                    "message": f"Scraping succeeded, {len(scraped_content)} chars",
                    "content_length": len(scraped_content)
                }
            else:
                news.scraping_retry_count = 1
                news.scraping_last_error = f"Content too short: {len(scraped_content or '')} chars"
                db.commit()
                result = {
                    "success": False,
                    "message": f"Scraping failed: content too short ({len(scraped_content or '')} chars)"
                }
        except Exception as e:
            error_tracker.record_scrape_error(db, news, e, news.source_url)
            result = {"success": False, "message": f"Scraping error: {str(e)[:100]}"}

    elif retry_type == "glm":
        # 重置重试计数
        news.reset_retry_counts("glm")
        db.commit()

        # 触发 GLM 重试
        try:
            generated = await news_fetcher.generate_content_for_news(db, [news_id], "zh")
            result = {
                "success": generated > 0,
                "message": f"GLM generation {'succeeded' if generated > 0 else 'failed'}"
            }
        except Exception as e:
            error_tracker.record_glm_error(db, news, e, "manual retry")
            result = {"success": False, "message": f"GLM error: {str(e)[:100]}"}

    elif retry_type == "title":
        # 重置重试计数
        news.reset_retry_counts("title")
        db.commit()

        # 触发标题翻译重试
        try:
            translated = await news_fetcher._translate_titles_for_news(db, [news_id])
            result = {
                "success": translated > 0,
                "message": f"Title translation {'succeeded' if translated > 0 else 'failed'}"
            }
        except Exception as e:
            error_tracker.record_title_error(db, news, e, "manual retry")
            result = {"success": False, "message": f"Title translation error: {str(e)[:100]}"}

    else:
        raise HTTPException(status_code=400, detail=f"Invalid retry_type: {retry_type}")

    logger.info(f"Retry specific [{retry_type}] for news {news_id}: {result}")
    return result


@router.get("/system-health")
async def get_system_health(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取系统健康状态"""
    from app.models.news import News
    from sqlalchemy import func

    # 获取错误统计
    error_summary = error_tracker.get_error_summary(db)

    # 获取总体统计
    total_news = db.query(func.count(News.id)).scalar() or 0
    ready_news = db.query(func.count(News.id)).filter(
        News.content_status == "ready",
        News.title_status == "ready"
    ).scalar() or 0

    # 获取配置
    config = ConfigService.get_all(db)

    return {
        "status": "healthy" if error_summary["total_issues"] < 100 else "degraded",
        "total_news": total_news,
        "ready_news": ready_news,
        "success_rate": round(ready_news / total_news * 100, 1) if total_news > 0 else 0,
        "errors": error_summary,
        "config": config
    }


@router.get("/error-summary")
async def get_error_summary(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取错误统计摘要"""
    return error_tracker.get_error_summary(db)

