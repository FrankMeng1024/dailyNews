#!/usr/bin/env python3
"""测试新闻爬取功能"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

import asyncio
from app.database import SessionLocal
from app.services.news_fetcher import NewsFetcher
from app.models.news import News
from collections import Counter

async def main():
    print("🚀 开始爬取新闻...")
    print("")

    # 创建fetcher
    fetcher = NewsFetcher()
    db = SessionLocal()

    try:
        # 爬取新闻
        result = await fetcher.fetch_and_save_news(db)

        print("")
        print("=" * 50)
        print("📊 爬取结果统计")
        print("=" * 50)
        print(f"新增新闻: {result['saved_count']} 条")
        print(f"重复跳过: {result['duplicate_count']} 条")
        print("")

        # 查询数据库统计
        news_list = db.query(News).all()
        print(f"数据库总计: {len(news_list)} 条新闻")
        print("")

        # 统计类型分布
        type_dist = Counter(n.source_type for n in news_list)
        print("类型分布:")
        for type_name, count in type_dist.most_common():
            print(f"  {type_name}: {count} 条")
        print("")

        # 统计来源分布
        source_dist = Counter(n.source_name for n in news_list)
        print("来源分布 (Top 10):")
        for source, count in source_dist.most_common(10):
            print(f"  {source}: {count} 条")
        print("")

        # 检查翻译情况
        translated_count = sum(1 for n in news_list if n.title_zh)
        print(f"已翻译标题: {translated_count}/{len(news_list)} 条")

        # 检查验证情况
        verified_count = sum(1 for n in news_list if n.is_verified)
        print(f"已验证来源: {verified_count}/{len(news_list)} 条")
        print("")

        # 显示几个示例
        print("=" * 50)
        print("📰 示例新闻 (前5条)")
        print("=" * 50)
        for i, news in enumerate(news_list[:5], 1):
            print(f"{i}. [{news.source_type.upper()}] {news.title_zh or news.title}")
            print(f"   来源: {news.source_name}")
            print(f"   验证: {'✓' if news.is_verified else '✗'}")
            print("")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
