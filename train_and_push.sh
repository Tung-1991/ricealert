#!/usr/bin/env bash
set -euo pipefail

# ===== SCRIPT HUẤN LUYỆN & TRIỂN KHAI v9.0 - GIẢI PHÁP ĐƠN GIẢN NHẤT =====
# CẬP NHẬT:
# 1. XÓA BỎ HOÀN TOÀN tất cả các bộ lọc log phức tạp bên ngoài.
# 2. Chấp nhận việc banner của NVIDIA/TensorFlow sẽ hiển thị ở đầu mỗi tác vụ.
# 3. Đảm bảo 100% log huấn luyện và DEBUG được giữ lại.
# 4. Vẫn giữ cờ `--ipc=host` để tối ưu hiệu năng.

# --- CẤU HÌNH ---
PROJECT_DIR="/home/tungn/ricealert"
IMAGE="rice-trainer:latest"
LOG_DIR="$PROJECT_DIR/log"
DATA_DIR="$PROJECT_DIR/data"
CONTAINER_NAME="rice-trainer-session"

# Thông tin VPS để triển khai
VPS_USER="root"
VPS_IP="103.101.162.130"
VPS_REMOTE_PATH="/root/ricealert/"

# Kịch bản cho cron job
CRON_WEEKLY_INTERVALS="1h,4h"
CRON_MONTHLY_INTERVALS="1h,4h,1d"

# --- HÀM THỰC THI ---
run_training_process() {
    local debug_env="$1"
    local intervals_str="$2"

    echo "🧹 Dọn dẹp container '$CONTAINER_NAME' cũ (nếu có)..."
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

    LOGFILE="train_$(date +%F_%H-%M-%S).log"
    FULL_LOGFILE_PATH="$LOG_DIR/$LOGFILE"

    local symbols_line
    symbols_line=$(grep -E '^SYMBOLS=' "$PROJECT_DIR/.env" | head -n 1)
    local symbols_val=${symbols_line#*=}
    IFS=',' read -r -a SYMBOLS_ARR <<< "$symbols_val"
    IFS=',' read -r -a INTERVALS_ARR <<< "$intervals_str"

    echo "---"
    echo "🐳 Bắt đầu quá trình huấn luyện theo chế độ CÔ LẬP TIẾN TRÌNH"
    echo "   - Symbols: ${SYMBOLS_ARR[@]}"
    echo "   - Intervals: ${INTERVALS_ARR[@]}"
    echo "   - Log sẽ được lưu vào: $LOGFILE"
    echo "---"

    # Vòng lặp chính
    for sym in "${SYMBOLS_ARR[@]}"; do
        for iv in "${INTERVALS_ARR[@]}"; do
            echo "--- [$(date --iso-8601=seconds)] Bắt đầu train: $sym - $iv ---" | tee -a "$FULL_LOGFILE_PATH"
            
            # ===== DÒNG LỆNH GỐC, KHÔNG LỌC BÊN NGOÀI =====
            # Chỉ gọi python và ghi log, không có grep hay awk
            docker run --rm --gpus all \
              --ipc=host \
              --ulimit memlock=-1 --ulimit stack=67108864 \
              -v "$PROJECT_DIR":/app --user "$(id -u)":"$(id -g)" \
              -e DEBUG="$debug_env" \
              "$IMAGE" \
              python -u trainer.py "$sym" "$iv" 2>&1 | tee -a "$FULL_LOGFILE_PATH"
            
            echo "--- [$(date --iso-8601=seconds)] Kết thúc train: $sym - $iv. Bộ nhớ đã được giải phóng. ---" | tee -a "$FULL_LOGFILE_PATH"
            echo "" | tee -a "$FULL_LOGFILE_PATH"
        done
    done

    echo "---"
    echo "✅ Toàn bộ quá trình huấn luyện đã hoàn tất!"
    echo "🚀 Chuẩn bị triển khai thư mục 'data' lên VPS..."
    
    # ... (Phần scp giữ nguyên)
    if ssh "$VPS_USER@$VPS_IP" "rm -rf \"${VPS_REMOTE_PATH}data\""; then
        echo "    ✅ Xóa thành công."
        if scp -r "$DATA_DIR" "$VPS_USER@$VPS_IP:$VPS_REMOTE_PATH"; then
            echo "    ✅ Triển khai thành công!"
        else
            echo "    ⚠️ LỖI: Không thể copy 'data' lên VPS."
        fi
    else
        echo "⚠️ LỖI: Không thể kết nối tới VPS."
    fi

    echo "🎉 TOÀN BỘ QUY TRÌNH KẾT THÚC. 🎉"
}


# --- ĐIỂM BẮT ĐẦU CỦA SCRIPT ---
if [[ $# -gt 0 ]]; then
    case "$1" in
        weekly) run_training_process 0 "$CRON_WEEKLY_INTERVALS";;
        monthly) run_training_process 0 "$CRON_MONTHLY_INTERVALS";;
        *) echo "Lỗi: Kịch bản '$1' không được nhận dạng."; exit 1;;
    esac
else
    read -rp "Nhập các khung thời gian muốn train (vd: 1h,4h,1d): " INTERVALS_TO_TRAIN
    [[ -z "$INTERVALS_TO_TRAIN" ]] && { echo "Lỗi: Bạn chưa nhập khung thời gian. Thoát."; exit 1; }
    echo "Chọn chế độ chạy:"
    echo "  [1] RUN"
    echo "  [2] DEBUG"
    read -rp "Nhập lựa chọn [1-2]: " MODE_CHOICE
    DEBUG_ENV=0
    [[ "$MODE_CHOICE" == "2" ]] && DEBUG_ENV=1
    run_training_process "$DEBUG_ENV" "$INTERVALS_TO_TRAIN"
fi
