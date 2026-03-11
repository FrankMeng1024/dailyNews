#!/usr/bin/env python3
"""
Update quality thresholds based on new score distribution
Run: python update_thresholds.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal
from app.services.quality_threshold_manager import QualityThresholdManager

def update_thresholds():
    db = SessionLocal()
    try:
        # Calculate new thresholds based on updated scores
        thresholds = QualityThresholdManager.calculate_thresholds(db)
        print(f"Calculated thresholds: {thresholds}")

        # Save to database
        QualityThresholdManager.save_thresholds(db, thresholds)
        print("✓ Thresholds saved to database")

        # Show statistics
        stats = QualityThresholdManager.get_score_statistics(db)
        print(f"\nScore Statistics:")
        print(f"  Total articles: {stats['total']}")
        print(f"  Min score: {stats['min_score']}")
        print(f"  Avg score: {stats['avg_score']}")
        print(f"  Max score: {stats['max_score']}")
        print(f"\nQuality Thresholds:")
        print(f"  Premium (top 33%): >= {stats['thresholds']['premium']}")
        print(f"  Standard (top 67%): >= {stats['thresholds']['standard']}")
        print(f"  All: >= {stats['thresholds']['all']}")
        print(f"\nArticle Distribution:")
        print(f"  Premium: {stats['distribution']['premium']} articles")
        print(f"  Standard: {stats['distribution']['standard']} articles")
        print(f"  All: {stats['distribution']['all']} articles")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    update_thresholds()
