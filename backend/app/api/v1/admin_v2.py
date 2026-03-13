"""
Admin API v2 - 使用新状态机架构

主要端点：
- POST /fetch-news-v2: 启动抓取任务
- GET /fetch-stream/{task_id}: SSE 实时进度
- POST /retry/{news_id}: 重试单条新闻
- GET /stats: 获取统计信息
"""

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone
import asyncio
import json
import uuid
import logging

from app.database import get_db, SessionLocal
from app.models.news import News
from app.models.system_config import FetchHistory
from app.config import settings
from app.services.pipeline import (
    state_machine,
    basic_fetcher,
    register_handlers,
)
from app.services.task_store import create_task, update_task, get_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-v2"])

# 创作者代码
CREATOR_CODE = getattr(settings, 'CREATOR_CODE', 'creator2026')


def verify_creator_code(x_creator_code: str = Header(...)):
    """验证创作者代码"""
    if x_creator_code != CREATOR_CODE:
        raise HTTPException(status_code=403, detail="Invalid creator code")
    return True


# ========== 抓取相关 ==========

@router.post("/fetch-news-v2")
async def fetch_news_v2(
    limit_per_source: int = Query(10, description="每个源的最大数量"),
    _: bool = Depends(verify_creator_code)
):
    """
    启动新版抓取任务

    使用状态机架构，返回 task_id 用于轮询状态
    """
    # 检查状态机是否运行
    if not state_machine.is_running():
        register_handlers()
        await state_machine.start()

    task_id = str(uuid.uuid4())

    # 创建任务状态（用于前端轮询）
    create_task(task_id)

    # 创建抓取历史
    db = SessionLocal()
    try:
        history = FetchHistory(
            task_id=task_id,
            status="running",
            started_at=datetime.now(timezone.utc)
        )
        db.add(history)
        db.commit()
    finally:
        db.close()

    # 启动后台任务
    asyncio.create_task(_do_fetch_v2(task_id, limit_per_source))

    return {"task_id": task_id, "message": "Fetch started"}


async def _do_fetch_v2(task_id: str, limit_per_source: int):
    """执行抓取任务"""
    db = SessionLocal()

    try:
        update_task(task_id, status="running", progress=5, message="开始抓取新闻...")

        # 1. 从各源抓取基本信息
        update_task(task_id, progress=10, message="正在从各源获取新闻...")
        articles = await basic_fetcher.fetch_all_sources(limit_per_source)
        update_task(task_id, progress=40, message=f"获取到 {len(articles)} 条新闻")

        if not articles:
            update_task(task_id, status="completed", progress=100, message="没有找到新闻", result={"found": 0, "new": 0, "fetched_count": 0})
            return

        # 2. 创建 News 记录
        update_task(task_id, progress=50, message=f"正在创建 {len(articles)} 条记录...")
        news_ids = await basic_fetcher.create_news_records(articles)
        update_task(task_id, progress=70, message=f"创建了 {len(news_ids)} 条新记录")

        # 3. 将所有新记录放入状态机队列
        await state_machine.enqueue_batch(news_ids)
        update_task(task_id, progress=90, message=f"已将 {len(news_ids)} 条新闻放入处理队列")

        # 4. 更新抓取历史
        history = db.query(FetchHistory).filter(FetchHistory.task_id == task_id).first()
        if history:
            history.found_count = len(articles)
            history.new_count = len(news_ids)
            history.status = "completed"
            history.completed_at = datetime.now(timezone.utc)
            db.commit()

        update_task(task_id, status="completed", progress=100,
                   message=f"完成！发现 {len(articles)} 条，新增 {len(news_ids)} 条",
                   result={"found": len(articles), "new": len(news_ids), "fetched_count": len(news_ids)})
        logger.info(f"Fetch task {task_id} completed: {len(articles)} found, {len(news_ids)} new")

    except Exception as e:
        logger.error(f"Fetch task {task_id} error: {e}")
        update_task(task_id, status="failed", message=str(e)[:200])

        # 更新历史为失败
        history = db.query(FetchHistory).filter(FetchHistory.task_id == task_id).first()
        if history:
            history.mark_failed(str(e))
            db.commit()

    finally:
        db.close()


@router.get("/fetch-stream/{task_id}")
async def fetch_stream(task_id: str):
    """SSE 流式返回抓取进度"""
    async def event_generator():
        queue = state_machine.event_queues.get(task_id)
        if not queue:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Task not found'})}\n\n"
            return

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get('type') in ('complete', 'error'):
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


# ========== 重试相关 ==========

@router.post("/retry/{news_id}")
async def retry_news(
    news_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """重试单条新闻"""
    news = db.query(News).filter(News.id == news_id).first()
    if not news:
        raise HTTPException(status_code=404, detail="News not found")

    if news.visibility_status != 'failed':
        raise HTTPException(status_code=400, detail="News is not in failed state")

    # 确保状态机运行
    if not state_machine.is_running():
        register_handlers()
        await state_machine.start()

    # 清除错误状态，放入队列
    news.visibility_status = 'inactive'
    news.last_error = None
    db.commit()

    await state_machine.enqueue(news_id)

    return {
        "success": True,
        "message": f"News {news_id} queued for retry",
        "current_status": news.processing_status
    }


@router.post("/retry-all-failed")
async def retry_all_failed(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """重试所有失败的新闻"""
    # 确保状态机运行
    if not state_machine.is_running():
        register_handlers()
        await state_machine.start()

    failed_news = db.query(News).filter(
        News.visibility_status == 'failed',
        News.retry_count < 5
    ).all()

    count = 0
    for news in failed_news:
        news.visibility_status = 'inactive'
        news.last_error = None
        await state_machine.enqueue(news.id)
        count += 1

    db.commit()

    return {
        "success": True,
        "retried_count": count,
        "message": f"Queued {count} failed news for retry"
    }


# ========== 统计相关 ==========

@router.get("/stats")
async def get_stats(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取处理统计"""
    # 按 processing_status 统计
    processing_stats = {}
    for status in ['created', 'fetching', 'verifying', 'translating', 'refining', 'complete']:
        count = db.query(func.count(News.id)).filter(News.processing_status == status).scalar() or 0
        processing_stats[status] = count

    # 按 visibility_status 统计
    visibility_stats = {}
    for status in ['inactive', 'active', 'skip', 'failed']:
        count = db.query(func.count(News.id)).filter(News.visibility_status == status).scalar() or 0
        visibility_stats[status] = count

    # 队列状态
    queue_size = state_machine.get_queue_size() if state_machine.is_running() else 0

    return {
        "processing": processing_stats,
        "visibility": visibility_stats,
        "queue_size": queue_size,
        "state_machine_running": state_machine.is_running(),
        "total": sum(processing_stats.values())
    }


@router.get("/failed-list")
async def get_failed_list(
    limit: int = Query(50, description="返回数量"),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取失败的新闻列表"""
    failed_news = db.query(News).filter(
        News.visibility_status == 'failed'
    ).order_by(News.created_at.desc()).limit(limit).all()

    return {
        "items": [
            {
                "id": n.id,
                "title": n.title[:60] if n.title else "",
                "title_zh": n.title_zh[:60] if n.title_zh else None,
                "source_name": n.source_name,
                "processing_status": n.processing_status,
                "error_step": n.error_step,
                "last_error": n.last_error,
                "retry_count": n.retry_count,
                "created_at": n.created_at.isoformat() if n.created_at else None
            }
            for n in failed_news
        ],
        "total": len(failed_news)
    }


@router.get("/processing-list")
async def get_processing_list(
    status: str = Query(None, description="过滤状态"),
    limit: int = Query(50, description="返回数量"),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取处理中的新闻列表（processing_status 不是 complete 的文章）"""
    # 返回所有还在处理中的文章（不管 visibility_status）
    query = db.query(News).filter(News.processing_status != 'complete')

    if status:
        query = query.filter(News.processing_status == status)

    news_list = query.order_by(News.created_at.desc()).limit(limit).all()

    return {
        "items": [
            {
                "id": n.id,
                "title": n.title[:60] if n.title else "",
                "source_name": n.source_name,
                "processing_status": n.processing_status,
                "created_at": n.created_at.isoformat() if n.created_at else None
            }
            for n in news_list
        ],
        "total": len(news_list)
    }


# ========== 验证代码 ==========

@router.post("/verify-code")
async def verify_code(code: str):
    """验证创作者代码"""
    if code == CREATOR_CODE:
        return {"valid": True, "message": "Creator code verified"}
    return {"valid": False, "message": "Invalid creator code"}
