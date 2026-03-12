#!/bin/bash

# AI News App - Clear Data
# Double-click to clear database data (keeps table structure)

cd "$(dirname "$0")"

echo "=========================================="
echo "   AI News - 清除数据"
echo "=========================================="
echo ""

# Activate virtual environment
if [ -d "backend/venv" ]; then
    source backend/venv/bin/activate
else
    echo "Error: 虚拟环境不存在，请先运行 start.command"
    read -p "按回车键退出..."
    exit 1
fi

cd backend

echo "选择要清除的数据:"
echo "  1) 全部数据 (新闻 + 音频 + 抓取历史)"
echo "  2) 只清除新闻"
echo "  3) 只清除音频"
echo "  4) 取消"
echo ""
read -p "请输入选项 [1-4]: " choice

case $choice in
    1)
        echo ""
        echo "正在清除全部数据..."
        python3 clear_data.py --all
        ;;
    2)
        echo ""
        echo "正在清除新闻数据..."
        python3 clear_data.py --news
        ;;
    3)
        echo ""
        echo "正在清除音频数据..."
        python3 clear_data.py --audio
        ;;
    4)
        echo ""
        echo "已取消"
        ;;
    *)
        echo ""
        echo "无效选项"
        ;;
esac

echo ""
read -p "按回车键退出..."
