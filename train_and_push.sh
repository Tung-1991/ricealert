#!/usr/bin/env bash
set -euo pipefail

# ===== SCRIPT HUẤN LUYỆN & TRIỂN KHAI v2.1 =====
# FIX: Thêm lại các cờ --ulimit đã bị thiếu.

# --- CẤU HÌNH ---
# Đường dẫn trên máy LOCAL của bạn
PROJECT_DIR="/home/tungn/ricealert"
IMAGE="rice-trainer:latest"
LOG_DIR="$PROJECT_DIR/log"
DATA_DIR="$PROJECT_DIR/data"
CONTAINER_NAME="rice-trainer-session"

# Thông tin VPS để triển khai
VPS_USER="root"
VPS_IP="103.101.162.130"
VPS_REMOTE_PATH="/root/ricealert/"

# Kịch bản cho cron job hàng tuần
CRON_WEEKLY_INTERVALS="1h,4h"
# Kịch bản cho cron job hàng tháng (train lại tất cả)
CRON_MONTHLY_INTERVALS="1h,4h,1d"

# --- HÀM THỰC THI ---
run_training_process() {
    local debug_env="$1"
    local intervals="$2"
    
    echo "🧹 Dọn dẹp container '$CONTAINER_NAME' cũ (nếu có)..."
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

    LOGFILE="train_$(date +%F_%H-%M-%S).log"
    FULL_LOGFILE_PATH="$LOG_DIR/$LOGFILE"

    echo "---"
    echo "🐳 Bắt đầu quá trình huấn luyện cho intervals: $intervals | Chế độ DEBUG: $debug_env"
    echo "   Log sẽ được lưu vào: $LOGFILE"
    echo "---"

    # <<< SỬA LỖI: THÊM LẠI 2 DÒNG --ulimit Ở ĐÂY >>>
    docker run --rm --name "$CONTAINER_NAME" --gpus all \
      --ulimit memlock=-1 --ulimit stack=67108864 \
      -v "$PROJECT_DIR":/app --user "$(id -u)":"$(id -g)" \
      -e DEBUG="$debug_env" \
      "$IMAGE" \
      bash -c "python -u trainer.py \"$intervals\"" 2>&1 | tee "$FULL_LOGFILE_PATH"

    echo "---"
    echo "✅ Quá trình huấn luyện đã hoàn tất!"

    # --- Triển khai trực tiếp thư mục data ---
    echo "🚀 Chuẩn bị triển khai trực tiếp thư mục 'data' lên VPS..."
    
    echo "   -> Bước 1/2: Đang xóa thư mục 'data' cũ trên VPS ($VPS_IP)..."
    if ssh "$VPS_USER@$VPS_IP" "rm -rf \"${VPS_REMOTE_PATH}data\""; then
        echo "      ✅ Xóa thành công."
        
        echo "   -> Bước 2/2: Đang copy thư mục 'data' mới lên VPS..."
        if scp -r "$DATA_DIR" "$VPS_USER@$VPS_IP:$VPS_REMOTE_PATH"; then
            echo "      ✅ Triển khai toàn bộ thư mục 'data' thành công!"
            echo "👉 Quá trình hoàn tất. Dịch vụ trên VPS giờ đã có dữ liệu mới."
        else
            echo "      ⚠️ LỖI: Không thể copy thư mục 'data' mới lên VPS."
            echo "      👉 Vui lòng kiểm tra kết nối và thử copy thủ công:"
            echo "      scp -r \"$DATA_DIR\" \"$VPS_USER@$VPS_IP:$VPS_REMOTE_PATH\""
        fi
    else
        echo "⚠️ LỖI: Không thể kết nối tới VPS để xóa thư mục 'data' cũ."
        echo "👉 Triển khai đã bị hủy. Vui lòng kiểm tra và thực hiện thủ công."
    fi

    echo "🎉 TOÀN BỘ QUY TRÌNH KẾT THÚC. 🎉"
}


# --- ĐIỂM BẮT ĐẦU CỦA SCRIPT ---
if [[ $# -gt 0 ]]; then
    # CHẾ ĐỘ TỰ ĐỘNG (Dành cho crontab)
    case "$1" in
        weekly)
            echo "Chạy kịch bản tự động HÀNG TUẦN..."
            run_training_process 0 "$CRON_WEEKLY_INTERVALS"
            ;;
        monthly)
            echo "Chạy kịch bản tự động HÀNG THÁNG..."
            run_training_process 0 "$CRON_MONTHLY_INTERVALS"
            ;;
        *)
            echo "Lỗi: Kịch bản '$1' không được nhận dạng."
            exit 1
            ;;
    esac
else
    # CHẾ ĐỘ TƯƠNG TÁC (Khi bạn chạy thủ công)
    read -rp "Nhập các khung thời gian muốn train (vd: 1h,4h,1d): " INTERVALS_TO_TRAIN
    if [[ -z "$INTERVALS_TO_TRAIN" ]]; then
        echo "Lỗi: Bạn chưa nhập khung thời gian. Thoát."
        exit 1
    fi

    echo "Chọn chế độ chạy (Cả 2 chế độ đều tự xóa container khi xong):"
    echo "  [1] RUN   (Log sạch, không Epoch)"
    echo "  [2] DEBUG (Log có Epoch, để theo dõi)"
    read -rp "Nhập lựa chọn [1-2]: " MODE_CHOICE

    DEBUG_ENV=0
    if [[ "$MODE_CHOICE" == "2" ]]; then
        DEBUG_ENV=1
    fi
    
    run_training_process "$DEBUG_ENV" "$INTERVALS_TO_TRAIN"
fi
