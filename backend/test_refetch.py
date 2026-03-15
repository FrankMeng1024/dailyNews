"""
测试脚本：重新抓取所有新闻，检查新逻辑的效果
"""

import asyncio
import sys
sys.path.insert(0, '.')

from app.database import SessionLocal
from app.models.news import News
from app.services.pipeline.content_fetcher import content_fetcher


async def test_refetch_all():
    """重新抓取所有新闻并统计结果"""
    db = SessionLocal()

    try:
        # 获取所有新闻
        all_news = db.query(News).all()
        print(f"\n总共 {len(all_news)} 条新闻\n")

        # 按来源分组统计
        source_stats = {}

        results = {
            "success": [],
            "ai_validated": [],
            "failed": []
        }

        for i, news in enumerate(all_news):
            source = news.source_name or "Unknown"
            if source not in source_stats:
                source_stats[source] = {"total": 0, "success": 0, "ai_validated": 0, "failed": 0}
            source_stats[source]["total"] += 1

            print(f"[{i+1}/{len(all_news)}] {source}: {news.title[:50]}...")

            try:
                # 抓取内容
                content = await content_fetcher._scrape_content(news.source_url, news.source_name)

                if content and len(content) >= 200:
                    # 规则验证
                    if content_fetcher._validate_content(news.title, content):
                        print(f"  ✓ 规则验证通过: {len(content)} chars")
                        results["success"].append({
                            "id": news.id,
                            "source": source,
                            "title": news.title,
                            "content_len": len(content)
                        })
                        source_stats[source]["success"] += 1
                    else:
                        # 需要 AI 验证
                        print(f"  ? 规则验证失败，需要 AI 验证: {len(content)} chars")
                        results["ai_validated"].append({
                            "id": news.id,
                            "source": source,
                            "title": news.title,
                            "content_len": len(content),
                            "content_preview": content[:200]
                        })
                        source_stats[source]["ai_validated"] += 1
                else:
                    print(f"  ✗ 抓取失败或内容过短: {len(content) if content else 0} chars")
                    results["failed"].append({
                        "id": news.id,
                        "source": source,
                        "title": news.title,
                        "url": news.source_url,
                        "content_len": len(content) if content else 0
                    })
                    source_stats[source]["failed"] += 1

            except Exception as e:
                print(f"  ✗ 错误: {e}")
                results["failed"].append({
                    "id": news.id,
                    "source": source,
                    "title": news.title,
                    "url": news.source_url,
                    "error": str(e)
                })
                source_stats[source]["failed"] += 1

        # 打印统计结果
        print("\n" + "="*80)
        print("统计结果")
        print("="*80)

        print(f"\n总计: {len(all_news)} 条")
        print(f"  ✓ 规则验证通过: {len(results['success'])} ({len(results['success'])/len(all_news)*100:.1f}%)")
        print(f"  ? 需要 AI 验证: {len(results['ai_validated'])} ({len(results['ai_validated'])/len(all_news)*100:.1f}%)")
        print(f"  ✗ 抓取失败: {len(results['failed'])} ({len(results['failed'])/len(all_news)*100:.1f}%)")

        print("\n按来源统计:")
        print("-"*80)
        for source, stats in sorted(source_stats.items(), key=lambda x: x[1]["total"], reverse=True):
            total = stats["total"]
            success = stats["success"]
            ai = stats["ai_validated"]
            failed = stats["failed"]
            success_rate = (success / total * 100) if total > 0 else 0
            print(f"  {source[:30]:<30} | 总计:{total:>3} | 成功:{success:>3} ({success_rate:>5.1f}%) | AI验证:{ai:>3} | 失败:{failed:>3}")

        # 打印需要 AI 验证的样本
        if results["ai_validated"]:
            print("\n" + "="*80)
            print("需要 AI 验证的样本（前5条）:")
            print("="*80)
            for item in results["ai_validated"][:5]:
                print(f"\n[{item['source']}] {item['title']}")
                print(f"  内容预览: {item['content_preview'][:100]}...")

        # 打印失败的样本
        if results["failed"]:
            print("\n" + "="*80)
            print("抓取失败的样本（前10条）:")
            print("="*80)
            for item in results["failed"][:10]:
                print(f"\n[{item['source']}] {item['title']}")
                print(f"  URL: {item.get('url', 'N/A')[:80]}")
                if 'error' in item:
                    print(f"  错误: {item['error']}")
                else:
                    print(f"  内容长度: {item.get('content_len', 0)}")

        return results

    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(test_refetch_all())
