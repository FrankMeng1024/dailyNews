"""
Content Retry Service - 内容精炼重试补偿机制

功能：
1. 启动时自动修复异常状态
2. 定时重试pending内容
3. 智能失败处理
4. 提供Admin管理接口
"""

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.news import News
from app.models.retry_history import RetryHistory
from app.services.news_fetcher import news_fetcher


class ContentRetryService:
    """内容精炼重试服务"""

    # 配置
    GENERATING_TIMEOUT_MINUTES = 10  # generating状态超时时间
    RETRY_BATCH_SIZE = 15  # 每次重试的批量大小
    MAX_RETRIES = 5  # 最大重试次数
    TITLE_MAX_RETRIES = 5  # 标题翻译最大重试次数

    def __init__(self):
        pass

    async def startup_healing(self, db: Session) -> Dict[str, int]:
        """
        启动时自动修复异常状态

        Returns:
            修复统计 {healed_generating: int, reset_pending: int, title_reset: int}
        """
        print("=" * 60)
        print("CONTENT RETRY SERVICE - Startup Healing")
        print("=" * 60)

        healed_count = 0
        reset_count = 0
        title_reset_count = 0

        # 1. 修复卡住的generating状态
        timeout_threshold = datetime.now(timezone.utc) - timedelta(minutes=self.GENERATING_TIMEOUT_MINUTES)

        generating_news = db.query(News).filter(
            News.content_status == "generating"
        ).all()

        for news in generating_news:
            # 检查是否超时（通过created_at或updated_at判断）
            last_update = news.created_at
            if last_update < timeout_threshold:
                print(f"Healing stuck generating: {news.id} - {news.title[:50]}")
                news.content_status = "pending"
                news.glm_next_retry_at = datetime.now(timezone.utc)
                healed_count += 1

        # 2. 重置长时间pending但没有retry_at的新闻
        old_pending = db.query(News).filter(
            and_(
                News.content_status == "pending",
                News.glm_next_retry_at.is_(None),
                News.glm_retry_count == 0
            )
        ).all()

        for news in old_pending:
            print(f"Reset pending retry time: {news.id} - {news.title[:50]}")
            news.glm_next_retry_at = datetime.now(timezone.utc)
            reset_count += 1

        # 3. 重置标题翻译pending但没有retry_at的新闻
        title_pending = db.query(News).filter(
            and_(
                News.title_status == "pending",
                News.title_next_retry_at.is_(None),
                or_(News.title_retry_count == 0, News.title_retry_count.is_(None))
            )
        ).all()

        for news in title_pending:
            print(f"Reset title pending retry time: {news.id} - {news.title[:50]}")
            news.title_next_retry_at = datetime.now(timezone.utc)
            title_reset_count += 1

        db.commit()

        print(f"✓ Healed {healed_count} generating, reset {reset_count} pending, {title_reset_count} title pending")
        print("=" * 60)

        return {
            "healed_generating": healed_count,
            "reset_pending": reset_count,
            "title_reset": title_reset_count
        }

    async def process_pending_batch(self, db: Session, batch_size: int = None, trigger_type: str = "auto") -> Dict[str, Any]:
        """
        处理一批pending新闻

        Args:
            db: 数据库session
            batch_size: 批量大小，默认使用RETRY_BATCH_SIZE
            trigger_type: 触发类型 ('auto' 或 'manual')

        Returns:
            处理结果统计
        """
        if batch_size is None:
            batch_size = self.RETRY_BATCH_SIZE

        now = datetime.now(timezone.utc)

        # 查询需要重试的新闻
        pending_news = db.query(News).filter(
            and_(
                News.content_status == "pending",
                News.glm_retry_count < self.MAX_RETRIES,
                or_(
                    News.glm_next_retry_at.is_(None),
                    News.glm_next_retry_at <= now
                )
            )
        ).limit(batch_size).all()

        if not pending_news:
            return {
                "processed": 0,
                "success": 0,
                "failed": 0
            }

        print(f"Processing {len(pending_news)} pending news for content generation...")

        # 提取ID列表
        news_ids = [n.id for n in pending_news]

        # 调用GLM生成内容
        try:
            success_count = await news_fetcher.generate_content_for_news(db, news_ids, language="zh")
        except Exception as e:
            # 记录失败历史
            history = RetryHistory(
                trigger_type=trigger_type,
                processed_count=len(pending_news),
                success_count=0,
                failed_count=len(pending_news),
                error_message=str(e)
            )
            db.add(history)
            db.commit()
            raise

        # 标记达到最大重试次数的为failed
        failed_count = 0
        for news in pending_news:
            if news.glm_retry_count >= self.MAX_RETRIES and news.content_status == "pending":
                news.content_status = "failed"
                news.glm_last_error = "Max retries reached"
                failed_count += 1

        db.commit()

        # 记录成功历史
        history = RetryHistory(
            trigger_type=trigger_type,
            processed_count=len(pending_news),
            success_count=success_count,
            failed_count=failed_count
        )
        db.add(history)
        db.commit()

        return {
            "processed": len(pending_news),
            "success": success_count,
            "failed": failed_count
        }

    def get_content_status_stats(self, db: Session) -> Dict[str, Any]:
        """
        获取内容状态统计

        Returns:
            统计信息
        """
        from sqlalchemy import func

        # 按状态统计
        status_counts = db.query(
            News.content_status,
            func.count(News.id).label('count')
        ).group_by(News.content_status).all()

        stats = {status: count for status, count in status_counts}

        # 获取最老的pending新闻
        oldest_pending = db.query(News).filter(
            News.content_status == "pending"
        ).order_by(News.created_at.asc()).first()

        # 获取平均retry次数
        avg_retry = db.query(
            func.avg(News.glm_retry_count)
        ).filter(
            News.content_status.in_(["pending", "failed"])
        ).scalar() or 0

        return {
            "status_counts": stats,
            "oldest_pending_age_hours": (
                (datetime.now(timezone.utc) - oldest_pending.created_at).total_seconds() / 3600
                if oldest_pending else 0
            ),
            "average_retry_count": round(avg_retry, 2),
            "total_news": sum(stats.values())
        }

    def get_retry_list(self, db: Session, status: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取需要重试的新闻列表（用于Admin页面）

        Args:
            status: 过滤状态 (pending/failed/generating)
            limit: 返回数量限制

        Returns:
            新闻列表
        """
        query = db.query(News)

        if status:
            query = query.filter(News.content_status == status)
        else:
            query = query.filter(News.content_status.in_(["pending", "failed", "generating"]))

        news_list = query.order_by(News.created_at.desc()).limit(limit).all()

        return [
            {
                "id": n.id,
                "title": n.title_zh or n.title,
                "source_name": n.source_name,
                "content_status": n.content_status,
                "retry_count": n.glm_retry_count or 0,
                "last_error": n.glm_last_error,
                "next_retry_at": n.glm_next_retry_at.isoformat() if n.glm_next_retry_at else None,
                "created_at": n.created_at.isoformat(),
                "age_hours": round((datetime.now(timezone.utc) - n.created_at).total_seconds() / 3600, 1)
            }
            for n in news_list
        ]

    async def manual_retry(self, db: Session, news_ids: List[int]) -> Dict[str, Any]:
        """
        手动重试指定新闻（Admin操作）

        Args:
            news_ids: 新闻ID列表

        Returns:
            重试结果
        """
        # 重置retry状态
        news_list = db.query(News).filter(News.id.in_(news_ids)).all()

        for news in news_list:
            news.content_status = "pending"
            news.glm_retry_count = 0
            news.glm_last_error = None
            news.glm_next_retry_at = datetime.now(timezone.utc)

        db.commit()

        # 立即处理
        success_count = await news_fetcher.generate_content_for_news(db, news_ids, language="zh")

        return {
            "total": len(news_ids),
            "success": success_count,
            "failed": len(news_ids) - success_count
        }

    async def reset_all_failed(self, db: Session) -> int:
        """
        重置所有failed状态的新闻（Admin操作）

        Returns:
            重置数量
        """
        failed_news = db.query(News).filter(News.content_status == "failed").all()

        for news in failed_news:
            news.content_status = "pending"
            news.glm_retry_count = 0
            news.glm_last_error = None
            news.glm_next_retry_at = datetime.now(timezone.utc)

        db.commit()

        return len(failed_news)

    def get_retry_history(self, db: Session, limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取重试历史记录

        Args:
            limit: 返回数量限制

        Returns:
            历史记录列表
        """
        history_list = db.query(RetryHistory).order_by(
            RetryHistory.created_at.desc()
        ).limit(limit).all()

        return [
            {
                "id": h.id,
                "trigger_type": h.trigger_type,
                "processed_count": h.processed_count,
                "success_count": h.success_count,
                "failed_count": h.failed_count,
                "error_message": h.error_message,
                "created_at": h.created_at.isoformat(),
                "success_rate": round(h.success_count / h.processed_count * 100, 1) if h.processed_count > 0 else 0
            }
            for h in history_list
        ]

    # ========== Title Translation Retry Methods ==========

    async def process_pending_titles(self, db: Session, batch_size: int = None) -> Dict[str, Any]:
        """
        处理一批待翻译标题的新闻（重试队列）

        重试队列使用1条/条模式，确保最大成功率

        Args:
            db: 数据库session
            batch_size: 每次处理的新闻数量，默认10条

        Returns:
            处理结果统计
        """
        if batch_size is None:
            batch_size = 10  # 每次从队列取10条处理

        now = datetime.now(timezone.utc)

        # 查询需要翻译的新闻
        pending_news = db.query(News).filter(
            and_(
                News.title_status == "pending",
                or_(News.title_retry_count.is_(None), News.title_retry_count < self.TITLE_MAX_RETRIES),
                or_(
                    News.title_next_retry_at.is_(None),
                    News.title_next_retry_at <= now
                )
            )
        ).limit(batch_size).all()

        if not pending_news:
            return {
                "processed": 0,
                "success": 0,
                "failed": 0
            }

        print(f"[Retry Queue] Processing {len(pending_news)} pending titles one by one...")

        success_count = 0
        failed_count = 0

        # 一条一条处理，确保最大成功率
        for news in pending_news:
            try:
                from app.services.glm_service import glm_service

                # 准备数据
                news_items = [{
                    "title": news.title,
                    "content": news.original_content or news.summary or ""
                }]

                # 调用翻译
                translated = await glm_service.translate_titles_with_context(news_items)

                if translated and translated[0] and translated[0] != news.title:
                    # 成功
                    news.title_zh = translated[0]
                    news.title_status = "ready"
                    news.title_last_error = None
                    news.title_next_retry_at = None
                    success_count += 1
                    print(f"  ✓ [{news.id}] {news.title[:30]}... → {translated[0]}")
                else:
                    # 翻译返回空或未变化
                    news.title_retry_count = (news.title_retry_count or 0) + 1
                    if news.title_retry_count >= self.TITLE_MAX_RETRIES:
                        news.title_status = "failed"
                        news.title_last_error = "Max retries reached"
                        failed_count += 1
                    else:
                        news.title_next_retry_at = now + timedelta(minutes=self._get_retry_interval(news.title_retry_count))
                        news.title_last_error = "Translation returned unchanged or empty"
                    print(f"  ✗ [{news.id}] Failed, retry_count={news.title_retry_count}")

                db.commit()

                # 每条之间延迟0.5秒
                import asyncio
                await asyncio.sleep(0.5)

            except Exception as e:
                print(f"  ⚠ [{news.id}] Error: {str(e)[:50]}")
                news.title_retry_count = (news.title_retry_count or 0) + 1
                if news.title_retry_count >= self.TITLE_MAX_RETRIES:
                    news.title_status = "failed"
                    news.title_last_error = str(e)[:500]
                    failed_count += 1
                else:
                    news.title_next_retry_at = now + timedelta(minutes=self._get_retry_interval(news.title_retry_count))
                    news.title_last_error = str(e)[:500]
                db.commit()

                # 错误后延迟更长
                import asyncio
                await asyncio.sleep(2)

        print(f"[Retry Queue] Completed: {success_count} success, {failed_count} failed")

        return {
            "processed": len(pending_news),
            "success": success_count,
            "failed": failed_count
        }

    def _get_retry_interval(self, retry_count: int) -> int:
        """获取重试间隔（分钟）"""
        intervals = [1, 3, 6, 9, 12]
        if retry_count >= len(intervals):
            return intervals[-1]
        return intervals[retry_count]

    def get_title_status_stats(self, db: Session) -> Dict[str, Any]:
        """
        获取标题翻译状态统计

        Returns:
            统计信息
        """
        from sqlalchemy import func

        # 按状态统计
        status_counts = db.query(
            News.title_status,
            func.count(News.id).label('count')
        ).group_by(News.title_status).all()

        stats = {status or 'unknown': count for status, count in status_counts}

        return {
            "status_counts": stats,
            "total_news": sum(stats.values())
        }

    def get_title_retry_list(self, db: Session, status: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取需要翻译重试的新闻列表（用于Admin页面）

        Args:
            status: 过滤状态 (pending/failed)
            limit: 返回数量限制

        Returns:
            新闻列表
        """
        query = db.query(News)

        if status:
            query = query.filter(News.title_status == status)
        else:
            query = query.filter(News.title_status.in_(["pending", "failed"]))

        news_list = query.order_by(News.created_at.desc()).limit(limit).all()

        return [
            {
                "id": n.id,
                "title": n.title,
                "title_zh": n.title_zh,
                "source_name": n.source_name,
                "title_status": n.title_status,
                "retry_count": n.title_retry_count or 0,
                "last_error": n.title_last_error,
                "next_retry_at": n.title_next_retry_at.isoformat() if n.title_next_retry_at else None,
                "created_at": n.created_at.isoformat(),
                "age_hours": round((datetime.now(timezone.utc) - n.created_at).total_seconds() / 3600, 1)
            }
            for n in news_list
        ]

    async def manual_retry_titles(self, db: Session, news_ids: List[int]) -> Dict[str, Any]:
        """
        手动重试指定新闻的标题翻译（Admin操作）

        Args:
            news_ids: 新闻ID列表

        Returns:
            重试结果
        """
        # 重置retry状态
        news_list = db.query(News).filter(News.id.in_(news_ids)).all()

        for news in news_list:
            news.title_status = "pending"
            news.title_retry_count = 0
            news.title_last_error = None
            news.title_next_retry_at = datetime.now(timezone.utc)

        db.commit()

        # 立即处理
        success_count = await news_fetcher._translate_titles_for_news(db, news_ids)

        return {
            "total": len(news_ids),
            "success": success_count,
            "failed": len(news_ids) - success_count
        }

    async def reset_all_failed_titles(self, db: Session) -> int:
        """
        重置所有标题翻译failed状态的新闻（Admin操作）

        Returns:
            重置数量
        """
        failed_news = db.query(News).filter(News.title_status == "failed").all()

        for news in failed_news:
            news.title_status = "pending"
            news.title_retry_count = 0
            news.title_last_error = None
            news.title_next_retry_at = datetime.now(timezone.utc)

        db.commit()

        return len(failed_news)


# 全局实例
content_retry_service = ContentRetryService()
