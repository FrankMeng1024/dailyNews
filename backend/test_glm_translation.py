#!/usr/bin/env python3
"""测试GLM翻译功能"""

import asyncio
import sys
sys.path.insert(0, '.')

from app.services.glm_service import glm_service

async def test_translation():
    print("=" * 60)
    print("Test 1: Simple Translation")
    print("=" * 60)
    titles = [
        "OpenAI Releases GPT-4 Turbo with Vision",
        "Google DeepMind Announces Gemini Pro"
    ]

    result = await glm_service.translate_titles_batch(titles)
    print(f"Input: {titles}")
    print(f"Output: {result}")
    print(f"Success: {len(result) == len(titles) and result[0] != titles[0]}")
    print()

    print("=" * 60)
    print("Test 2: Context-aware Translation")
    print("=" * 60)
    items = [
        {
            "title": "OpenAI Releases GPT-4 Turbo",
            "content": "OpenAI has announced GPT-4 Turbo, featuring improved performance and lower costs. The new model supports 128K context window and includes vision capabilities."
        }
    ]

    result = await glm_service.translate_titles_with_context(items)
    print(f"Input: {items[0]['title']}")
    print(f"Output: {result}")
    print(f"Success: {len(result) > 0 and result[0] != items[0]['title']}")
    print()

    print("=" * 60)
    print("Test 3: Error Handling")
    print("=" * 60)
    try:
        result = await glm_service.translate_titles_batch([])
        print(f"Empty input result: {result}")
        print(f"Success: {result == []}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_translation())
