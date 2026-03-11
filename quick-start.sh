#!/bin/bash

# Quick test script

cd "$(dirname "$0")/backend"

echo "Testing News App..."
echo ""

# Activate venv
source venv/bin/activate

# Test imports
echo "[1/3] Testing imports..."
python -c "from app.main import app; print('✓ App loads')" || exit 1

# Check database
echo "[2/3] Checking database..."
python -c "
from app.database import SessionLocal
from app.models.news import News

db = SessionLocal()
count = db.query(News).count()
print(f'✓ Database OK: {count} news items')

# Check if new fields exist
news = db.query(News).first()
if news:
    print(f'✓ source_type: {news.source_type}')
    print(f'✓ is_verified: {news.is_verified}')
db.close()
" || exit 1

echo "[3/3] Starting server..."
echo ""
echo "Server will start at http://localhost:8000"
echo "Open in browser to see the updated UI"
echo ""
echo "Press Ctrl+C to stop"
echo ""

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
