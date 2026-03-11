#!/bin/bash

# Test startup script

cd "$(dirname "$0")/backend"

echo "=========================================="
echo "   Testing News App Startup"
echo "=========================================="
echo ""

# Activate virtual environment
echo "[1/4] Activating virtual environment..."
source venv/bin/activate
echo "      ✓ Done"
echo ""

# Test imports
echo "[2/4] Testing imports..."
python -c "from app.main import app; print('      ✓ FastAPI app loaded')" || exit 1
python -c "from app.services.news_fetcher import news_fetcher; print('      ✓ News fetcher loaded')" || exit 1
python -c "from app.config_sources.ai_sources import VERIFIED_AI_SOURCES; print(f'      ✓ {len(VERIFIED_AI_SOURCES)} AI sources loaded')" || exit 1
echo ""

# Check database
echo "[3/4] Checking database..."
if [ -f "../ainews.db" ]; then
    echo "      ✓ Database file exists"
else
    echo "      ⚠ Database file not found, will be created on first run"
fi
echo ""

# Start server
echo "[4/4] Starting server..."
echo "      Server will start at http://localhost:8000"
echo "      Press Ctrl+C to stop"
echo ""

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
