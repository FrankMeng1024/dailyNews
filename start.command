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
pkill -f "localtunnel" 2>/dev/null
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

# Step 3: Start tunnel (Cloudflare first, then localtunnel as fallback)
echo "[3/4] 启动隧道..."
rm -f /tmp/tunnel.log
cd backend
TUNNEL_URL=""
TUNNEL_PID=""
TUNNEL_TYPE=""

# 尝试 Cloudflare
echo "      尝试 Cloudflare..."
cloudflared tunnel --url http://localhost:8000 > /tmp/tunnel.log 2>&1 &
TUNNEL_PID=$!

for i in {1..20}; do
    sleep 1
    # 检查是否有错误
    if grep -q "failed to unmarshal\|Error\|error" /tmp/tunnel.log 2>/dev/null; then
        break
    fi
    TUNNEL_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /tmp/tunnel.log 2>/dev/null | head -1)
    if [ -n "$TUNNEL_URL" ]; then
        TUNNEL_TYPE="Cloudflare"
        break
    fi
    if [ $((i % 5)) -eq 0 ]; then
        echo "      ... $i 秒"
    fi
done

# 如果 Cloudflare 失败，尝试 localtunnel
if [ -z "$TUNNEL_URL" ]; then
    echo "      ✗ Cloudflare 不可用"
    kill $TUNNEL_PID 2>/dev/null

    # 检查 npx 是否可用
    if command -v npx &> /dev/null; then
        echo "      尝试 localtunnel..."
        rm -f /tmp/tunnel.log
        npx localtunnel --port 8000 --subdomain ainews > /tmp/tunnel.log 2>&1 &
        TUNNEL_PID=$!

        for i in {1..30}; do
            sleep 1
            TUNNEL_URL=$(grep -o 'https://[a-z0-9-]*\.loca\.lt' /tmp/tunnel.log 2>/dev/null | head -1)
            if [ -n "$TUNNEL_URL" ]; then
                TUNNEL_TYPE="localtunnel"
                break
            fi
            if [ $((i % 5)) -eq 0 ]; then
                echo "      ... $i 秒"
            fi
        done
    else
        echo "      ⚠ npx 未安装，无法使用 localtunnel"
        echo "      请运行: brew install node"
    fi
fi

if [ -n "$TUNNEL_URL" ]; then
    echo "      ✓ [$TUNNEL_TYPE] $TUNNEL_URL"
    if [ "$TUNNEL_TYPE" = "localtunnel" ]; then
        PUBLIC_IP=$(curl -s https://ipv4.icanhazip.com)
        echo ""
        echo "      ⚠️  首次访问需输入密码: $PUBLIC_IP"
    fi
else
    echo "      ✗ 所有隧道方案均失败"
    TUNNEL_PID=""
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
    else
        echo "      - 小程序配置文件不存在，跳过"
    fi
else
    echo "      ⚠ 无隧道URL，跳过配置"
fi
echo ""

# Show info and QR code BEFORE starting server
echo "=========================================="
echo "  服务信息"
echo "=========================================="
echo "  Local:   http://localhost:8000"
if [ -n "$TUNNEL_URL" ]; then
    echo "  Tunnel:  $TUNNEL_URL"
    echo "  Docs:    $TUNNEL_URL/docs"
else
    echo "  Tunnel:  (未启动)"
    echo "  Docs:    http://localhost:8000/docs"
fi
echo "=========================================="
echo ""

# 显示 QR 码
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
    echo ""
fi

echo "Press Ctrl+C to stop"
echo ""
echo "=========================================="
echo "  后端日志:"
echo "=========================================="

# Cleanup on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $TUNNEL_PID 2>/dev/null
    pkill -f "uvicorn" 2>/dev/null
    pkill -f "cloudflared" 2>/dev/null
    pkill -f "localtunnel" 2>/dev/null
}
trap cleanup EXIT

# Run uvicorn in foreground (最后启动，日志会持续输出)
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
