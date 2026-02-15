#!/bin/bash

# AI News App - One-Click Start
# Double-click to start backend + tunnel

cd "$(dirname "$0")"

echo "=========================================="
echo "   AI News App"
echo "=========================================="
echo ""

# Step 1: Clean old processes
echo "[1/4] 清理旧进程..."
pkill -f "uvicorn" 2>/dev/null
pkill -f "cloudflared" 2>/dev/null
lsof -ti:8000 | xargs kill -9 2>/dev/null
sleep 1
echo "      ✓ 完成"
echo ""

# Step 2: Setup backend environment
echo "[2/4] 准备后端环境..."
if [ ! -d "backend/venv" ]; then
    echo "      首次运行，创建虚拟环境..."
    python3 -m venv backend/venv
fi
source backend/venv/bin/activate
pip install -r backend/requirements.txt -q 2>/dev/null
pip install qrcode -q 2>/dev/null
echo "      ✓ 完成"
echo ""

# Step 3: Start Cloudflare tunnel (background)
echo "[3/4] 启动 Cloudflare 隧道..."
rm -f /tmp/tunnel.log
cd backend
cloudflared tunnel --url http://localhost:8000 > /tmp/tunnel.log 2>&1 &
TUNNEL_PID=$!

# Wait for tunnel URL
for i in {1..15}; do
    sleep 1
    TUNNEL_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /tmp/tunnel.log 2>/dev/null | head -1)
    if [ -n "$TUNNEL_URL" ]; then
        break
    fi
done

if [ -n "$TUNNEL_URL" ]; then
    echo "      ✓ $TUNNEL_URL"
else
    echo "      ⚠ 隧道启动中..."
fi
echo ""

# Step 4: Update miniprogram API URL
echo "[4/4] 配置小程序 API..."
cd ..
if [ -n "$TUNNEL_URL" ]; then
    CONFIG_FILE="miniprogram/utils/constants.js"
    if [ -f "$CONFIG_FILE" ]; then
        sed -i '' "s|const BASE_URL = '.*';|const BASE_URL = '${TUNNEL_URL}/api/v1';|g" "$CONFIG_FILE" 2>/dev/null
        echo "      ✓ API地址已更新"
    fi
else
    echo "      ⚠ 等待隧道URL..."
fi
echo ""

# Show info
echo "=========================================="
echo "  服务信息"
echo "=========================================="
echo "  Local:   http://localhost:8000"
echo "  Tunnel:  ${TUNNEL_URL:-pending...}"
echo "  Docs:    ${TUNNEL_URL:-http://localhost:8000}/docs"
echo "=========================================="
echo ""

if [ -n "$TUNNEL_URL" ]; then
    echo "=========================================="
    echo "  扫描二维码访问 API:"
    echo "=========================================="
    python3 -c "
import qrcode
qr = qrcode.QRCode(box_size=1, border=1)
qr.add_data('$TUNNEL_URL')
qr.make()
qr.print_ascii()
" 2>/dev/null
    echo "=========================================="
fi

echo ""
echo "Press Ctrl+C to stop"
echo ""

# Cleanup on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $TUNNEL_PID 2>/dev/null
    pkill -f "uvicorn" 2>/dev/null
    pkill -f "cloudflared" 2>/dev/null
}
trap cleanup EXIT

# Run uvicorn in foreground
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
