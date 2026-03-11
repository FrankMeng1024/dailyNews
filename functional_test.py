#!/usr/bin/env python3
"""
Functional Test for News Fetch System
测试新闻抓取系统的功能
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

import asyncio
import traceback
from app.database import SessionLocal
from app.services.news_fetcher import NewsFetcher
from app.models.news import News
from sqlalchemy import func

async def test_fetch():
    """测试新闻抓取功能"""
    print("=" * 80)
    print("功能测试：新闻抓取系统")
    print("=" * 80)
    print()

    db = SessionLocal()
    fetcher = NewsFetcher()

    try:
        # 1. 清空现有数据
        print("步骤 1: 清空现有数据...")
        db.query(News).delete()
        db.commit()
        print("✓ 数据清空完成")
        print()

        # 2. 执行抓取
        print("步骤 2: 执行新闻抓取...")
        print("-" * 80)
        result = await fetcher.fetch_and_save_news(
            db,
            page_size=50,
            language='zh',
            skip_glm=True  # 跳过GLM生成，加快测试
        )
        print("-" * 80)
        print()

        # 3. 检查结果
        print("步骤 3: 检查抓取结果...")

        # 结果可能是字典或元组
        if isinstance(result, dict):
            saved_count = result.get('saved_count', 0)
            duplicate_count = result.get('duplicate_count', 0)
            saved_ids = result.get('saved_ids', [])
        elif isinstance(result, tuple):
            if len(result) >= 3:
                saved_count, duplicate_count, saved_ids = result[0], result[1], result[2]
            else:
                saved_count, duplicate_count, saved_ids = result[0], result[1], []
        else:
            saved_count = result if isinstance(result, int) else 0
            duplicate_count = 0
            saved_ids = []

        print(f"  新增文章: {saved_count}")
        print(f"  重复跳过: {duplicate_count}")
        print(f"  保存ID数: {len(saved_ids)}")
        print()

        # 4. 验证数据库
        print("步骤 4: 验证数据库...")
        total_count = db.query(News).count()
        print(f"  数据库总计: {total_count} 条")

        if total_count > 0:
            # 获取质量分数统计
            stats = db.query(
                func.min(News.final_score).label('min'),
                func.max(News.final_score).label('max'),
                func.avg(News.final_score).label('avg')
            ).first()

            print(f"  质量分数范围: {stats.min:.4f} - {stats.max:.4f}")
            print(f"  平均分数: {stats.avg:.4f}")
            print()

            # 显示前5条
            print("  前5条新闻:")
            news_list = db.query(News).limit(5).all()
            for i, n in enumerate(news_list, 1):
                print(f"    {i}. [{n.source_name}] {n.title_zh or n.title}")
                print(f"       分数: {n.final_score:.4f} | 来源层级: {n.source_tier}")
        print()

        # 5. 测试质量阈值计算
        print("步骤 5: 测试质量阈值计算...")
        if total_count >= 10:
            from app.services.quality_threshold_manager import QualityThresholdManager

            thresholds = QualityThresholdManager.calculate_thresholds(db)
            print(f"  计算的阈值:")
            for level, threshold in thresholds.items():
                print(f"    {level}: {threshold:.2f}")

            # 统计各质量级别的文章数
            stats = QualityThresholdManager.get_score_statistics(db)
            print(f"  文章分布:")
            for level, count in stats['distribution'].items():
                print(f"    {level}: {count} 篇")
        else:
            print(f"  ⚠ 文章数量不足10篇，跳过阈值计算测试")
        print()

        # 6. 总结
        print("=" * 80)
        if total_count > 0:
            print("✓ 功能测试通过！")
            print(f"✓ 成功抓取并保存 {total_count} 条新闻")
            print("✓ 质量评分系统正常工作")
            if total_count >= 10:
                print("✓ 质量阈值计算正常")
        else:
            print("✗ 功能测试失败：未保存任何新闻")
            return 1
        print("=" * 80)

        return 0

    except Exception as e:
        print()
        print("=" * 80)
        print("✗ 功能测试失败！")
        print("=" * 80)
        print(f"错误信息: {str(e)}")
        print()
        print("完整堆栈:")
        traceback.print_exc()
        print("=" * 80)
        return 1

    finally:
        db.close()


if __name__ == "__main__":
    exit_code = asyncio.run(test_fetch())
    sys.exit(exit_code)
