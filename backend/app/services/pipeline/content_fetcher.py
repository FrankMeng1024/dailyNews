"""
Content Fetcher - 内容抓取服务

抓取文章全文内容，处理 created 状态的新闻
支持多种抓取方法：API、专用选择器、newspaper4k、通用抓取
"""

import asyncio
import httpx
import logging
import re
from typing import Optional, List, Dict, Any
from bs4 import BeautifulSoup

from app.database import SessionLocal
from app.models.news import News
from .error_handler import ErrorHandler
from .state_machine import state_machine

logger = logging.getLogger(__name__)

# 最小内容长度
MIN_CONTENT_LENGTH = 200

# 质量评分阈值（低于此值标记为 skip）
MIN_QUALITY_THRESHOLD = 0.3

# 尝试导入来源配置
try:
    from app.config_sources.ai_sources import VERIFIED_AI_SOURCES
except ImportError:
    VERIFIED_AI_SOURCES = {}


class ContentFetcherService:
    """内容抓取服务 - 支持多种抓取方法"""

    def __init__(self):
        self.timeout = 30.0
        self._source_config_cache: Dict[str, Dict] = {}

    def _get_source_config(self, source_name: str) -> Dict[str, Any]:
        """根据来源名称获取配置"""
        if source_name in self._source_config_cache:
            return self._source_config_cache[source_name]

        # 遍历配置查找匹配的来源
        for source_id, config in VERIFIED_AI_SOURCES.items():
            if config.get("name") == source_name:
                self._source_config_cache[source_name] = config
                return config

        # 未找到，返回默认配置
        return {"fetch_method": "generic"}

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    # ==================== 主入口 ====================

    @ErrorHandler.handle("fetching")
    async def fetch(self, news_id: int):
        """抓取文章全文"""
        db = SessionLocal()
        try:
            news = db.query(News).filter(News.id == news_id).first()
            if not news:
                logger.warning(f"News {news_id} not found")
                return

            # 更新状态为 fetching
            news.processing_status = 'fetching'
            db.commit()

            # 检查是否为 rss_content 类型（RSS 已包含完整内容）
            source_config = self._get_source_config(news.source_name) if news.source_name else {}
            fetch_method = source_config.get("fetch_method", "generic")

            content = None
            if fetch_method == "rss_content" and news.summary and len(news.summary) >= MIN_CONTENT_LENGTH:
                # RSS 已有完整内容，直接使用
                content = news.summary
                logger.info(f"Using RSS content for {news_id}: {len(content)} chars")
            else:
                # 根据来源选择抓取方法
                content = await self._scrape_content(news.source_url, news.source_name)

            # 规则验证内容
            if content and self._validate_content(news.title, content):
                news.original_content = content
                score = self._calculate_quality_score(news, content)
                news.quality_score = score

                if score < MIN_QUALITY_THRESHOLD:
                    news.visibility_status = 'skip'
                    news.processing_status = 'complete'
                    db.commit()
                    logger.info(f"News {news_id} skipped: quality score {score:.2f}")
                    return

                news.processing_status = 'verifying'
                db.commit()
                logger.info(f"News {news_id} fetched: {len(content)} chars, score {score:.2f}")
                await state_machine.enqueue(news_id)
                return

            # 规则验证失败 → AI 验证
            if content and len(content) >= 100:
                from .glm_client import glm_client
                result = await glm_client.verify_content_validity(news.title, content)
                if result.get("is_valid"):
                    news.original_content = content
                    news.quality_score = 0.5
                    news.processing_status = 'verifying'
                    db.commit()
                    logger.info(f"News {news_id} passed AI validation: {len(content)} chars")
                    await state_machine.enqueue(news_id)
                    return

            # AI 也判断无效 → 标记失败
            raise Exception(f"Content invalid for {news.source_url}")

        finally:
            db.close()

    # ==================== 主路由 ====================

    async def _scrape_content(self, url: str, source_name: str = None) -> Optional[str]:
        """根据来源选择最佳抓取方法"""
        if not url:
            return None

        # HN 讨论页 - 抓取热门评论
        if url.startswith("https://news.ycombinator.com"):
            return await self._fetch_hn_comments(url)

        # 获取来源配置
        source_config = self._get_source_config(source_name) if source_name else {}
        fetch_method = source_config.get("fetch_method", "generic")

        logger.info(f"Fetching {url[:50]}... method={fetch_method}")

        # 路由到对应方法
        if fetch_method == "arxiv_api":
            return await self._fetch_via_arxiv_api(url)

        elif fetch_method == "rss_content":
            # RSS 已有完整内容，应该在 fetch() 方法中从 summary 获取
            # 这里作为备用（旧数据 summary 被截断的情况），尝试抓取
            content = await self._fetch_via_newspaper(url)
            if content and len(content) >= MIN_CONTENT_LENGTH:
                return content
            # 最后尝试 Jina Reader
            return await self._fetch_via_jina_reader(url)

        elif fetch_method == "custom_selector":
            selectors = source_config.get("selectors", [])
            content = await self._fetch_with_selectors(url, selectors)
            if content and len(content) >= MIN_CONTENT_LENGTH:
                return content
            # 降级到 newspaper4k
            content = await self._fetch_via_newspaper(url)
            if content and len(content) >= MIN_CONTENT_LENGTH:
                return content
            # 最后尝试 Jina Reader
            return await self._fetch_via_jina_reader(url)

        # HN/Reddit 等来源，如果 URL 是外部链接，走 generic 路径
        if fetch_method == "api":
            if 'news.ycombinator.com' in url or 'reddit.com' in url:
                return None
            # 外部链接走 generic 路径
            fetch_method = "generic"

        if fetch_method == "generic":  # generic
            # GitHub 特殊处理
            if 'github.com' in url:
                content = await self._scrape_github(url)
                if content:
                    return content

            # arXiv 特殊处理（即使没有配置也尝试 API）
            if 'arxiv.org' in url:
                content = await self._fetch_via_arxiv_api(url)
                if content:
                    return content

            # 先尝试 newspaper4k
            content = await self._fetch_via_newspaper(url)
            if content and len(content) >= MIN_CONTENT_LENGTH:
                return content

            # 降级到通用选择器
            content = await self._fetch_generic(url)
            if content and len(content) >= MIN_CONTENT_LENGTH:
                return content

            # 最后尝试 Jina Reader（绑过 403 等问题）
            return await self._fetch_via_jina_reader(url)

    # ==================== arXiv API ====================

    def _extract_arxiv_id(self, url: str) -> Optional[str]:
        """从 URL 提取 arXiv paper ID"""
        match = re.search(r'arxiv.org/(?:abs|pdf)/([0-9.]+)', url)
        return match.group(1) if match else None

    async def _fetch_via_arxiv_api(self, url: str, full_text: bool = True) -> Optional[str]:
        """通过 arXiv 获取论文内容

        Args:
            url: arXiv 论文 URL
            full_text: 是否获取全文（通过 Jina Reader 解析 PDF）
        """
        paper_id = self._extract_arxiv_id(url)
        if not paper_id:
            logger.warning(f"Cannot extract arXiv ID from {url}")
            return None

        # 优先尝试获取 PDF 全文（通过 Jina Reader）
        if full_text:
            pdf_url = f"https://arxiv.org/pdf/{paper_id}"
            content = await self._fetch_via_jina_reader(pdf_url, is_paper=True)
            if content and len(content) >= MIN_CONTENT_LENGTH:
                logger.info(f"arXiv PDF full text success: {paper_id}, {len(content)} chars")
                return content

        # PDF 全文获取失败，降级到 API 获取摘要
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._fetch_arxiv_sync, paper_id)
            if result:
                logger.info(f"arXiv API (abstract only): {paper_id}, {len(result)} chars")
                return result
        except Exception as e:
            logger.warning(f"arXiv API error for {paper_id}: {e}")

        # 最后尝试 Jina Reader 获取 abs 页面
        logger.info(f"arXiv API failed, trying Jina Reader for abs page")
        return await self._fetch_via_jina_reader(url, is_paper=True)

    def _fetch_arxiv_sync(self, paper_id: str) -> Optional[str]:
        """同步获取 arXiv 论文（仅摘要）"""
        try:
            import arxiv
            search = arxiv.Search(id_list=[paper_id])
            for result in search.results():
                parts = [
                    f"Title: {result.title}",
                    f"Authors: {', '.join(str(a) for a in result.authors)}",
                    f"\n{result.summary}",
                    f"\nCategories: {', '.join(result.categories)}",
                    f"\n\n---\n[注：以上为论文摘要，完整全文请访问 https://arxiv.org/pdf/{paper_id}]"
                ]
                return '\n'.join(parts)
        except ImportError:
            logger.warning("arxiv library not installed")
        except Exception as e:
            logger.warning(f"arXiv sync fetch error: {e}")
        return None

    # ==================== 内容清洗 ====================

    def _clean_jina_content(self, content: str) -> str:
        """清洗 Jina Reader 返回的内容，移除冗余元数据"""
        if not content:
            return content

        lines = content.split('\n')
        cleaned_lines = []

        # 需要跳过的元数据模式（整行匹配，无论位置）
        skip_patterns = [
            # Jina Reader 标准元数据
            r'^Title:\s*.+',
            r'^URL Source:\s*.+',
            r'^Published Time:\s*.+',
            r'^Number of Pages:\s*.+',
            r'^Markdown Content:\s*$',
            r'^Warning:\s*.+',
            r'^Source:\s*.+',
            r'^Author:\s*.+',
            r'^Date:\s*.+',
            r'^Image \d+:.*',
            r'^\[Image \d+\].*',
            r'^Language:\s*.+',
            r'^Word Count:\s*.+',
            # AI Alignment Forum / LessWrong 特有元数据
            r'^Crossposted from.*',
            r'^This is a linkpost for.*',
            r'^Originally posted on.*',
            r'^\d+ min read$',
            r'^\d+ comments$',
            r'^Posted on \w+ \d+.*',
            r'^by \[.*\]\(.*\)$',
            # arXiv 特有元数据
            r'^arXiv:\d+\.\d+.*',
            r'^\[Submitted on.*\]$',
            r'^Subjects?:\s*.+',
            r'^Comments?:\s*\d+\s*pages?.*',
            r'^MSC classes?:\s*.+',
            r'^ACM classes?:\s*.+',
            r'^DOI:\s*.+',
            r'^Journal-ref:\s*.+',
            r'^Report-no:\s*.+',
            r'^License:\s*.+',
            # 通用社交/分享元数据
            r'^Share this.*',
            r'^Follow us.*',
            r'^Subscribe.*newsletter.*',
            r'^Tags?:\s*.+',
            r'^Categories?:\s*.+',
            r'^Related (posts?|articles?).*',
            # 新增：更多干扰模式
            r'^Reading Time:\s*.+',
            r'^Last Updated:\s*.+',
            r'^Views:\s*\d+',
            r'^Likes:\s*\d+',
            r'^\d+ (views|likes|shares)$',
            r'^(Share|Tweet|Pin|Email)\s*$',
            r'^\[Read more\].*',
            r'^Advertisement$',
            r'^Sponsored$',
            r'^ADVERTISEMENT$',
        ]

        for line in lines:
            stripped = line.strip()

            # 跳过匹配的元数据行
            if any(re.match(p, stripped, re.I) for p in skip_patterns):
                continue

            cleaned_lines.append(line)

        result = '\n'.join(cleaned_lines)

        # 移除开头的空行
        result = result.lstrip('\n')

        # 移除 "📋 摘要 / Abstract" 等标签（整行匹配）
        result = re.sub(r'^📋\s*(摘要|Abstract)\s*[/\|]?\s*(摘要|Abstract)?\s*$\n*', '', result, flags=re.I | re.MULTILINE)

        # 移除 Markdown 图片 ![alt](url)
        result = re.sub(r'!\[.*?\]\([^)]+\)', '', result)

        # 移除作者邮箱（各种格式）
        result = re.sub(r'\[[\w.-]+@[\w.-]+\.(edu|com|org|net|cn)\]', '', result)
        result = re.sub(r'[\w.-]+@[\w.-]+\.(edu|com|org|net|cn)', '', result)

        # 移除连续多个空行
        result = re.sub(r'\n{3,}', '\n\n', result)

        # 进一步清洗网站导航和页脚
        result = self._remove_navigation_and_footer(result)

        # 移除重复段落
        result = self._remove_duplicate_paragraphs(result)

        # 最终清理
        result = self._final_cleanup(result)

        return result.strip()

    def _final_cleanup(self, content: str) -> str:
        """最终清理：移除残留的无用内容"""
        if not content:
            return content

        # 移除空链接 [](url) 或 [](https://...)
        content = re.sub(r'\[\]\([^)]+\)\s*', '', content)

        # 移除只有分隔符的行
        content = re.sub(r'^[=\-_]{3,}\s*$', '', content, flags=re.MULTILINE)

        # 移除末尾的页脚版权信息（只匹配最后几行）
        lines = content.split('\n')
        # 从后往前找，移除页脚行
        while lines:
            last_line = lines[-1].strip()
            if not last_line:
                lines.pop()
                continue
            # 检查是否是页脚内容
            if any(x in last_line.lower() for x in ['©', 'copyright', 'manage cookies', 'english united states', 'all rights reserved']):
                lines.pop()
                continue
            # 检查是否是短的导航/链接行
            if len(last_line) < 50 and re.match(r'^[\[\*\-]', last_line):
                lines.pop()
                continue
            break

        content = '\n'.join(lines)

        # 移除开头的标题重复（如果标题和第一行内容相同）
        lines = content.split('\n')
        if len(lines) >= 2:
            first_line = lines[0].strip()
            # 检查是否是 "Title | Site" 格式，且后面有实际内容
            if '|' in first_line and len(lines) > 5:
                # 保留标题，但移除分隔线
                if lines[1].strip() in ['', '===============', '---']:
                    lines = [lines[0]] + lines[2:]
                    content = '\n'.join(lines)

        # 移除连续空行
        content = re.sub(r'\n{3,}', '\n\n', content)

        return content.strip()

    def _remove_navigation_and_footer(self, content: str) -> str:
        """移除网站导航菜单和页脚内容"""
        if not content:
            return content

        lines = content.split('\n')
        cleaned_lines = []

        # 导航/页脚特征模式
        nav_patterns = [
            # 通用导航链接
            r'^\*\s*\[.+\]\(.+\)\s*$',  # * [Link](url) 格式的导航
            r'^\[.+\]\(.+\)$',  # 单独的 [Link](url)
            r'^(Skip to|Jump to|Go to)\s+(main\s+)?content',
            r'^(Back to|Return to)\s+',
            r'^(Log\s*in|Sign\s*in|Sign\s*up|Register)\s*$',
            r'^(Menu|Navigation|Nav)\s*$',
            # OpenAI 特有
            r'^Switch to\s*$',
            r'^\*\s*(Research|Safety|For Business|For Developers|ChatGPT|Sora|Codex|Stories|Company|News)\s*$',
            r'^(Research|Safety|Products?|Company|About|News|Blog|Careers?|Contact)\s*$',
            r'^Latest Advancements\s*$',
            r'^Back to main menu\s*$',
            # Google 特有
            r'^\*\s*(Google Products|About the Keyword|Help)\s*$',
            # 页脚特征
            r'^©\s*\d{4}',
            r'^\d{4}\s*©',
            r'^(Privacy|Terms|Cookie|Legal)',
            r'^(All rights reserved|Copyright)',
            r'^(Follow us|Connect with us)',
            r'^\[(opens in a new window)\]',
            r'^Manage Cookies\s*$',
            r'^English\s+(United States|UK|US)\s*$',
            # 社交媒体
            r'^\*?\s*\[(Twitter|Facebook|LinkedIn|Instagram|YouTube|TikTok|Discord)\]',
            r'^(Twitter|Facebook|LinkedIn|Instagram|YouTube|TikTok|Discord)\s*$',
        ]

        # 检测导航区域的开始和结束
        in_nav_section = False
        nav_link_count = 0
        content_started = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 空行处理
            if not stripped:
                if content_started:
                    cleaned_lines.append(line)
                continue

            # 检查是否是导航模式
            is_nav = any(re.match(p, stripped, re.I) for p in nav_patterns)

            # 检测连续的导航链接（超过3个连续的 * [xxx] 格式）
            if re.match(r'^\*\s*\[.+\]', stripped):
                nav_link_count += 1
                if nav_link_count >= 3:
                    in_nav_section = True
            else:
                nav_link_count = 0
                if in_nav_section and len(stripped) > 50:  # 长文本，可能是正文开始
                    in_nav_section = False

            # 跳过导航内容
            if is_nav or in_nav_section:
                continue

            # 检测正文开始（标题或长段落）
            if not content_started:
                # Markdown 标题或长文本段落
                if stripped.startswith('#') or len(stripped) > 100:
                    content_started = True
                # 短行但不是导航
                elif len(stripped) > 30 and not re.match(r'^\*\s*\[', stripped):
                    content_started = True

            if content_started:
                cleaned_lines.append(line)

        result = '\n'.join(cleaned_lines)

        # 移除页脚区域（从特定标记开始到结尾）
        footer_markers = [
            r'\n---\n.*?(©|Copyright|All rights reserved)',
            r'\n(Follow us|Connect with us|Stay connected).*$',
            r'\n\*\s*\[(Twitter|Facebook|LinkedIn).*$',
        ]
        for marker in footer_markers:
            result = re.sub(marker, '', result, flags=re.I | re.DOTALL)

        return result.strip()

    def _remove_duplicate_paragraphs(self, content: str) -> str:
        """移除重复的段落"""
        if not content:
            return content

        paragraphs = content.split('\n\n')
        seen = set()
        unique_paragraphs = []

        for para in paragraphs:
            # 标准化段落用于比较
            normalized = ' '.join(para.split()).lower()
            if len(normalized) < 50:  # 短段落不去重
                unique_paragraphs.append(para)
                continue

            # 检查是否重复（允许小差异）
            is_duplicate = False
            for seen_para in seen:
                # 如果相似度超过 80%，认为是重复
                if self._similarity(normalized, seen_para) > 0.8:
                    is_duplicate = True
                    break

            if not is_duplicate:
                seen.add(normalized)
                unique_paragraphs.append(para)

        return '\n\n'.join(unique_paragraphs)

    def _similarity(self, s1: str, s2: str) -> float:
        """计算两个字符串的相似度"""
        if not s1 or not s2:
            return 0.0

        # 简单的 Jaccard 相似度
        words1 = set(s1.split())
        words2 = set(s2.split())

        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    def _clean_paper_content(self, content: str) -> str:
        """清洗论文内容，移除作者信息块，只保留标题和正文"""
        if not content:
            return content

        # 先进行基础清洗
        content = self._clean_jina_content(content)

        lines = content.split('\n')
        result_lines = []
        title_line = None
        found_abstract = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 保存标题行（第一个 # 开头的行，且不是 Abstract/摘要）
            if title_line is None and stripped.startswith('#'):
                if not re.match(r'^#\s*(Abstract|摘要)', stripped, re.I):
                    title_line = line
                    continue

            # 检测到 Abstract 或 摘要，标记并开始保留内容
            if re.match(r'^#*\s*(Abstract|摘要)\s*$', stripped, re.I):
                found_abstract = True
                # 不保留 "## Abstract" 这行标题，直接跳过
                continue

            # 在找到 Abstract 之前，跳过所有内容（作者、机构等）
            if not found_abstract:
                continue

            result_lines.append(line)

        # 如果有标题，添加到开头
        if title_line:
            result_lines.insert(0, title_line)
            result_lines.insert(1, '')

        # 清理结果中的多余空行
        result = '\n'.join(result_lines)
        result = re.sub(r'\n{3,}', '\n\n', result)

        return result.strip()

    def _smart_truncate(self, content: str, max_length: int = 30000) -> str:
        """智能截断，在章节边界处截断"""
        if len(content) <= max_length:
            return content

        # 在 max_length 附近找章节标题
        truncated = content[:max_length]

        # 尝试在章节标题前截断（在最后 2000 字符内找）
        section_patterns = [
            r'\n#{1,3}\s+\d+[\.\s]',  # ## 4. xxx
            r'\n\d+\.\d+\s+',          # 4.2 xxx
            r'\n\*\*\d+[\.\s]',        # **4. xxx**
        ]

        best_pos = max_length
        search_region = truncated[-2000:] if len(truncated) > 2000 else truncated

        for pattern in section_patterns:
            matches = list(re.finditer(pattern, search_region))
            if matches:
                last_match = matches[-1]
                pos = max_length - len(search_region) + last_match.start()
                if pos > max_length * 0.8:  # 至少保留 80%
                    best_pos = pos
                    break

        result = content[:best_pos].rstrip()
        result += '\n\n---\n[内容过长，已截断。完整内容请访问原文链接]'
        return result

    # ==================== Jina Reader API ====================

    async def _fetch_via_jina_reader(self, url: str, is_paper: bool = False) -> Optional[str]:
        """使用 Jina Reader API 提取内容（绕过 Cloudflare 等反爬虫）

        Args:
            url: 要抓取的 URL
            is_paper: 是否为论文（使用论文专用清洗）
        """
        jina_url = f"https://r.jina.ai/{url}"
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(jina_url, headers={
                    "Accept": "text/plain"
                })
                # 记录非 200 状态码
                if resp.status_code != 200:
                    if resp.status_code == 429:
                        logger.warning(f"Jina Reader rate limited (429): {url[:60]}")
                    else:
                        logger.warning(f"Jina Reader HTTP {resp.status_code}: {url[:60]}")
                    return None

                content = resp.text.strip()
                # 清洗元数据
                content = self._clean_jina_content(content)
                # 论文使用专用清洗
                if is_paper:
                    content = self._clean_paper_content(content)
                if len(content) >= MIN_CONTENT_LENGTH:
                    # 截断过长内容
                    content = self._smart_truncate(content, 30000)
                    logger.info(f"Jina Reader success: {len(content)} chars")
                    return content
        except Exception as e:
            logger.warning(f"Jina Reader error: {e}")
        return None

    # ==================== newspaper4k ====================

    async def _fetch_via_newspaper(self, url: str) -> Optional[str]:
        """使用 newspaper4k 提取文章"""
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._newspaper_extract, url)
            if result:
                logger.info(f"Newspaper4k success: {len(result)} chars")
            return result
        except Exception as e:
            logger.warning(f"Newspaper4k error: {e}")
            return None

    def _newspaper_extract(self, url: str) -> Optional[str]:
        """同步提取文章"""
        try:
            import newspaper
            article = newspaper.article(url)
            if article.text and len(article.text) >= MIN_CONTENT_LENGTH:
                # 直接返回文章正文，不添加 Title/Authors 前缀
                # 这些信息已在 UI 中展示
                return article.text
        except ImportError:
            logger.warning("newspaper4k library not installed")
        except Exception as e:
            logger.debug(f"Newspaper extract error: {e}")
        return None

    # ==================== 专用选择器 ====================

    async def _fetch_with_selectors(self, url: str, selectors: List[str]) -> Optional[str]:
        """使用专用选择器抓取"""
        if not selectors:
            return None

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                resp = await client.get(url, headers=self._get_headers())
                if resp.status_code != 200:
                    return None

                soup = BeautifulSoup(resp.text, 'html.parser')
                self._remove_noise(soup)

                # 按优先级尝试选择器
                for selector in selectors:
                    element = soup.select_one(selector)
                    if element:
                        content = self._extract_text(element)
                        if content and len(content) >= MIN_CONTENT_LENGTH:
                            logger.info(f"Selector '{selector}' matched: {len(content)} chars")
                            return content

                return None
        except Exception as e:
            logger.warning(f"Selector fetch error: {e}")
            return None

    # ==================== 通用抓取 ====================

    async def _fetch_generic(self, url: str) -> Optional[str]:
        """通用网页抓取"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                resp = await client.get(url, headers=self._get_headers())
                if resp.status_code != 200:
                    return None

                soup = BeautifulSoup(resp.text, 'html.parser')
                self._remove_noise(soup)

                # 尝试多种选择器
                content = None
                selectors = [
                    'article', '[role="main"]', '.article-content', '.post-content',
                    '.entry-content', 'main', '#content', '.prose', '.markdown-body'
                ]

                for selector in selectors:
                    element = soup.select_one(selector)
                    if element:
                        content = self._extract_text(element)
                        if content and len(content) >= MIN_CONTENT_LENGTH:
                            break
                        content = None

                # 备用：收集所有段落
                if not content:
                    paragraphs = soup.find_all('p')
                    texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30]
                    if texts:
                        content = '\n\n'.join(texts[:30])

                if content and len(content) >= MIN_CONTENT_LENGTH:
                    return content

                return None

        except Exception as e:
            logger.warning(f"Generic scrape error: {e}")
            return None

    # ==================== GitHub ====================

    async def _scrape_github(self, url: str) -> Optional[str]:
        """GitHub 页面特殊处理"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                # blob 页面转 raw
                if '/blob/' in url:
                    raw_url = url.replace('github.com', 'raw.githubusercontent.com').replace('/blob/', '/')
                    resp = await client.get(raw_url)
                    if resp.status_code == 200:
                        return resp.text

                # 仓库主页获取 README
                parts = url.rstrip('/').split('/')
                if len(parts) >= 5 and parts[2] == 'github.com':
                    user, repo = parts[3], parts[4]
                    for branch in ['main', 'master']:
                        readme_url = f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/README.md"
                        resp = await client.get(readme_url)
                        if resp.status_code == 200 and len(resp.text) > 100:
                            return resp.text

                return None

        except Exception as e:
            logger.warning(f"GitHub scrape error: {e}")
            return None

    # ==================== Hacker News 评论 ====================

    def _extract_hn_story_id(self, url: str) -> Optional[str]:
        """从 HN URL 提取 story ID"""
        match = re.search(r'item\?id=(\d+)', url)
        return match.group(1) if match else None

    async def _fetch_hn_comments(self, url: str) -> Optional[str]:
        """抓取 Hacker News 热门评论

        使用 HN Firebase API 获取评论数据
        """
        story_id = self._extract_hn_story_id(url)
        if not story_id:
            logger.warning(f"Cannot extract HN story ID from {url}")
            return None

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # 获取 story 信息
                story_url = f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                resp = await client.get(story_url)
                if resp.status_code != 200:
                    return None

                story = resp.json()
                if not story:
                    return None

                # 获取评论 ID 列表
                comment_ids = story.get('kids', [])[:10]  # 最多取前 10 条顶级评论
                if not comment_ids:
                    return f"## 讨论\n\n暂无评论"

                # 并发获取评论内容
                comments = []
                for cid in comment_ids[:5]:  # 只取前 5 条热门评论
                    comment = await self._fetch_hn_comment(client, cid, depth=0)
                    if comment:
                        comments.append(comment)

                if not comments:
                    return f"## 讨论\n\n暂无评论"

                # 格式化输出
                output = "## 热门讨论\n\n"
                for comment in comments:
                    output += comment + "\n\n"

                logger.info(f"HN comments fetched: {story_id}, {len(output)} chars")
                return output

        except Exception as e:
            logger.warning(f"HN comments fetch error: {e}")
            return None

    async def _fetch_hn_comment(self, client: httpx.AsyncClient, comment_id: int, depth: int = 0) -> Optional[str]:
        """递归获取单条评论及其回复"""
        if depth > 1:  # 最多 2 层回复
            return None

        try:
            url = f"https://hacker-news.firebaseio.com/v0/item/{comment_id}.json"
            resp = await client.get(url)
            if resp.status_code != 200:
                return None

            comment = resp.json()
            if not comment or comment.get('deleted') or comment.get('dead'):
                return None

            # 提取评论信息
            author = comment.get('by', '匿名')
            text = comment.get('text', '')
            time_ago = self._format_hn_time(comment.get('time', 0))

            # 清理 HTML
            text = self._clean_hn_html(text)
            if not text or len(text) < 10:
                return None

            # 格式化评论
            indent = ">" * depth + " " if depth > 0 else ""
            result = f"{indent}**{author}** · {time_ago}\n{indent}{text}"

            # 获取回复（最多 2 条）
            reply_ids = comment.get('kids', [])[:2]
            replies = []
            for rid in reply_ids:
                reply = await self._fetch_hn_comment(client, rid, depth + 1)
                if reply:
                    replies.append(reply)

            if replies:
                result += "\n\n" + "\n\n".join(replies)

            return result

        except Exception as e:
            logger.debug(f"HN comment fetch error: {e}")
            return None

    def _format_hn_time(self, timestamp: int) -> str:
        """格式化 HN 时间戳为相对时间"""
        import time
        if not timestamp:
            return "未知时间"

        diff = int(time.time()) - timestamp
        if diff < 3600:
            return f"{diff // 60}分钟前"
        elif diff < 86400:
            return f"{diff // 3600}小时前"
        else:
            return f"{diff // 86400}天前"

    def _clean_hn_html(self, html: str) -> str:
        """清理 HN 评论中的 HTML 标签"""
        if not html:
            return ""

        # 简单的 HTML 清理
        import html as html_module
        text = html_module.unescape(html)
        text = re.sub(r'<p>', '\n\n', text)
        text = re.sub(r'<br\s*/?>', '\n', text)
        text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', r'[\2](\1)', text)
        text = re.sub(r'<code>([^<]*)</code>', r'`\1`', text)
        text = re.sub(r'<pre>([^<]*)</pre>', r'```\n\1\n```', text)
        text = re.sub(r'<i>([^<]*)</i>', r'*\1*', text)
        text = re.sub(r'<[^>]+>', '', text)  # 移除其他标签
        text = text.strip()
        return text

    # ==================== 辅助方法 ====================

    def _remove_noise(self, soup: BeautifulSoup):
        """移除无用元素"""
        for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer',
                                  'aside', 'iframe', 'noscript', 'form', 'button',
                                  '.sidebar', '.comments', '.advertisement', '.ad']):
            if hasattr(tag, 'decompose'):
                tag.decompose()

    def _extract_text(self, element) -> Optional[str]:
        """从元素提取文本"""
        texts = []
        for p in element.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'li']):
            text = p.get_text(strip=True)
            if len(text) > 30:
                texts.append(text)

        if texts:
            return '\n\n'.join(texts)
        return None

    # ==================== 内容验证 ====================

    def _validate_content(self, title: str, content: str) -> bool:
        """验证内容有效性（不使用 AI）"""
        if not content or len(content) < MIN_CONTENT_LENGTH:
            return False

        content_lower = content.lower()

        # 0. 检测 Jina Reader 返回的错误页面
        jina_error_patterns = [
            'vercel security checkpoint',
            'target url returned error',
            'error 429',
            'too many requests',
            'access denied by website',
            'cloudflare',
            'please enable javascript',
            'checking your browser',
            'just a moment',
            'ray id:',
            'please wait while we verify',
        ]
        if sum(1 for p in jina_error_patterns if p in content_lower) >= 2:
            logger.debug("Jina Reader error page detected")
            return False

        # 1. 标题关键词检查（去除标点符号）
        import string
        title_clean = title.translate(str.maketrans('', '', string.punctuation))
        title_words = set(w.lower() for w in title_clean.split() if len(w) > 3)
        if title_words:
            match_count = sum(1 for w in title_words if w in content_lower)
            if match_count < len(title_words) * 0.15:  # 至少 15% 匹配（放宽）
                logger.debug(f"Title keyword mismatch: {match_count}/{len(title_words)}")
                return False

        # 2. 内容多样性检查
        lines = [l.strip() for l in content.split('\n') if l.strip()]
        if len(lines) < 3:
            logger.debug("Content too few lines")
            return False

        # 3. 模板文字检测
        template_patterns = [
            'cookie', 'privacy policy', 'terms of service',
            'subscribe', 'newsletter', 'sign up', 'log in',
            'javascript', 'enable javascript', 'browser',
            'arXivLabs', 'arxiv is committed'  # arXiv 模板特征
        ]
        first_500 = content_lower[:500]
        template_count = sum(1 for p in template_patterns if p in first_500)
        if template_count >= 3:
            logger.debug(f"Template text detected: {template_count} patterns")
            return False

        # 4. 错误页面检测
        error_patterns = ['404', 'not found', 'page not found', 'forbidden',
                         'access denied', 'login required']
        if sum(1 for p in error_patterns if p in first_500) >= 2:
            logger.debug("Error page detected")
            return False

        return True

    def _calculate_quality_score(self, news: News, content: str) -> float:
        """计算质量评分 - 按内容类型差异化"""
        source_type = news.source_type or 'news'

        # 讨论类：基于社区指标
        if source_type == 'discussion':
            return self._score_discussion(news)

        # 论文类：基于来源和内容完整度
        if source_type == 'paper':
            return self._score_paper(news, content)

        # 博客/新闻：基于内容长度和来源
        return self._score_article(news, content)

    def _score_discussion(self, news: News) -> float:
        """讨论类评分 - 基于社区热度"""
        import re
        score = 0.5

        # 从 summary 解析 Score 和 Comments
        # 格式: "Score: 63 | Comments: 6"
        summary = news.summary or ''

        hn_score = 0
        comments = 0

        score_match = re.search(r'Score:\s*(\d+)', summary)
        if score_match:
            hn_score = int(score_match.group(1))

        comments_match = re.search(r'Comments:\s*(\d+)', summary)
        if comments_match:
            comments = int(comments_match.group(1))

        # HN score 加分 (最多 +0.3)
        if hn_score >= 50:
            score += 0.1
        if hn_score >= 100:
            score += 0.1
        if hn_score >= 200:
            score += 0.1

        # 评论数加分 (最多 +0.2)
        if comments >= 20:
            score += 0.1
        if comments >= 50:
            score += 0.1

        return min(1.0, score)

    def _score_paper(self, news: News, content: str) -> float:
        """论文类评分"""
        score = 0.6  # 论文基础分较高

        # 有全文内容加分
        if content and len(content) > 5000:
            score += 0.2
        elif content and len(content) > 1000:
            score += 0.1

        # arXiv 来源加分
        if 'arxiv' in (news.source_name or '').lower():
            score += 0.1

        return min(1.0, score)

    def _score_article(self, news: News, content: str) -> float:
        """文章类评分（博客/新闻）"""
        score = 0.5

        # 内容长度加分 (最多 +0.2，降低权重)
        if content and len(content) > 1000:
            score += 0.1
        if content and len(content) > 3000:
            score += 0.1

        # 来源权威加分 (+0.2)
        trusted_sources = ['openai', 'anthropic', 'google', 'microsoft', 'meta', 'deepmind']
        source_lower = (news.source_name or '').lower()
        if any(s in source_lower for s in trusted_sources):
            score += 0.2

        # 一级来源额外加分 (+0.1)
        tier1_sources = ['openai blog', 'anthropic', 'google ai blog', 'deepmind blog']
        if any(s in source_lower for s in tier1_sources):
            score += 0.1

        return min(1.0, score)


# 全局单例
content_fetcher = ContentFetcherService()
