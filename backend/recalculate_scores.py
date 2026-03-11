#!/usr/bin/env python3
"""
Recalculate quality scores for all existing articles
Run: python recalculate_scores.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal
from app.models.news import News
from app.services.quality_scorer import quality_scorer

def recalculate_all_scores():
    db = SessionLocal()
    try:
        all_news = db.query(News).all()
        print(f"Found {len(all_news)} articles to score")

        updated = 0
        for news in all_news:
            # Recalculate comprehensive score
            quality_scorer.calculate_comprehensive_score(news)
            updated += 1

            if updated % 10 == 0:
                print(f"Processed {updated}/{len(all_news)}...")

        db.commit()
        print(f"\nSuccess! Updated {updated} articles")

        # Show score distribution
        scores = db.query(News.final_score).all()
        score_list = sorted([s[0] for s in scores if s[0]])
        if score_list:
            print(f"\nScore distribution:")
            print(f"  Min: {score_list[0]:.4f}")
            print(f"  25%: {score_list[len(score_list)//4]:.4f}")
            print(f"  50%: {score_list[len(score_list)//2]:.4f}")
            print(f"  75%: {score_list[3*len(score_list)//4]:.4f}")
            print(f"  Max: {score_list[-1]:.4f}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    recalculate_all_scores()
