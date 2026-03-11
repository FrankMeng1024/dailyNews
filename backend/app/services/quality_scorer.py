"""
Quality scoring service for news content evaluation

Implements multi-dimensional quality scoring based on:
- Source authority (40%)
- Content depth (25%)
- Timeliness (15%)
- AI relevance (10%)
- Technical credibility (10%)
"""

import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from app.models.news import News
from app.config_sources.source_config import (
    get_source_authority,
    get_all_technical_entities,
    MIN_QUALITY_SCORE_ARCHIVE
)


class QualityScorer:
    """Quality scoring service for news content"""

    def __init__(self):
        self.technical_entities = get_all_technical_entities()

    def score_source_authority(self, news: News) -> float:
        """
        Score source authority (0-1)

        Uses predefined source authority scores from source_config
        """
        source_info = get_source_authority(news.source_name)
        return source_info['score']

    def score_content_depth(self, news: News) -> float:
        """
        Score content depth (0-1)

        Factors:
        - Text length quality curve (30%)
        - Technical entity density (30%)
        - Structure completeness (20%)
        - Originality (20%)
        """
        # Get content for analysis
        content = news.original_content or news.content or news.summary or ""
        title = news.title or ""
        combined_text = f"{title} {content}"

        # 1. Length quality score (30%)
        length = len(content)
        news.content_length = length  # Store for future use

        if length < 200:
            length_score = 0.3  # Too short
        elif length < 500:
            length_score = 0.5  # Brief news
        elif length < 1500:
            length_score = 0.7  # Medium depth
        elif length < 5000:
            length_score = 0.9  # Deep article
        elif length < 10000:
            length_score = 1.0  # Long-form
        else:
            length_score = 0.8  # Too long, might be redundant

        # 2. Technical entity density (30%)
        entity_count = self._count_technical_entities(combined_text)
        news.entity_count = entity_count  # Store for future use

        # Calculate density (entities per 1000 chars)
        density = (entity_count / max(length, 100)) * 1000

        if density >= 5:
            density_score = 1.0  # High technical density
        elif density >= 2:
            density_score = 0.7  # Medium
        else:
            density_score = 0.4  # Low

        # 3. Structure completeness (20%)
        structure_score = self._score_structure_completeness(content, title)

        # 4. Originality (20%)
        # Check for signs of original content
        originality_score = 0.7  # Default
        if any(indicator in content.lower() for indicator in ['we announce', 'we release', 'we introduce', 'today we']):
            originality_score = 1.0  # Official announcement
        elif any(indicator in content.lower() for indicator in ['according to', 'reported by', 'via']):
            originality_score = 0.5  # Likely repost
        elif news.author and len(news.author) > 0:
            originality_score = 0.8  # Has clear authorship

        # Combine scores
        final_score = (
            length_score * 0.30 +
            density_score * 0.30 +
            structure_score * 0.20 +
            originality_score * 0.20
        )

        return round(final_score, 4)

    def _count_technical_entities(self, text: str) -> int:
        """Count occurrences of technical entities in text"""
        count = 0
        text_lower = text.lower()

        for entity in self.technical_entities:
            # Use word boundary for accurate matching
            pattern = r'\b' + re.escape(entity.lower()) + r'\b'
            matches = re.findall(pattern, text_lower)
            count += len(matches)

        return count

    def _score_structure_completeness(self, content: str, title: str) -> float:
        """
        Score content structure completeness (0-1)

        Checks for:
        - Clear problem statement
        - Technical details/results
        - Impact analysis
        - Code/formulas/data
        """
        score = 0.0
        content_lower = content.lower()

        # Problem statement indicators (+0.25)
        if any(word in content_lower for word in ['problem', 'challenge', 'issue', 'objective', 'goal']):
            score += 0.25

        # Technical details (+0.30)
        if any(word in content_lower for word in ['method', 'approach', 'architecture', 'algorithm', 'implementation', 'experiment', 'result', 'performance']):
            score += 0.30

        # Impact analysis (+0.25)
        if any(word in content_lower for word in ['impact', 'significance', 'implication', 'application', 'future', 'potential']):
            score += 0.25

        # Code/formulas/data indicators (+0.20)
        has_code_indicators = bool(re.search(r'```|<code>|def |class |function|import |github\.com', content, re.IGNORECASE))
        has_data_indicators = bool(re.search(r'\d+%|\d+x|accuracy|f1|score|benchmark', content, re.IGNORECASE))
        if has_code_indicators or has_data_indicators:
            score += 0.20

        return min(score, 1.0)

    def score_timeliness(self, news: News) -> float:
        """
        Score timeliness (0-1)

        Time decay curve with special adjustments for content type
        """
        if not news.published_at:
            return 0.5

        # Ensure timezone-aware comparison
        now = datetime.now(timezone.utc)
        published = news.published_at
        if not published.tzinfo:
            published = published.replace(tzinfo=timezone.utc)

        age_hours = (now - published).total_seconds() / 3600

        # Base time decay
        if age_hours < 3:
            score = 1.0  # Hot news (3 hours)
        elif age_hours < 12:
            score = 0.95  # Today (12 hours)
        elif age_hours < 24:
            score = 0.85  # Recent (24 hours)
        elif age_hours < 72:
            score = 0.70  # This week (3 days)
        elif age_hours < 168:
            score = 0.50  # Last week (7 days)
        else:
            score = 0.30  # Older

        # Adjust for content type
        source_type = news.source_type or "news"

        if source_type == "paper":
            # Papers have longer relevance
            score = score * 0.5 + 0.5  # Slow decay
        elif source_type in ["blog", "discussion"]:
            # Analysis content has medium relevance
            score = score * 0.7 + 0.3
        elif age_hours < 6 and source_type == "news":
            # Breaking news boost
            score = min(score * 1.2, 1.0)

        return round(score, 4)

    def score_technical_credibility(self, news: News) -> float:
        """
        Score technical credibility (0-1)

        Factors:
        - Source verification (30%)
        - Author credibility (30%)
        - Citation quality (40%)
        """
        # 1. Source verification (30%)
        source_score = 1.0 if news.is_verified else 0.5

        # 2. Author credibility (30%)
        author_score = 0.3  # Default
        if news.author:
            if len(news.author) > 0:
                author_score = 0.7
            # Known AI researchers/organizations
            if any(org in news.author for org in ['OpenAI', 'Anthropic', 'Google', 'DeepMind', 'Meta', 'Microsoft']):
                author_score = 1.0

        # 3. Citation quality (40%)
        content = news.original_content or news.content or ""
        citation_score = self._score_citations(content)

        final_score = (
            source_score * 0.30 +
            author_score * 0.30 +
            citation_score * 0.40
        )

        return round(final_score, 4)

    def _score_citations(self, content: str) -> float:
        """Score citation quality based on references"""
        score = 0.0

        # Academic paper citations (+0.4)
        if re.search(r'arxiv\.org|doi\.org|proceedings|conference|journal', content, re.IGNORECASE):
            score += 0.4

        # Official documentation (+0.3)
        if re.search(r'documentation|official|whitepaper|technical report', content, re.IGNORECASE):
            score += 0.3

        # Data/benchmarks (+0.3)
        if re.search(r'dataset|benchmark|evaluation|metrics|results', content, re.IGNORECASE):
            score += 0.3

        return min(score, 1.0)

    def calculate_comprehensive_score(self, news: News) -> Dict:
        """
        Calculate comprehensive quality score with full breakdown

        Returns:
            Dict with final_score, breakdown, and weights
        """
        # Calculate individual scores
        source_authority = self.score_source_authority(news)
        content_depth = self.score_content_depth(news)
        timeliness = self.score_timeliness(news)
        ai_relevance = float(news.ai_relevance_score or 0.5)
        technical_credibility = self.score_technical_credibility(news)

        # Store individual scores
        news.source_authority_score = source_authority
        news.content_depth_score = content_depth
        news.timeliness_score = timeliness
        news.technical_credibility_score = technical_credibility

        # Update source tier
        source_info = get_source_authority(news.source_name)
        news.source_tier = source_info['tier']

        # Calculate final score using News model method
        news.calculate_final_score()

        return news.quality_breakdown

    def score_and_filter_news_list(
        self,
        news_list: List[News],
        min_score: float = MIN_QUALITY_SCORE_ARCHIVE
    ) -> List[News]:
        """
        Score a list of news items and filter by quality

        Args:
            news_list: List of news to score
            min_score: Minimum quality score to keep

        Returns:
            Filtered list of high-quality news
        """
        scored_news = []

        for news in news_list:
            self.calculate_comprehensive_score(news)

            # Filter by minimum score
            if news.final_score and news.final_score >= min_score:
                scored_news.append(news)

        return scored_news

    def update_news_scores(self, db: Session, news_ids: List[int]) -> int:
        """
        Update quality scores for existing news items

        Args:
            db: Database session
            news_ids: List of news IDs to update

        Returns:
            Number of items updated
        """
        updated = 0

        for news_id in news_ids:
            news = db.query(News).filter(News.id == news_id).first()
            if news:
                self.calculate_comprehensive_score(news)
                updated += 1

        db.commit()
        return updated


# Singleton instance
quality_scorer = QualityScorer()
