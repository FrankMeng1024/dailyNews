"""
Admin API - 管理员接口（需要创作者代码验证）

注意：主要功能已迁移到 admin_v2.py
此文件保留兼容性端点，逐步废弃
"""

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, Any
from pydantic import BaseModel
import logging

from app.database import get_db
from app.models.news import News
from app.services.config_service import ConfigService, DEFAULT_CONFIG
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# 创作者代码（从环境变量读取，默认值）
CREATOR_CODE = getattr(settings, 'CREATOR_CODE', 'creator2026')


def verify_creator_code(x_creator_code: str = Header(...)):
    """验证创作者代码"""
    if x_creator_code != CREATOR_CODE:
        raise HTTPException(status_code=403, detail="Invalid creator code")
    return True


@router.post("/verify-code")
async def verify_code(code: str):
    """验证创作者代码"""
    if code == CREATOR_CODE:
        return {"valid": True, "message": "Creator code verified"}
    return {"valid": False, "message": "Invalid creator code"}


# ========== 兼容性端点 - 重定向到 v2 ==========

@router.post("/fetch-news")
async def admin_fetch_news(
    force: bool = Query(False, description="强制抓取，忽略时间限制"),
    _: bool = Depends(verify_creator_code)
):
    """
    [已废弃] 请使用 /fetch-news-v2

    此端点返回提示信息，引导使用新 API
    """
    return {
        "error": "deprecated",
        "message": "此端点已废弃，请使用 /api/v1/admin/fetch-news-v2",
        "new_endpoint": "/api/v1/admin/fetch-news-v2"
    }


@router.get("/fetch-status")
async def get_fetch_status(_: bool = Depends(verify_creator_code)):
    """获取当前抓取任务状态 - 使用新版状态机"""
    from app.services.pipeline import state_machine
    return {
        "is_running": state_machine.is_running(),
        "queue_size": state_machine.get_queue_size() if state_machine.is_running() else 0
    }


@router.get("/current-state")
async def get_current_state(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取当前系统状态"""
    from app.services.pipeline import state_machine

    # 获取正在处理的新闻
    processing_news = db.query(News).filter(
        News.visibility_status == 'inactive',
        News.processing_status != 'complete'
    ).order_by(News.created_at.desc()).limit(100).all()

    news_list = []
    for news in processing_news:
        news_list.append({
            "id": news.id,
            "title": news.title[:60] if news.title else "",
            "title_zh": news.title_zh[:60] if news.title_zh else None,
            "source": news.source_name[:20] if news.source_name else "",
            "processing_status": news.processing_status,
            "visibility_status": news.visibility_status,
            "created_at": news.created_at.isoformat() if news.created_at else None
        })

    # 获取统计数据
    stats = {}
    for status in ['created', 'fetching', 'verifying', 'translating', 'refining', 'complete']:
        stats[status] = db.query(func.count(News.id)).filter(
            News.processing_status == status
        ).scalar() or 0

    return {
        "is_fetching": state_machine.is_running(),
        "queue_size": state_machine.get_queue_size() if state_machine.is_running() else 0,
        "processing_news": news_list,
        "stats": stats
    }


@router.get("/processing-stats")
async def get_processing_stats(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取各处理状态的数量统计"""
    from datetime import datetime, timezone

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    stats = {}
    for status in ['created', 'fetching', 'verifying', 'translating', 'refining', 'complete']:
        stats[status] = db.query(func.count(News.id)).filter(
            News.processing_status == status
        ).scalar() or 0

    # 今日完成数
    stats["complete_today"] = db.query(func.count(News.id)).filter(
        News.visibility_status == "active",
        News.created_at >= today_start
    ).scalar() or 0

    # 失败数
    stats["failed"] = db.query(func.count(News.id)).filter(
        News.visibility_status == "failed"
    ).scalar() or 0

    stats["total"] = sum(stats[s] for s in ['created', 'fetching', 'verifying', 'translating', 'refining', 'complete'])
    stats["processing"] = sum(stats[s] for s in ['created', 'fetching', 'verifying', 'translating', 'refining'])

    return stats


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


# ========== Fetch History ==========

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
            "task_id": h.task_id,
            "status": h.status,
            "found_count": h.found_count,
            "new_count": h.new_count,
            "skip_count": h.skip_count,
            "failed_count": h.failed_count,
            "error_message": h.error_message,
            "started_at": h.started_at.isoformat() if h.started_at else None,
            "completed_at": h.completed_at.isoformat() if h.completed_at else None,
            "duration_seconds": round(duration, 1) if duration else None
        })

    return {"items": items, "total": len(items)}


# ========== System Health ==========

@router.get("/system-health")
async def get_system_health(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_creator_code)
):
    """获取系统健康状态"""
    from app.services.pipeline import state_machine

    total_news = db.query(func.count(News.id)).scalar() or 0
    active_news = db.query(func.count(News.id)).filter(
        News.visibility_status == "active"
    ).scalar() or 0
    failed_news = db.query(func.count(News.id)).filter(
        News.visibility_status == "failed"
    ).scalar() or 0

    config = ConfigService.get_all(db)

    return {
        "status": "healthy" if failed_news < 100 else "degraded",
        "total_news": total_news,
        "active_news": active_news,
        "failed_news": failed_news,
        "success_rate": round(active_news / total_news * 100, 1) if total_news > 0 else 0,
        "state_machine_running": state_machine.is_running(),
        "queue_size": state_machine.get_queue_size() if state_machine.is_running() else 0,
        "config": config
    }
