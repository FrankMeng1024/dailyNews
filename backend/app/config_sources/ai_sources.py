"""
Verified AI Content Sources Configuration

Only includes official and authoritative sources to ensure content authenticity.
All sources are verified and trustworthy.
"""

# Verified AI content sources with RSS feeds
VERIFIED_AI_SOURCES = {
    # Official AI Company Blogs
    "openai": {
        "name": "OpenAI Blog",
        "rss_url": "https://openai.com/blog/rss.xml",
        "type": "blog",
        "verified": True,
        "description": "Official OpenAI blog with product updates and research"
    },
    "anthropic": {
        "name": "Anthropic News",
        "rss_url": "https://www.anthropic.com/news/rss",
        "type": "blog",
        "verified": True,
        "description": "Official Anthropic news and updates"
    },
    "google_ai": {
        "name": "Google AI Blog",
        "rss_url": "https://blog.google/technology/ai/rss/",
        "type": "blog",
        "verified": True,
        "description": "Google's official AI blog"
    },
    "deepmind": {
        "name": "DeepMind Blog",
        "rss_url": "https://deepmind.google/blog/rss.xml",
        "type": "blog",
        "verified": True,
        "description": "DeepMind research and updates"
    },
    "meta_ai": {
        "name": "Meta AI Blog",
        "rss_url": "https://ai.meta.com/blog/rss/",
        "type": "blog",
        "verified": True,
        "description": "Meta's AI research blog"
    },
    "cohere": {
        "name": "Cohere Blog",
        "rss_url": "https://cohere.com/blog/rss.xml",
        "type": "blog",
        "verified": True,
        "description": "Cohere AI blog and updates"
    },
    "huggingface": {
        "name": "Hugging Face Blog",
        "rss_url": "https://huggingface.co/blog/feed.xml",
        "type": "blog",
        "verified": True,
        "description": "Hugging Face blog and model updates"
    },
    "stability_ai": {
        "name": "Stability AI Blog",
        "rss_url": "https://stability.ai/blog/rss",
        "type": "blog",
        "verified": True,
        "description": "Stability AI news and research"
    },
    "mistral_ai": {
        "name": "Mistral AI Blog",
        "rss_url": "https://mistral.ai/news/rss",
        "type": "blog",
        "verified": True,
        "description": "Mistral AI updates and announcements"
    },

    # Tech Media - AI Sections
    "techcrunch_ai": {
        "name": "TechCrunch AI",
        "rss_url": "https://techcrunch.com/tag/artificial-intelligence/feed/",
        "type": "news",
        "verified": True,
        "description": "TechCrunch AI news coverage"
    },
    "theverge_ai": {
        "name": "The Verge AI",
        "rss_url": "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",
        "type": "news",
        "verified": True,
        "description": "The Verge AI news and analysis"
    },
    "mit_tech_review": {
        "name": "MIT Technology Review AI",
        "rss_url": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
        "type": "news",
        "verified": True,
        "description": "MIT Technology Review AI coverage"
    },
    "venturebeat_ai": {
        "name": "VentureBeat AI",
        "rss_url": "https://venturebeat.com/category/ai/feed/",
        "type": "news",
        "verified": True,
        "description": "VentureBeat AI news"
    },
    "arstechnica_ai": {
        "name": "Ars Technica AI",
        "rss_url": "https://arstechnica.com/tag/artificial-intelligence/feed/",
        "type": "news",
        "verified": True,
        "description": "Ars Technica AI coverage"
    },
    "wired_ai": {
        "name": "Wired AI",
        "rss_url": "https://www.wired.com/feed/tag/ai/latest/rss",
        "type": "news",
        "verified": True,
        "description": "Wired AI news and features"
    },
    "ieee_spectrum": {
        "name": "IEEE Spectrum AI",
        "rss_url": "https://spectrum.ieee.org/feeds/topic/artificial-intelligence",
        "type": "news",
        "verified": True,
        "description": "IEEE Spectrum AI technology news"
    },

    # Research and Academic
    "arxiv_ai": {
        "name": "arXiv AI Papers",
        "rss_url": "http://export.arxiv.org/rss/cs.AI",
        "type": "paper",
        "verified": True,
        "description": "Latest AI papers from arXiv"
    },
    "arxiv_ml": {
        "name": "arXiv Machine Learning",
        "rss_url": "http://export.arxiv.org/rss/cs.LG",
        "type": "paper",
        "verified": True,
        "description": "Latest ML papers from arXiv"
    },
    "paperswithcode": {
        "name": "Papers with Code",
        "rss_url": "https://paperswithcode.com/latest/rss",
        "type": "paper",
        "verified": True,
        "description": "Latest ML papers with code implementations"
    },
    "ai_alignment": {
        "name": "AI Alignment Forum",
        "rss_url": "https://www.alignmentforum.org/feed.xml",
        "type": "paper",
        "verified": True,
        "description": "AI safety and alignment research"
    },

    # Community (already implemented)
    "hackernews": {
        "name": "Hacker News",
        "type": "discussion",
        "verified": True,
        "description": "Hacker News AI discussions (API-based)"
    },
    "reddit_ml": {
        "name": "Reddit r/MachineLearning",
        "type": "discussion",
        "verified": True,
        "description": "Reddit ML community (API-based)"
    },
    "devto_ai": {
        "name": "Dev.to AI",
        "rss_url": "https://dev.to/feed/tag/ai",
        "type": "discussion",
        "verified": True,
        "description": "Dev.to AI community posts"
    },
    "medium_ai": {
        "name": "Medium AI",
        "rss_url": "https://medium.com/feed/tag/artificial-intelligence",
        "type": "discussion",
        "verified": True,
        "description": "Medium AI articles and discussions"
    }
}

# AI relevance keywords for content filtering
AI_KEYWORDS = [
    # Core AI terms
    "artificial intelligence", "ai", "machine learning", "ml", "deep learning",
    "neural network", "transformer", "llm", "large language model",

    # Major AI companies and products
    "openai", "chatgpt", "gpt", "gpt-4", "gpt-5",
    "anthropic", "claude",
    "google", "gemini", "bard", "deepmind", "alphago",
    "meta", "llama",
    "microsoft", "copilot",
    "midjourney", "stable diffusion", "dall-e",

    # AI technologies
    "generative ai", "genai", "diffusion model",
    "reinforcement learning", "rlhf", "fine-tuning",
    "prompt engineering", "rag", "retrieval augmented",
    "multimodal", "vision language model", "vlm",

    # AI applications
    "ai agent", "autonomous agent", "chatbot",
    "computer vision", "nlp", "natural language processing",
    "speech recognition", "text to speech", "tts",

    # Research terms
    "arxiv", "research paper", "ai research",
    "model training", "inference", "benchmark"
]

# Source type mapping
SOURCE_TYPE_MAP = {
    "blog": "blog",
    "news": "news",
    "paper": "paper",
    "discussion": "discussion",
    "podcast": "podcast",
    "video": "video"
}
