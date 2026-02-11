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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Start a background fetch task. Returns task_id for polling status.
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
        language=language
    )

    return {
        "task_id": task_id,
        "status": "started",
        "message": "Fetch task started"
    }


async def do_fetch_news_background(task_id: str, user_id: int, language: str):
    """
    Background task to fetch news with GLM content generation
    """
    db = SessionLocal()
    try:
        update_task(task_id, status="running", progress=10, message="Fetching from sources...")

        # Fetch news with full GLM processing (skip_glm=False)
        update_task(task_id, progress=30, message="Processing with GLM...")

        result = await news_fetcher.fetch_and_save_news(
            db,
            page_size=50,
            language=language,
            skip_glm=False  # Full fetch with GLM content generation
        )

        # Handle tuple return (new_count, skipped_count) or int
        if isinstance(result, tuple):
            new_count, skipped_count = result
        else:
            new_count = result
            skipped_count = 0

        update_task(task_id, progress=80, message="Scoring articles...")

        # Score new news with GLM
        if new_count > 0:
            unscored_news = db.query(News).filter(News.glm_score == None).all()
            if unscored_news:
                await glm_service.score_and_update_news(db, unscored_news)

        update_task(
            task_id,
            status="completed",
            progress=100,
            message=f"Added {new_count} new, skipped {skipped_count} duplicates",
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
            message=str(e)
        )
    finally:
        db.close()
