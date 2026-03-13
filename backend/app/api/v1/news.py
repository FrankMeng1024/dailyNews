from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from datetime import datetime, timedelta, timezone
import uuid
import logging

from app.database import get_db
from app.database_utils import async_safe_db_session
from app.api.deps import get_current_user
from app.models.user import User
from app.models.news import News
from app.schemas.news import NewsResponse, NewsListResponse
from app.services.task_store import create_task, update_task, get_task
from app.services.config_service import ConfigService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/news", tags=["News"])


@router.get("", response_model=NewsListResponse)
async def list_news(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    min_score: Optional[float] = Query(None, ge=0, le=1),
    quality_level: Optional[str] = Query(None),  # NEW: premium/standard/all
    source_type: Optional[str] = Query(None),  # NEW: news/blog/paper/discussion/all
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: Session = Depends(get_db)
):
    """
    List news articles with pagination and filtering
    If quality_level is provided, uses that level's threshold
    Otherwise uses min_score if provided
    source_type filters by content type (news/blog/paper/discussion)

    Only shows news with visibility_status = 'active'
    """
    query = db.query(News)

    # IMPORTANT: Only show articles with visibility_status = 'active'
    # This means translation is complete and article is ready for display
    query = query.filter(News.visibility_status == 'active')

    # Source type filtering
    if source_type and source_type != 'all':
        query = query.filter(News.source_type == source_type)

    # Quality level filtering (takes precedence over min_score)
    if quality_level:
        from app.services.quality_threshold_manager import QualityThresholdManager
        thresholds = QualityThresholdManager.get_thresholds(db)
        min_threshold = thresholds.get(quality_level, 0.0)
        query = query.filter(News.quality_score >= min_threshold)
    elif min_score is not None:
        query = query.filter(News.quality_score >= min_score)

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
    Get today's news articles (visibility_status = 'active')
    """
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    query = db.query(News).filter(News.created_at >= today_start)

    # Only show active articles
    query = query.filter(News.visibility_status == 'active')

    # Only show articles with Chinese title
    query = query.filter(News.title_zh.isnot(None))

    if min_score is not None:
        query = query.filter(News.quality_score >= min_score)

    total = query.count()
    news_list = query.order_by(desc(News.quality_score)).limit(limit).all()

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


@router.post("/fetch")
async def start_fetch_news(
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Force fetch even if recently fetched"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Start a background fetch task using new pipeline architecture.
    Returns task_id for polling status.
    """
    # Check last fetch time (prevent abuse)
    if not force:
        last_news = db.query(News).order_by(desc(News.created_at)).first()
        if last_news and last_news.created_at:
            time_since_fetch = datetime.now(timezone.utc) - last_news.created_at
            if time_since_fetch < timedelta(minutes=5):
                return {
                    "task_id": None,
                    "status": "skipped",
                    "message": "News was fetched recently. Wait a few minutes or use force=true."
                }

    # Create task and start background job
    task_id = str(uuid.uuid4())
    create_task(task_id)

    # Run in background using new pipeline
    background_tasks.add_task(
        do_fetch_news_background,
        task_id=task_id
    )

    return {
        "task_id": task_id,
        "status": "started",
        "message": "Fetch task started"
    }


@router.get("/{news_id}/refine-status")
async def get_refine_status(
    news_id: int,
    db: Session = Depends(get_db)
):
    """
    Get the processing status of a news item.
    Used by frontend to poll for content updates.
    """
    news = db.query(News).filter(News.id == news_id).first()

    if not news:
        raise HTTPException(status_code=404, detail="News not found")

    return {
        "id": news.id,
        "processing_status": news.processing_status,
        "visibility_status": news.visibility_status,
        "is_refining": news.processing_status == "refining",
        "is_complete": news.processing_status == "complete",
        "is_active": news.visibility_status == "active",
        "verification_score": float(news.verification_score) if news.verification_score else None,
        "content": news.content,
        "has_content": bool(news.content and len(news.content) > ConfigService.get(db, "min_summary_length", 50)),
        "error": news.last_error if news.visibility_status == "failed" else None
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


async def do_fetch_news_background(task_id: str):
    """
    Background task to fetch news using new pipeline architecture
    """
    from app.models.system_config import FetchHistory
    from app.services.pipeline import state_machine, register_handlers, basic_fetcher

    async with async_safe_db_session() as db:
        fetch_record = None

        try:
            # Create fetch history record
            fetch_record = FetchHistory(
                task_id=task_id,
                started_at=datetime.now(timezone.utc),
                status="running"
            )
            db.add(fetch_record)
            db.commit()

            update_task(task_id, status="running", progress=10, message="连接新闻源...")

            # Ensure state machine is running
            if not state_machine.is_running():
                register_handlers()
                await state_machine.start()

            update_task(task_id, progress=30, message="抓取新闻中...")

            # Fetch from all sources
            articles = await basic_fetcher.fetch_all_sources(limit_per_source=15)

            update_task(task_id, progress=50, message=f"处理 {len(articles)} 篇文章...")

            if not articles:
                update_task(task_id, status="completed", progress=100, message="没有新文章")
                if fetch_record:
                    fetch_record.status = "completed"
                    fetch_record.completed_at = datetime.now(timezone.utc)
                    fetch_record.found_count = 0
                    fetch_record.new_count = 0
                    db.commit()
                return

            # Create news records
            update_task(task_id, progress=70, message="保存新闻...")
            news_ids = await basic_fetcher.create_news_records(articles)

            # Enqueue for processing
            update_task(task_id, progress=85, message="加入处理队列...")
            await state_machine.enqueue_batch(news_ids)

            # Update fetch history
            if fetch_record:
                fetch_record.status = "completed"
                fetch_record.completed_at = datetime.now(timezone.utc)
                fetch_record.found_count = len(articles)
                fetch_record.new_count = len(news_ids)
                db.commit()

            update_task(
                task_id,
                status="completed",
                progress=100,
                message=f"完成！新增 {len(news_ids)} 条，已加入处理队列",
                result={
                    "fetched_count": len(news_ids),
                    "total_found": len(articles)
                }
            )

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"Fetch task {task_id} failed: {error_msg}", exc_info=True)

            if fetch_record:
                fetch_record.status = "failed"
                fetch_record.error_message = error_msg[:500]
                fetch_record.completed_at = datetime.now(timezone.utc)
                db.commit()

            update_task(
                task_id,
                status="failed",
                progress=0,
                message=f"出错: {error_msg[:100]}"
            )
