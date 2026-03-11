"""
Source configuration for priority-based fetching and quality scoring
"""

from typing import Dict, Optional
from enum import IntEnum


class SourceTier(IntEnum):
    """Source priority tiers (1=highest quality, 4=lowest)"""
    TIER1 = 1  # Official blogs, top research institutions
    TIER2 = 2  # Top tech media, academic sources
    TIER3 = 3  # Professional tech media, developer communities
    TIER4 = 4  # General news, community blogs


# Source authority scores (0-1)
SOURCE_AUTHORITY_SCORES = {
    # Tier 1: Official Blogs & Research Institutions (1.0)
    "OpenAI Blog": {"score": 1.0, "tier": SourceTier.TIER1},
    "OpenAI": {"score": 1.0, "tier": SourceTier.TIER1},
    "Anthropic News": {"score": 1.0, "tier": SourceTier.TIER1},
    "Anthropic": {"score": 1.0, "tier": SourceTier.TIER1},
    "DeepMind Blog": {"score": 1.0, "tier": SourceTier.TIER1},
    "Google DeepMind": {"score": 1.0, "tier": SourceTier.TIER1},
    "Google AI Blog": {"score": 1.0, "tier": SourceTier.TIER1},
    "Meta AI": {"score": 1.0, "tier": SourceTier.TIER1},
    "Meta AI Blog": {"score": 1.0, "tier": SourceTier.TIER1},
    "Microsoft Research": {"score": 1.0, "tier": SourceTier.TIER1},
    "Microsoft AI": {"score": 1.0, "tier": SourceTier.TIER1},

    # Tier 1: Top Academic Sources (0.95)
    "arXiv": {"score": 0.95, "tier": SourceTier.TIER1},
    "arXiv.org": {"score": 0.95, "tier": SourceTier.TIER1},
    "NeurIPS": {"score": 0.95, "tier": SourceTier.TIER1},
    "ICML": {"score": 0.95, "tier": SourceTier.TIER1},
    "ACL": {"score": 0.95, "tier": SourceTier.TIER1},
    "CVPR": {"score": 0.95, "tier": SourceTier.TIER1},
    "Nature AI": {"score": 0.95, "tier": SourceTier.TIER1},
    "Science Robotics": {"score": 0.95, "tier": SourceTier.TIER1},

    # Tier 2: Authority Tech Media (0.85)
    "MIT Technology Review": {"score": 0.85, "tier": SourceTier.TIER2},
    "Wired": {"score": 0.85, "tier": SourceTier.TIER2},
    "Wired AI": {"score": 0.85, "tier": SourceTier.TIER2},
    "VentureBeat": {"score": 0.85, "tier": SourceTier.TIER2},
    "VentureBeat AI": {"score": 0.85, "tier": SourceTier.TIER2},
    "The Verge": {"score": 0.85, "tier": SourceTier.TIER2},
    "The Verge AI": {"score": 0.85, "tier": SourceTier.TIER2},

    # Tier 3: Professional Tech Media (0.75)
    "TechCrunch": {"score": 0.75, "tier": SourceTier.TIER3},
    "Ars Technica": {"score": 0.75, "tier": SourceTier.TIER3},
    "ZDNet": {"score": 0.75, "tier": SourceTier.TIER3},
    "InfoQ": {"score": 0.75, "tier": SourceTier.TIER3},
    "InfoQ AI": {"score": 0.75, "tier": SourceTier.TIER3},

    # Tier 3: Developer Communities (0.70)
    "Hacker News": {"score": 0.70, "tier": SourceTier.TIER3},
    "Reddit": {"score": 0.70, "tier": SourceTier.TIER3},
    "Reddit r/MachineLearning": {"score": 0.70, "tier": SourceTier.TIER3},
    "GitHub": {"score": 0.70, "tier": SourceTier.TIER3},
    "GitHub Blog": {"score": 0.70, "tier": SourceTier.TIER3},

    # Tier 4: Professional Blogs (0.60)
    "Towards Data Science": {"score": 0.60, "tier": SourceTier.TIER4},
    "Medium": {"score": 0.60, "tier": SourceTier.TIER4},
    "Analytics Vidhya": {"score": 0.60, "tier": SourceTier.TIER4},
    "Machine Learning Mastery": {"score": 0.60, "tier": SourceTier.TIER4},

    # Default for unknown sources
    "Unknown": {"score": 0.50, "tier": SourceTier.TIER4}
}


# Fetch limits per tier (None = unlimited)
TIER_FETCH_LIMITS = {
    SourceTier.TIER1: None,  # No limit for top sources
    SourceTier.TIER2: 50,    # Max 50 articles per fetch
    SourceTier.TIER3: 20,    # Max 20 articles per fetch
    SourceTier.TIER4: 10     # Max 10 articles per fetch
}


# Time-based deduplication window (days)
DEDUPLICATION_WINDOW_DAYS = 7


# Quality score threshold for display
MIN_QUALITY_SCORE_HOMEPAGE = 0.75  # Homepage/recommendations
MIN_QUALITY_SCORE_LIST = 0.60      # List view
MIN_QUALITY_SCORE_SEARCH = 0.50    # Search results
MIN_QUALITY_SCORE_ARCHIVE = 0.15   # Archive (lowered to 0.15 to allow more articles through)


# Technical entity keywords for content depth scoring
TECHNICAL_ENTITIES = {
    # Model names
    "models": [
        "GPT-4", "GPT-3", "GPT-5", "GPT",
        "Claude", "Claude 3", "Claude Sonnet", "Claude Opus", "Claude Haiku",
        "LLaMA", "Llama", "Llama 2", "Llama 3",
        "Gemini", "Gemini Pro", "Gemini Ultra",
        "Mistral", "Mixtral",
        "BERT", "RoBERTa", "T5",
        "Stable Diffusion", "DALL-E", "Midjourney",
        "Whisper", "ChatGPT", "Bard", "Copilot"
    ],

    # Technical concepts
    "concepts": [
        "Transformer", "Attention", "Self-Attention",
        "RAG", "Retrieval-Augmented",
        "Fine-tuning", "RLHF", "RLAIF",
        "Prompt Engineering", "Chain-of-Thought", "CoT",
        "Few-shot", "Zero-shot", "In-context Learning",
        "Embeddings", "Vector Database",
        "Neural Network", "Deep Learning",
        "Reinforcement Learning", "Supervised Learning",
        "Diffusion Model", "GAN", "VAE",
        "Tokenization", "BPE", "SentencePiece"
    ],

    # Organizations
    "organizations": [
        "OpenAI", "Anthropic", "Google", "DeepMind",
        "Meta", "Microsoft", "Hugging Face",
        "Stability AI", "Cohere", "AI21 Labs"
    ],

    # Benchmarks
    "benchmarks": [
        "MMLU", "HumanEval", "GSM8K",
        "HellaSwag", "TruthfulQA", "MATH",
        "BigBench", "SuperGLUE", "SQuAD",
        "ImageNet", "COCO", "FID"
    ],

    # Programming
    "programming": [
        "Python", "PyTorch", "TensorFlow",
        "JAX", "Keras", "scikit-learn",
        "Jupyter", "Colab", "HuggingFace",
        "API", "SDK", "REST", "GraphQL"
    ]
}


def get_source_authority(source_name: str) -> Dict[str, any]:
    """
    Get source authority score and tier

    Args:
        source_name: Name of the news source

    Returns:
        Dict with 'score' and 'tier'
    """
    # Try exact match first
    if source_name in SOURCE_AUTHORITY_SCORES:
        return SOURCE_AUTHORITY_SCORES[source_name]

    # Try partial match (case-insensitive)
    source_lower = source_name.lower()
    for key, value in SOURCE_AUTHORITY_SCORES.items():
        if key.lower() in source_lower or source_lower in key.lower():
            return value

    # Default for unknown sources
    return SOURCE_AUTHORITY_SCORES["Unknown"]


def get_fetch_limit(tier: SourceTier) -> Optional[int]:
    """
    Get fetch limit for a source tier

    Args:
        tier: Source tier (1-4)

    Returns:
        Max number of articles to fetch (None = unlimited)
    """
    return TIER_FETCH_LIMITS.get(tier, 10)


def get_all_technical_entities() -> list:
    """Get all technical entity keywords as a flat list"""
    entities = []
    for category in TECHNICAL_ENTITIES.values():
        entities.extend(category)
    return entities
