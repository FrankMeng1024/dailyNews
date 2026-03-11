#!/usr/bin/env python3
"""诊断GLM API响应"""

import asyncio
import sys
import httpx
sys.path.insert(0, '.')

from app.config import settings

async def test_glm_api():
    api_key = settings.GLM_API_KEY
    api_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

    # Test 1: Simple request
    print("=" * 60)
    print("Test 1: Simple API Call")
    print("=" * 60)

    payload = {
        "model": "glm-4-flash",
        "messages": [
            {"role": "user", "content": "将以下英文翻译成中文：Hello World"}
        ],
        "temperature": 0.3,
        "max_tokens": 100
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                api_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json=payload
            )

            print(f"Status Code: {response.status_code}")
            print(f"Response Headers: {dict(response.headers)}")
            print(f"Response Body: {response.text[:500]}")

            if response.status_code == 200:
                data = response.json()
                print(f"\nParsed JSON:")
                print(f"  Choices: {len(data.get('choices', []))}")
                if data.get('choices'):
                    content = data['choices'][0].get('message', {}).get('content', '')
                    print(f"  Content: {content}")
            else:
                print(f"\nError: {response.text}")

    except Exception as e:
        print(f"Exception: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_glm_api())
