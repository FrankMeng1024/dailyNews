#!/bin/bash

# AI News App - Local Development Start Script
# Run without Docker

cd "$(dirname "$0")"

echo "=========================================="
echo "   AI News App - Local Development"
echo "=========================================="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed!"
    exit 1
fi

echo "✓ Python 3 found"

# Check for .env file
if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️  Created .env - please edit with your API keys"
fi

# Load environment
export $(grep -v '^#' .env | xargs)

# Create virtual environment if not exists
if [ ! -d "backend/venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv backend/venv
fi

# Activate and install dependencies
source backend/venv/bin/activate
pip install -r backend/requirements.txt -q

# Create storage directory
mkdir -p backend/storage/audio

echo ""
echo "Starting backend server..."
echo "API: http://localhost:8000"
echo "Docs: http://localhost:8000/docs"
echo ""
echo "Note: You need MySQL running separately."
echo "Or use SQLite by changing DATABASE_URL in .env to:"
echo "DATABASE_URL=sqlite:///./ainews.db"
echo ""

cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
