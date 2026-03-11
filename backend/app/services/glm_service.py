import httpx
import json
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.models.news import News
from app.services.config_service import ConfigService, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class GLMService:
    """Service for Zhipu GLM API integration"""

    def __init__(self):
        self.api_key = settings.GLM_API_KEY
        self.api_url = settings.GLM_API_URL
        self.model = settings.GLM_MODEL

    def _get_headers(self) -> Dict[str, str]:
        """Get API request headers"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def _call_api(self, messages: List[Dict[str, str]], max_tokens: int = 1024, model: str = None, timeout: float = None) -> str:
        """
        Call GLM API with messages

        Args:
            messages: List of message dicts with role and content
            max_tokens: Maximum tokens in response
            model: Model to use (defaults to glm-4-flash - free model)
            timeout: Request timeout in seconds (defaults to config value)

        Returns:
            Response content string
        """
        # Use config timeout if not specified
        api_timeout = timeout or DEFAULT_CONFIG["glm_api_timeout"]

        payload = {
            "model": model or "glm-4-flash",  # Use latest free model
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.7
        }

        async with httpx.AsyncClient(timeout=float(api_timeout)) as client:
            response = await client.post(
                self.api_url,
                headers=self._get_headers(),
                json=payload
            )
            response.raise_for_status()
            data = response.json()

            return data["choices"][0]["message"]["content"]

    async def score_news_importance(self, news_list: List[News]) -> Dict[int, float]:
        """
        Score news articles for importance using GLM

        Args:
            news_list: List of News objects to score

        Returns:
            Dict mapping news ID to importance score (0-1)
        """
        if not news_list:
            return {}

        # Prepare news summaries for scoring
        news_texts = []
        for i, news in enumerate(news_list):
            news_texts.append(f"{i+1}. {news.title}")

        prompt = f"""You are an AI news analyst. Rate the importance of each news article below on a scale of 0 to 1.
Consider factors like:
- Breakthrough or significant advancement in AI
- Impact on industry or society
- Relevance to current AI trends
- Credibility of the source

News articles:
{chr(10).join(news_texts)}

Respond with ONLY a JSON object mapping article numbers to scores, like:
{{"1": 0.85, "2": 0.72, "3": 0.45}}

Be strict - only truly important news should score above 0.7."""

        messages = [
            {"role": "system", "content": "You are an AI news importance scorer. Respond only with valid JSON."},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await self._call_api(messages, max_tokens=512)
            # Parse JSON response
            scores_raw = json.loads(response.strip())

            # Map back to news IDs
            scores = {}
            for i, news in enumerate(news_list):
                score_key = str(i + 1)
                if score_key in scores_raw:
                    scores[news.id] = float(scores_raw[score_key])

            return scores

        except Exception as e:
            # Return default scores on error
            return {news.id: 0.5 for news in news_list}

    async def generate_summary(self, content: str, max_length: int = 200) -> str:
        """
        Generate a summary of news content

        Args:
            content: Full news content
            max_length: Maximum summary length in characters

        Returns:
            Summary string
        """
        prompt = f"""Summarize the following news article in {max_length} characters or less.
Focus on the key points and main takeaway.

Article:
{content[:2000]}

Summary:"""

        messages = [
            {"role": "system", "content": "You are a concise news summarizer."},
            {"role": "user", "content": prompt}
        ]

        try:
            return await self._call_api(messages, max_tokens=256)
        except Exception as e:
            return content[:max_length] + "..." if len(content) > max_length else content

    async def translate_title(self, title: str) -> str:
        """
        Translate English news title to Chinese

        Args:
            title: English news title

        Returns:
            Chinese translated title
        """
        prompt = f"""将以下英文新闻标题翻译成简洁的中文，保持新闻标题风格，不要添加额外内容：

{title}

只输出翻译结果，不要其他内容。"""

        messages = [
            {"role": "system", "content": "你是一位专业的新闻翻译。"},
            {"role": "user", "content": prompt}
        ]

        try:
            result = await self._call_api(messages, max_tokens=128)
            return result.strip()
        except Exception as e:
            return title  # Return original on error

    async def translate_titles_batch(self, titles: List[str]) -> List[str]:
        """
        Translate multiple English titles to Chinese in one API call

        Args:
            titles: List of English titles

        Returns:
            List of Chinese translated titles
        """
        if not titles:
            return []

        titles_text = "\n".join([f"{i+1}. {t}" for i, t in enumerate(titles)])

        prompt = f"""将以下英文新闻标题翻译成简洁的中文，保持新闻标题风格。

翻译要求：
1. 保留专有名词的英文原文（如：GPT-4、Claude、OpenAI、Anthropic、LLaMA等）
2. 技术术语使用通用中文翻译（如：AI、机器学习、深度学习等）
3. 保持标题简洁有力，符合中文新闻标题习惯
4. 不要添加任何解释或注释

{titles_text}

输出格式（JSON数组）：
["翻译1", "翻译2", ...]

只输出JSON数组，不要其他内容。"""

        messages = [
            {"role": "system", "content": "你是一位专业的科技新闻翻译，擅长AI领域内容。只输出JSON数组。"},
            {"role": "user", "content": prompt}
        ]

        try:
            logger.info(f"[Translation] Translating {len(titles)} titles...")
            logger.debug(f"[Translation] Request: {json.dumps(messages, ensure_ascii=False)[:200]}...")

            response = await self._call_api(messages, max_tokens=1024)
            logger.debug(f"[Translation] Raw response: {response[:200]}...")

            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            translated = json.loads(response)

            # 验证结果
            if len(translated) != len(titles):
                logger.warning(f"[Translation] Length mismatch: {len(translated)} != {len(titles)}")

            # 输出对比
            for i, (orig, trans) in enumerate(zip(titles, translated)):
                if trans != orig:
                    logger.info(f"[Translation] ✓ {orig[:50]} → {trans}")
                else:
                    logger.warning(f"[Translation] ✗ Unchanged: {orig[:50]}")

            logger.info(f"成功翻译 {len(translated)}/{len(titles)} 个标题")
            return translated

        except json.JSONDecodeError as e:
            logger.error(f"[Translation] JSON parse error: {e}")
            logger.error(f"[Translation] Response was: {response[:500]}")
            logger.warning("标题翻译失败: JSON解析错误")
            return titles
        except httpx.TimeoutException as e:
            logger.error(f"[Translation] Timeout: {e}")
            logger.warning("标题翻译失败: 超时")
            return titles
        except httpx.HTTPStatusError as e:
            logger.error(f"[Translation] HTTP {e.response.status_code}: {e.response.text[:200]}")
            logger.warning(f"标题翻译失败: HTTP {e.response.status_code}")
            return titles
        except Exception as e:
            logger.error(f"[Translation] Unexpected error: {type(e).__name__}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            logger.warning(f"标题翻译失败: {e}")
            return titles  # Return originals on error

    async def translate_titles_with_context(
        self,
        news_items: List[Dict[str, str]]
    ) -> List[str]:
        """
        Translate titles with article context for better understanding

        Args:
            news_items: List of dicts with 'title' and 'content' keys

        Returns:
            List of Chinese translated titles
        """
        if not news_items:
            return []

        # 构建提示词
        news_text = []
        for i, item in enumerate(news_items):
            title = item.get("title", "")
            content = item.get("content", "")[:800]  # 增加内容长度以获得更好的理解
            news_text.append(f"新闻{i+1}:\n原标题: {title}\n文章内容: {content}\n")

        prompt = f"""你是一位顶级科技媒体的资深编辑，擅长撰写吸引眼球的AI新闻标题。

你的任务是为以下AI新闻创作高质量的中文标题。

## 标题创作原则

1. **理解核心价值**: 深入阅读文章内容，找出最有新闻价值的点
2. **提炼关键信息**: 突出"谁做了什么"、"有什么突破"、"带来什么影响"
3. **吸引读者兴趣**: 使用有冲击力的动词和表达，让读者想点击阅读
4. **符合中文习惯**: 使用地道的中文表达，避免翻译腔

## 标题风格要求

- 长度: 15-30个字符
- 保留英文专有名词: GPT-4、Claude、OpenAI、Anthropic、Google、Meta等
- 避免: "关于"、"浅谈"、"论"等学术化表达
- 推荐: 使用"发布"、"推出"、"突破"、"首次"、"重磅"等新闻动词
- 可以适当使用冒号分隔主副标题

## 优秀标题示例

- "OpenAI发布GPT-5：推理能力超越人类专家"
- "Claude 3.5登顶编程榜单：代码能力碾压GPT-4"
- "重磅！Google开源最强AI模型Gemma 2"
- "Meta发布Llama 3：开源模型首次挑战闭源巨头"

## 待处理新闻

{chr(10).join(news_text)}

## 输出要求

输出JSON数组，每个元素是对应新闻的中文标题:
["标题1", "标题2", ...]

只输出JSON数组，不要任何解释。"""

        messages = [
            {"role": "system", "content": "你是顶级科技媒体的资深编辑，专注AI领域，擅长撰写高质量新闻标题。只输出JSON数组。"},
            {"role": "user", "content": prompt}
        ]

        try:
            logger.info(f"[ContextTranslation] Translating {len(news_items)} titles with context...")

            response = await self._call_api(messages, max_tokens=2048)
            response = response.strip()

            # 清理markdown代码块
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            translated = json.loads(response)

            # 输出对比
            for i, (item, trans) in enumerate(zip(news_items, translated)):
                if trans != item['title']:
                    logger.info(f"[ContextTranslation] ✓ {item['title'][:40]} → {trans}")
                else:
                    logger.warning(f"[ContextTranslation] ✗ Unchanged: {item['title'][:40]}")

            logger.info(f"成功生成 {len(translated)}/{len(news_items)} 个中文标题")
            return translated

        except json.JSONDecodeError as e:
            logger.error(f"[ContextTranslation] JSON parse error: {e}")
            logger.error(f"[ContextTranslation] Response was: {response[:500]}")
            logger.warning("上下文翻译失败: JSON解析错误，降级到简单翻译")
            # 降级到简单翻译
            return await self.translate_titles_batch([item["title"] for item in news_items])
        except Exception as e:
            logger.error(f"[ContextTranslation] Error: {type(e).__name__}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            logger.warning(f"上下文翻译失败: {e}，降级到简单翻译")
            # 降级到简单翻译
            return await self.translate_titles_batch([item["title"] for item in news_items])

    async def generate_dialogue_script(
        self,
        news_list: List[News],
        language: str = "zh",
        host_female_name: Optional[str] = None,
        host_male_name: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """
        Generate a two-person dialogue script discussing the news

        Args:
            news_list: List of news articles to discuss
            language: Output language (zh, en, bilingual)
            host_female_name: Custom female host name (default: 小雅)
            host_male_name: Custom male host name (default: 小明)

        Returns:
            List of dialogue turns with speaker and text
        """
        # Use custom names or defaults
        female_name = host_female_name or "小雅"
        male_name = host_male_name or "小明"

        # Prepare news content - use refined content (news.content) with higher limit
        news_content = []
        for i, news in enumerate(news_list):
            # Prefer refined content, fallback to original_content, then summary
            content = news.content or news.original_content or news.summary or ""
            # Use up to 2000 chars per article for better dialogue quality
            content_preview = content[:2000] if content else ""
            news_content.append(f"新闻 {i+1}: {news.title}\n{content_preview}")
            # Debug logging
            logger.info(f"[Dialogue] News {i+1}: title={news.title[:50]}, content_status={news.content_status}, content_len={len(content)}")

        lang_instruction = {
            "zh": "用中文生成对话",
            "en": "Generate dialogue in English",
            "bilingual": "Generate dialogue mixing Chinese and English naturally"
        }.get(language, "用中文生成对话")

        prompt = f"""你是一位专业的播客脚本作家。请根据以下新闻内容，创作一段两人对话讨论。

主持人设定：
- {female_name}（女）：善于分析，提出有洞察力的问题
- {male_name}（男）：善于解释，分享观点和见解

{lang_instruction}

新闻内容：
{chr(10).join(news_content)}

要求：
1. 开场简短介绍今天要讨论的话题
2. 必须逐一讨论每篇新闻，确保每篇文章的核心内容都讲清楚
3. 每篇文章讨论时间根据内容复杂度灵活调整，简单的30秒，复杂的可以讨论3-5分钟
4. 深入讨论技术细节、行业影响、未来展望
5. 两人有来有往，自然对话，不要生硬
6. 结尾总结要点
7. 总共有{len(news_content)}篇文章，请确保每篇都有充分讨论

【重要】文本格式规范（用于语音合成）：
- 英文术语：保持原样如"GPT4"、"OpenAI"、"LLMs"，不要加空格或连字符
- 专有名词：不要在中间加空格，如"哈利波特"而不是"哈利 波特"
- 数字单位：紧贴不加空格，如"40%"、"100美元"、"2.5倍"
- 日期：写"2024年3月15日"，不要写"2024-03-15"
- 避免使用破折号（—）、省略号（...）等会造成停顿的符号
- 中英混合时不要加空格，如"这个AI模型"而不是"这个 AI 模型"

【对话风格要求】：
1. 口语化表达：
   - 使用口语化词汇，避免书面语
   - 适当使用语气词："嗯"、"哦"、"哇"、"诶"、"对对对"、"没错"
   - 使用停顿词："那个"、"就是说"、"其实"、"怎么说呢"
   - 使用反问句增加互动："是吧？"、"对不对？"、"你觉得呢？"
   - 示例：不要说"这项技术具有重要意义"，而说"这个技术真的挺重要的"

2. 句式结构：
   - 多用短句，避免超过30字的长句
   - 一个观点分多句表达，增加停顿和呼吸感
   - 两人对话要有来有往，不要一个人说太长
   - 示例：不要说"这个模型在多个任务上都取得了突破性进展"，而说"这个模型表现真的很好。在好几个任务上，都有突破性的进展。"

3. 情感表达：
   - 对有趣的内容表现出兴奋："哇，这个太酷了！"、"真的假的？"
   - 对复杂的内容表现出思考："嗯...这个确实挺复杂的"、"让我想想"
   - 对争议性内容表现出谨慎："这个可能还有待观察"、"不过也有人持不同意见"
   - 适当使用感叹句："太厉害了！"、"这也太快了吧！"

4. 对话节奏：
   - 开场要简短有力，不要冗长
   - 讨论每条新闻时，先简单概括，再深入展开
   - 两人要有真实的互动，不要像念稿子
   - 适当插入"嗯嗯"、"对"、"是的"等回应
   - 结尾要自然收尾，不要突然结束

【对话示例】：
错误示例（AI感重）：
{female_name}：今天我们来讨论一下最新的人工智能技术发展。
{male_name}：是的，这项技术在多个领域都取得了显著的进展。

正确示例（自然口语）：
{female_name}：诶，今天有个挺有意思的消息，关于AI的。
{male_name}：哦？说来听听，什么消息？
{female_name}：就是那个GPT4，又有新进展了。
{male_name}：哇，这也太快了吧！具体是什么进展？

输出格式（JSON数组）：
[
  {{"speaker": "{female_name}", "text": "..."}},
  {{"speaker": "{male_name}", "text": "..."}},
  ...
]

只输出JSON，不要其他内容。"""

        messages = [
            {"role": "system", "content": "You are a podcast script writer. Output valid JSON only."},
            {"role": "user", "content": prompt}
        ]

        try:
            # Retry logic for rate limiting
            max_retries = 3
            response = None
            last_error = None

            for attempt in range(max_retries):
                try:
                    response = await self._call_api(messages, max_tokens=8192)
                    break
                except Exception as e:
                    last_error = e
                    if '429' in str(e) and attempt < max_retries - 1:
                        logger.warning(f"[Dialogue] Rate limited, waiting 5s before retry {attempt + 2}/{max_retries}")
                        import asyncio
                        await asyncio.sleep(5)
                    else:
                        raise Exception(f"GLM API调用失败: {str(e) or type(e).__name__}")

            # Check if we got a response
            if response is None:
                raise Exception(f"GLM API调用失败，已重试{max_retries}次: {str(last_error) or '未知错误'}")

            # Clean response and parse JSON
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            dialogue = json.loads(response)
            logger.info(f"[Dialogue] Generated {len(dialogue)} turns")
            return dialogue

        except json.JSONDecodeError as e:
            logger.error(f"[Dialogue] JSON parse error: {e}")
            raise Exception(f"对话脚本解析失败: AI返回的格式不正确")
        except Exception as e:
            logger.error(f"[Dialogue] GLM error: {e}")
            error_msg = str(e) or "未知错误"
            if "对话脚本" in error_msg or "GLM" in error_msg:
                raise  # Already has user-friendly message
            raise Exception(f"对话脚本生成失败: {error_msg}")

    async def score_and_update_news(self, db: Session, news_list: List[News]) -> int:
        """
        Score news and update database

        Args:
            db: Database session
            news_list: List of news to score

        Returns:
            Number of news items updated
        """
        if not news_list:
            return 0

        # Get scores from GLM
        scores = await self.score_news_importance(news_list)

        # Update news records
        updated = 0
        for news in news_list:
            if news.id in scores:
                news.glm_score = scores[news.id]
                news.calculate_final_score()
                updated += 1

        db.commit()
        return updated


glm_service = GLMService()
