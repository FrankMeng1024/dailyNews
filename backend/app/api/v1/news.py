from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from datetime import datetime, timedelta
import uuid
import asyncio

from app.database import get_db, SessionLocal
from app.api.deps import get_current_user
from app.models.user import User
from app.models.news import News
from app.models.settings import UserSettings
from app.schemas.news import NewsResponse, NewsListResponse, NewsFetchResponse
from app.services.news_fetcher import news_fetcher
from app.services.glm_service import glm_service
from app.services.task_store import create_task, update_task, get_task

router = APIRouter(prefix="/news", tags=["News"])


@router.get("", response_model=NewsListResponse)
async def list_news(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    min_score: Optional[float] = Query(None, ge=0, le=1),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: Session = Depends(get_db)
):
    """
    List news articles with pagination and filtering
    """
    query = db.query(News)

    # Apply filters
    if min_score is not None:
        query = query.filter(News.final_score >= min_score)

    if date_from:
        query = query.filter(News.published_at >= date_from)

    if date_to:
        query = query.filter(News.published_at <= date_to)

    # Get total count
    total = query.count()

    # Order by published_at (newest first)
    query = query.order_by(desc(News.published_at))

    # Paginate
    offset = (page - 1) * limit
    news_list = query.offset(offset).limit(limit).all()

    return NewsListResponse(
        items=[NewsResponse.model_validate(n) for n in news_list],
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit
    )


@router.get("/today", response_model=NewsListResponse)
async def get_today_news(
    min_score: Optional[float] = Query(None, ge=0, le=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Get today's news articles
    """
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    query = db.query(News).filter(News.fetched_at >= today_start)

    if min_score is not None:
        query = query.filter(News.final_score >= min_score)

    total = query.count()
    news_list = query.order_by(desc(News.final_score)).limit(limit).all()

    return NewsListResponse(
        items=[NewsResponse.model_validate(n) for n in news_list],
        total=total,
        page=1,
        limit=limit,
        total_pages=1
    )


@router.get("/fetch/status/{task_id}")
async def get_fetch_status(task_id: str):
    """
    Get the status of a fetch task
    """
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{news_id}/refine-status")
async def get_refine_status(
    news_id: int,
    db: Session = Depends(get_db)
):
    """
    Get the refine (GLM content generation) status of a news item.
    Used by frontend to poll for content updates.
    """
    news = db.query(News).filter(News.id == news_id).first()

    if not news:
        raise HTTPException(status_code=404, detail="News not found")

    return {
        "id": news.id,
        "status": news.content_status or "pending",
        "content": news.content,
        "has_content": bool(news.content and len(news.content) > 50)
    }


@router.get("/{news_id}", response_model=NewsResponse)
async def get_news_detail(
    news_id: int,
    db: Session = Depends(get_db)
):
    """
    Get news article detail by ID
    """
    news = db.query(News).filter(News.id == news_id).first()

    if not news:
        raise HTTPException(status_code=404, detail="News not found")

    return NewsResponse.model_validate(news)


@router.post("/fetch")
async def start_fetch_news(
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Force fetch even if recently fetched"),
    quick: bool = Query(False, description="Quick mode: skip GLM content generation"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Start a background fetch task. Returns task_id for polling status.
    quick=True (default): Fast fetch without AI summaries
    quick=False: Full fetch with GLM content generation (slower)
    """
    # Check last fetch time (prevent abuse)
    if not force:
        last_news = db.query(News).order_by(desc(News.fetched_at)).first()
        if last_news and last_news.fetched_at:
            time_since_fetch = datetime.utcnow() - last_news.fetched_at
            if time_since_fetch < timedelta(minutes=5):
                return {
                    "task_id": None,
                    "status": "skipped",
                    "message": "News was fetched recently. Wait a few minutes or use force=true."
                }

    # Create task and start background job
    task_id = str(uuid.uuid4())
    create_task(task_id)

    # Get user settings for language
    user_settings = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    language = user_settings.audio_language if user_settings else "zh"

    # Run in background
    background_tasks.add_task(
        do_fetch_news_background,
        task_id=task_id,
        user_id=current_user.id,
        language=language,
        skip_glm=quick
    )

    return {
        "task_id": task_id,
        "status": "started",
        "message": "Fetch task started"
    }


async def do_fetch_news_background(task_id: str, user_id: int, language: str, skip_glm: bool = True):
    """
    Background task to fetch news and optionally generate GLM content
    """
    db = SessionLocal()
    try:
        # Step 1: Connect to sources
        update_task(task_id, status="running", progress=5, message="连接新闻源...")

        # Step 2: Fetch from multiple sources
        update_task(task_id, progress=15, message="获取 Hacker News...")
        await asyncio.sleep(0.1)

        update_task(task_id, progress=25, message="获取 Reddit AI 版块...")
        await asyncio.sleep(0.1)

        update_task(task_id, progress=35, message="获取 NewsAPI...")

        # Actually fetch news (always fast, GLM is async)
        update_task(task_id, progress=45, message="抓取新闻中...")

        result = await news_fetcher.fetch_and_save_news(
            db,
            page_size=50,
            language=language,
            skip_glm=True  # Always skip GLM in fetch, do it async
        )

        update_task(task_id, progress=70, message="去重与整理...")

        # Handle tuple return (new_count, skipped_count, saved_ids, no_content_count)
        if isinstance(result, tuple) and len(result) == 4:
            new_count, skipped_count, saved_ids, no_content_count = result
        elif isinstance(result, tuple) and len(result) == 3:
            new_count, skipped_count, saved_ids = result
            no_content_count = 0
        elif isinstance(result, tuple):
            new_count, skipped_count = result
            saved_ids = []
            no_content_count = 0
        else:
            new_count = result
            skipped_count = 0
            saved_ids = []
            no_content_count = 0

        # Step 3: Start async GLM content generation if not quick mode
        if not skip_glm and saved_ids:
            update_task(task_id, progress=75, message=f"后台生成摘要 ({len(saved_ids)} 条)...")
            # Start GLM generation in background (non-blocking)
            asyncio.create_task(
                generate_content_background(saved_ids, language)
            )

        # Step 4: Complete
        update_task(task_id, progress=95, message="保存数据...")
        await asyncio.sleep(0.2)

        msg = f"完成！新增 {new_count} 条"
        if skipped_count > 0:
            msg += f"，跳过 {skipped_count} 条重复"
        if no_content_count > 0:
            msg += f"，{no_content_count} 条无法抓取原文"
        if not skip_glm and saved_ids:
            msg += f"，摘要后台生成中"

        update_task(
            task_id,
            status="completed",
            progress=100,
            message=msg,
            result={
                "fetched_count": new_count,
                "skipped_count": skipped_count
            }
        )

    except Exception as e:
        update_task(
            task_id,
            status="failed",
            progress=0,
            message=f"出错: {str(e)[:50]}"
        )
    finally:
        db.close()


async def generate_content_background(news_ids: list, language: str):
    """Background task to generate GLM content for news items"""
    db = SessionLocal()
    try:
        await news_fetcher.generate_content_for_news(db, news_ids, language)
    except Exception as e:
        print(f"Background GLM generation error: {e}")
    finally:
        db.close()
