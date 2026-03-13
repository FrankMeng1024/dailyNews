#!/usr/bin/env python3
"""
清除数据库数据脚本（不删除表结构）

用法:
    python clear_data.py          # 清除所有数据
    python clear_data.py --news   # 只清除新闻数据
    python clear_data.py --audio  # 只清除音频数据
    python clear_data.py --all    # 清除所有数据
    python clear_data.py --history # 只清除历史记录
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text, inspect
from app.database import SessionLocal, engine


def table_exists(table_name: str) -> bool:
    """检查表是否存在"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()


def clear_news(db):
    """清除新闻相关数据"""
    if table_exists("news"):
        db.execute(text("DELETE FROM news"))
        print("✓ 已清除 news 表")
    else:
        print("- news 表不存在，跳过")


def clear_audio(db):
    """清除音频相关数据"""
    cleared = False
    if table_exists("audio_news"):
        db.execute(text("DELETE FROM audio_news"))
        cleared = True
        print("✓ 已清除 audio_news 表")
    if table_exists("audio_recordings"):
        db.execute(text("DELETE FROM audio_recordings"))
        cleared = True
        print("✓ 已清除 audio_recordings 表")
    if not cleared:
        print("- audio 表不存在，跳过")


def clear_fetch_history(db):
    """清除抓取历史"""
    if table_exists("fetch_history"):
        db.execute(text("DELETE FROM fetch_history"))
        print("✓ 已清除 fetch_history 表")
    else:
        print("- fetch_history 表不存在，跳过")


def clear_retry_history(db):
    """清除重试历史"""
    if table_exists("retry_history"):
        db.execute(text("DELETE FROM retry_history"))
        print("✓ 已清除 retry_history 表")
    else:
        print("- retry_history 表不存在，跳过")


def clear_history(db):
    """清除所有历史记录"""
    clear_fetch_history(db)
    clear_retry_history(db)


def clear_all(db):
    """清除所有数据"""
    # 按依赖顺序删除
    clear_audio(db)
    clear_history(db)
    clear_news(db)
    print("\n所有数据已清除")


def main():
    args = sys.argv[1:] if len(sys.argv) > 1 else ['--all']

    db = SessionLocal()
    try:
        if '--news' in args:
            clear_news(db)
        elif '--audio' in args:
            clear_audio(db)
        elif '--history' in args:
            clear_history(db)
        elif '--all' in args or not args:
            clear_all(db)
        else:
            print("用法: python clear_data.py [--news|--audio|--history|--all]")
            return

        db.commit()
        print("\n✅ 数据清除完成！")

    except Exception as e:
        db.rollback()
        print(f"\n❌ 清除失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
