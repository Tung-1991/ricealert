#!/usr/bin/env bash
set -euo pipefail

# ===== SCRIPT HUẤN LUYỆN & TRIỂN KHAI TỰ ĐỘNG v1.8 =====
# TÍNH NĂNG MỚI: Xử lý lỗi khi triển khai (scp), không làm crash script.

# --- CẤU HÌNH ---
# Đường dẫn trên máy LOCAL của bạn
PROJECT_DIR="/home/tungn/ricealert"
IMAGE="rice-trainer:tf2502"
LOG_DIR="$PROJECT_DIR/log"
CONTAINER_NAME="rice-trainer-session" # Tên tạm thời, vì sẽ bị xóa
ARCHIVE_NAME="data.tar.gz"

# Thông tin VPS để triển khai
VPS_USER="root"
VPS_IP="103.101.162.130"
VPS_REMOTE_PATH="/root/ricealert/" # QUAN TRỌNG: Phải có dấu / ở cuối

# --- THỰC THI ---

# Đảm bảo thư mục log tồn tại
mkdir -p "$LOG_DIR"

# Dọn dẹp container cũ (chỉ để phòng hờ)
echo "🧹 Dọn dẹp container '$CONTAINER_NAME' cũ (nếu có)..."
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

# Lấy thông tin từ người dùng
read -rp "Nhập các khung thời gian muốn train (vd: 1h,4h,1d): " INTERVALS_TO_TRAIN
if [[ -z "$INTERVALS_TO_TRAIN" ]]; then
  echo "Lỗi: Bạn chưa nhập khung thời gian. Thoát."
  exit 1
fi

echo "Chọn chế độ chạy (Cả 2 chế độ đều tự xóa container khi xong):"
echo "  [1] RUN   (Log sạch, không Epoch)"
echo "  [2] DEBUG (Log có Epoch, để theo dõi)"
read -rp "Nhập lựa chọn [1-2]: " MODE_CHOICE

# Thiết lập biến môi trường DEBUG dựa trên lựa chọn
DEBUG_ENV=0
if [[ "$MODE_CHOICE" == "2" ]]; then
  DEBUG_ENV=1
fi

LOGFILE="train_$(date +%F_%H-%M-%S).log"
FULL_LOGFILE_PATH="$LOG_DIR/$LOGFILE"

# --- Bắt đầu quá trình huấn luyện ---
echo "---"
echo "🐳 Bắt đầu quá trình huấn luyện. Log sẽ được hiển thị và lưu vào: $LOGFILE"
echo "⏳ Script sẽ tự động tiếp tục sau khi huấn luyện hoàn tất. Vui lòng không tắt terminal này."
echo "---"

# Chạy container ở FOREGROUND, --rm để tự xóa, và dùng `tee` để xuất log
docker run --rm --name "$CONTAINER_NAME" --gpus all \
  --ulimit memlock=-1 --ulimit stack=67108864 \
  -v "$PROJECT_DIR":/app --user "$(id -u)":"$(id -g)" \
  -e DEBUG="$DEBUG_ENV" \
  "$IMAGE" \
  bash -c "python -u trainer.py \"$INTERVALS_TO_TRAIN\"" 2>&1 | tee "$FULL_LOGFILE_PATH"

# --- Các lệnh sau đây CHỈ được thực thi KHI quá trình train ở trên đã hoàn tất ---
echo "---"
echo "✅ Quá trình huấn luyện đã hoàn tất!"

# Nén thư mục data
echo "📦 Đang nén thư mục 'data' thành '$ARCHIVE_NAME'..."
cd "$PROJECT_DIR"
tar -czf "$ARCHIVE_NAME" data
echo "✅ Nén thành công! File '$ARCHIVE_NAME' đã được tạo."

# Triển khai file nén lên VPS với cơ chế xử lý lỗi
echo "🚀 Đang thử triển khai file '$ARCHIVE_NAME' lên VPS ($VPS_IP)..."

if scp "$ARCHIVE_NAME" "$VPS_USER@$VPS_IP:$VPS_REMOTE_PATH"; then
    # Khối lệnh này chạy nếu scp THÀNH CÔNG
    echo "✅ Triển khai thành công!"
    echo "👉 Hãy SSH vào VPS và giải nén bằng lệnh: cd $VPS_REMOTE_PATH && tar -xzvf $ARCHIVE_NAME"
else
    # Khối lệnh này chạy nếu scp THẤT BẠI
    echo "⚠️ LỖI: Không thể tự động triển khai file lên VPS."
    echo "Lý do có thể là: Sai mật khẩu, VPS không thể truy cập, hoặc lỗi mạng."
    echo "👉 Vui lòng tự triển khai thủ công bằng cách chạy lệnh sau trên máy LOCAL:"
    echo "scp \"$PROJECT_DIR/$ARCHIVE_NAME\" \"$VPS_USER@$VPS_IP:$VPS_REMOTE_PATH\""
fi

echo "🎉 TOÀN BỘ QUY TRÌNH KẾT THÚC. 🎉"
