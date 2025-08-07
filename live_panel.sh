#!/bin/bash

# Lấy đường dẫn thư mục hiện tại của script
BASE_DIR=$(dirname "$(readlink -f "$0")")

# Đường dẫn đến môi trường ảo và file python
VENV_ACTIVATE="$BASE_DIR/venv/bin/activate"
CONTROL_PANEL_SCRIPT="$BASE_DIR/livetrade/control_live.py"

# Kiểm tra xem file activate có tồn tại không
if [ ! -f "$VENV_ACTIVATE" ]; then
    echo "Lỗi: Không tìm thấy môi trường ảo tại $VENV_ACTIVATE"
    echo "Vui lòng đảm bảo bạn đã tạo venv trong thư mục ricealert."
    exit 1
fi

# Kích hoạt môi trường ảo
source "$VENV_ACTIVATE"

echo "✅ Đã kích hoạt môi trường ảo."
echo "🚀 Khởi động Bảng điều khiển..."

# Chạy script Python
python3 "$CONTROL_PANEL_SCRIPT"

# Hủy kích hoạt môi trường ảo sau khi script kết thúc
deactivate
echo "✅ Đã thoát khỏi môi trường ảo."
