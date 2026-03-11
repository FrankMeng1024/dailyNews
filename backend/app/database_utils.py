"""
数据库会话安全管理工具

提供上下文管理器确保数据库会话正确关闭，防止连接泄漏
"""

from contextlib import contextmanager, asynccontextmanager
from typing import Generator, AsyncGenerator
import logging

from sqlalchemy.orm import Session
from app.database import SessionLocal

logger = logging.getLogger(__name__)


@contextmanager
def safe_db_session() -> Generator[Session, None, None]:
    """同步安全数据库会话上下文管理器

    使用方式:
        with safe_db_session() as db:
            db.query(News).all()

    特性:
        - 自动关闭会话
        - 异常时自动回滚
        - 记录错误日志
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        logger.error(f"Database error in sync session: {e}", exc_info=True)
        raise
    finally:
        db.close()


@asynccontextmanager
async def async_safe_db_session() -> AsyncGenerator[Session, None]:
    """异步安全数据库会话上下文管理器

    使用方式:
        async with async_safe_db_session() as db:
            db.query(News).all()

    特性:
        - 自动关闭会话
        - 异常时自动回滚
        - 记录错误日志

    注意:
        虽然这是异步上下文管理器，但 SQLAlchemy 的 Session 本身是同步的
        这个包装器主要用于在异步函数中安全管理会话生命周期
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        logger.error(f"Database error in async session: {e}", exc_info=True)
        raise
    finally:
        db.close()


def get_db_session() -> Session:
    """获取新的数据库会话（调用者负责关闭）

    警告: 使用此函数时必须确保在 finally 块中调用 db.close()
    推荐使用 safe_db_session() 上下文管理器代替
    """
    return SessionLocal()


class DatabaseSessionManager:
    """数据库会话管理器类

    用于需要更细粒度控制的场景
    """

    def __init__(self):
        self._session: Session = None

    def __enter__(self) -> Session:
        self._session = SessionLocal()
        return self._session

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._session.rollback()
            logger.error(f"Database error: {exc_val}", exc_info=True)
        self._session.close()
        self._session = None
        return False  # 不抑制异常

    async def __aenter__(self) -> Session:
        self._session = SessionLocal()
        return self._session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._session.rollback()
            logger.error(f"Async database error: {exc_val}", exc_info=True)
        self._session.close()
        self._session = None
        return False
