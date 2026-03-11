#!/bin/bash

cd "$(dirname "$0")"

echo "🧹 清理项目..."
echo ""

# 1. 删除临时文件
echo "[1/3] 删除临时文件..."
rm -f test-frontend.html ui-demo.html
rm -f TROUBLESHOOTING.md FRONTEND_UPDATE.md
rm -f force-refresh.sh
echo "✓ 临时文件已删除"
echo ""

# 2. 清空数据库
echo "[2/3] 清空数据库..."
cd backend
source venv/bin/activate
python -c "
from app.database import SessionLocal
from app.models.news import News
from app.models.audio import AudioRecording, AudioNews

db = SessionLocal()
try:
    # 删除关联表
    audio_news_count = db.query(AudioNews).count()
    db.query(AudioNews).delete()

    # 删除audio记录
    audio_count = db.query(AudioRecording).count()
    db.query(AudioRecording).delete()

    # 删除新闻
    news_count = db.query(News).count()
    db.query(News).delete()

    db.commit()
    print(f'✓ 已删除 {news_count} 条新闻')
    print(f'✓ 已删除 {audio_count} 条音频记录')
    print(f'✓ 已删除 {audio_news_count} 条关联记录')
except Exception as e:
    print(f'✗ 数据库清理失败: {e}')
    db.rollback()
finally:
    db.close()
"
cd ..
echo ""

# 3. 清理音频文件
echo "[3/3] 清理音频文件..."
if [ -d "backend/storage/audio" ]; then
    # 只删除MP3文件，保留目录和预览
    find backend/storage/audio -name "*.mp3" -not -path "*/previews/*" -delete
    echo "✓ 音频文件已清理（保留预览）"
else
    echo "✓ 音频目录不存在，跳过"
fi
echo ""

echo "✅ 清理完成！"
echo ""
echo "下一步："
echo "  1. 运行 ./quick-start.sh 启动服务器"
echo "  2. 访问 http://localhost:8000"
echo "  3. 点击'刷新'按钮重新爬取数据"
