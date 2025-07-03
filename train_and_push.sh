#!/bin/bash
source /home/tungn/ricealert/venv/bin/activate
cd /home/tungn/ricealert

TODAY=$(date +"%Y-%m-%d")

echo "🧼 Reset local để giống origin..."
# Xoá sạch local, khôi phục y chang bản remote (trừ thư mục .git và venv)
git fetch origin
git reset --hard origin/main
git clean -fd                # Xoá file rác untracked

echo "📥 Đã đồng bộ code và data mới nhất từ Git."

# 1. Train lại
echo "🏋️ Đang train lại model..."
python trainer.py

# 2. Add data mới (đã được trainer.py tạo hoặc cập nhật)
git add data/
git commit -m "Auto data update on $TODAY" || echo "✅ Không có gì mới để commit"

# 3. Push lên Git
git push origin main
echo "✅ Đã push data lên Git thành công."
