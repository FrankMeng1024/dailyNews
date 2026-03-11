#!/usr/bin/env python3
"""
数据库初始化脚本
开发和生产环境统一使用此脚本初始化数据库
"""

import sqlite3
import os

def init_database(db_path='ainews.db', sql_file='init_db.sql'):
    """
    使用 SQL 文件初始化数据库

    Args:
        db_path: 数据库文件路径
        sql_file: SQL 初始化文件路径
    """
    # 获取脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # 数据库文件的完整路径
    if not os.path.isabs(db_path):
        db_path = os.path.join(script_dir, db_path)

    # SQL 文件的完整路径
    if not os.path.isabs(sql_file):
        sql_file = os.path.join(script_dir, sql_file)

    # 检查 SQL 文件是否存在
    if not os.path.exists(sql_file):
        raise FileNotFoundError(f"SQL 文件不存在: {sql_file}")

    # 读取 SQL 文件
    with open(sql_file, 'r', encoding='utf-8') as f:
        sql_script = f.read()

    # 连接数据库并执行 SQL
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.executescript(sql_script)
        conn.commit()
        print(f"✓ 数据库初始化成功: {db_path}")

        # 显示创建的表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cursor.fetchall()
        print(f"\n✓ 创建的表 ({len(tables)} 个):")
        for table in tables:
            print(f"  - {table[0]}")

        return True
    except Exception as e:
        print(f"✗ 数据库初始化失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    # 支持命令行参数指定数据库路径
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'ainews.db'

    print("=" * 60)
    print("数据库初始化脚本")
    print("=" * 60)
    print(f"数据库路径: {db_path}")
    print()

    success = init_database(db_path)

    print()
    print("=" * 60)
    if success:
        print("✅ 初始化完成")
    else:
        print("❌ 初始化失败")
    print("=" * 60)

    sys.exit(0 if success else 1)
