#!/usr/bin/env python3
"""回填中文标题"""

import asyncio
from app.database import SessionLocal
from app.models.news import News
from app.services.glm_service import glm_service

async def backfill_translations():
    db = SessionLocal()

    # 查找未翻译或翻译失败的新闻（title_zh等于title）
    news_list = db.query(News).filter(
        (News.title_zh == None) |
        (News.title_zh == News.title)
    ).all()

    print(f"Found {len(news_list)} news items to translate")

    if not news_list:
        print("No news items need translation")
        return

    # 分批翻译（避免单次请求过大）
    batch_size = 20
    total_success = 0

    for i in range(0, len(news_list), batch_size):
        batch = news_list[i:i+batch_size]
        print(f"\nProcessing batch {i//batch_size + 1}/{(len(news_list)-1)//batch_size + 1}")

        # 准备数据
        items = [
            {"title": n.title, "content": n.original_content or n.summary or ""}
            for n in batch
        ]

        # 翻译
        try:
            translated = await glm_service.translate_titles_with_context(items)

            # 更新数据库
            for j, news in enumerate(batch):
                if j < len(translated) and translated[j] != news.title:
                    news.title_zh = translated[j]
                    total_success += 1
                    print(f"✓ [{news.id}] {news.title[:40]} → {translated[j]}")
                else:
                    print(f"✗ [{news.id}] Translation failed or unchanged")

            db.commit()
            await asyncio.sleep(1)  # 避免API限流

        except Exception as e:
            print(f"❌ Batch translation error: {e}")
            continue

    print(f"\n{'='*60}")
    print(f"Backfill completed: {total_success}/{len(news_list)} titles translated")
    print(f"{'='*60}")

    db.close()

if __name__ == "__main__":
    asyncio.run(backfill_translations())
