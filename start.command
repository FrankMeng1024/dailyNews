#!/bin/bash

# AI News App - One-Click Start with Cloudflare Tunnel
# Double-click to start server with public URL

cd "$(dirname "$0")"

echo "=========================================="
echo "   AI News App - Starting Server"
echo "=========================================="
echo ""

# Kill existing processes
pkill -f "uvicorn" 2>/dev/null
pkill -f "cloudflared" 2>/dev/null
lsof -ti:8000 | xargs kill -9 2>/dev/null
sleep 1

# Setup venv if needed
if [ ! -d "backend/venv" ]; then
    echo "First time setup..."
    python3 -m venv backend/venv
fi

source backend/venv/bin/activate
pip install -r backend/requirements.txt -q 2>/dev/null
pip install qrcode -q 2>/dev/null

cd backend

# Run the tunnel script
python start_with_tunnel.py
