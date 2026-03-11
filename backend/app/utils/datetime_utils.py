"""
日期时间处理工具

提供安全的日期时间解析和转换，统一时区处理
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Union
import logging

logger = logging.getLogger(__name__)


def parse_datetime_safe(
    value: Union[str, datetime, None],
    default: Optional[datetime] = None
) -> datetime:
    """安全解析日期时间，带详细错误日志

    Args:
        value: 要解析的值，可以是字符串、datetime 或 None
        default: 解析失败时的默认值，如果为 None 则使用当前 UTC 时间

    Returns:
        解析后的 datetime 对象（带 UTC 时区）

    支持的字符串格式:
        - ISO 8601: "2024-01-15T10:30:00Z"
        - ISO 8601 带时区: "2024-01-15T10:30:00+08:00"
        - 无时区: "2024-01-15T10:30:00"
    """
    if value is None:
        return default or datetime.now(timezone.utc)

    if isinstance(value, datetime):
        return ensure_utc(value)

    if isinstance(value, str):
        # 尝试多种格式解析
        formats_to_try = [
            # ISO 格式（最常见）
            lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")),
            # 带毫秒的格式
            lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f"),
            # 不带毫秒的格式
            lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%S"),
            # 日期格式
            lambda s: datetime.strptime(s, "%Y-%m-%d"),
        ]

        for parse_func in formats_to_try:
            try:
                dt = parse_func(value)
                return ensure_utc(dt)
            except (ValueError, TypeError):
                continue

        # 所有格式都失败
        logger.warning(f"Failed to parse datetime string '{value}', using default")
        return default or datetime.now(timezone.utc)

    # 不支持的类型
    logger.warning(f"Unexpected datetime type: {type(value).__name__}, using default")
    return default or datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """确保 datetime 有 UTC 时区

    Args:
        dt: datetime 对象

    Returns:
        带 UTC 时区的 datetime 对象
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_utc() -> datetime:
    """获取当前 UTC 时间"""
    return datetime.now(timezone.utc)


def minutes_ago(minutes: int) -> datetime:
    """获取 N 分钟前的 UTC 时间"""
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


def hours_ago(hours: int) -> datetime:
    """获取 N 小时前的 UTC 时间"""
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def days_ago(days: int) -> datetime:
    """获取 N 天前的 UTC 时间"""
    return datetime.now(timezone.utc) - timedelta(days=days)


def format_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """格式化 datetime 为字符串

    Args:
        dt: datetime 对象
        format_str: 格式字符串

    Returns:
        格式化后的字符串
    """
    if dt is None:
        return ""
    return dt.strftime(format_str)


def time_since(dt: datetime) -> str:
    """计算距离现在的时间差，返回人类可读的字符串

    Args:
        dt: datetime 对象

    Returns:
        如 "5分钟前", "2小时前", "3天前"
    """
    if dt is None:
        return "未知"

    dt = ensure_utc(dt)
    now = datetime.now(timezone.utc)
    diff = now - dt

    seconds = diff.total_seconds()

    if seconds < 60:
        return "刚刚"
    elif seconds < 3600:
        return f"{int(seconds / 60)}分钟前"
    elif seconds < 86400:
        return f"{int(seconds / 3600)}小时前"
    elif seconds < 604800:
        return f"{int(seconds / 86400)}天前"
    else:
        return format_datetime(dt, "%Y-%m-%d")


def calculate_next_retry_time(
    retry_count: int,
    intervals: list,
    base_time: Optional[datetime] = None
) -> datetime:
    """计算下次重试时间

    Args:
        retry_count: 当前重试次数
        intervals: 重试间隔列表（分钟）
        base_time: 基准时间，默认为当前时间

    Returns:
        下次重试的 datetime
    """
    base = base_time or datetime.now(timezone.utc)

    if retry_count >= len(intervals):
        interval = intervals[-1] if intervals else 5
    else:
        interval = intervals[retry_count]

    return base + timedelta(minutes=interval)
