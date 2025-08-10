#!/usr/bin/env bash
set -euo pipefail

# ===== CONFIG =====
PROJECT_DIR="${PROJECT_DIR:-/home/tungn/ricealert}"
IMAGE="${IMAGE:-rice-trainer:tf2502}"
INTERVALS="${INTERVALS:-1h,4h,1d}"

NAME_RUN="rice-trainer-run"
NAME_DBG="rice-trainer-debug"
LOG_DIR="$PROJECT_DIR/log"

mkdir -p "$LOG_DIR"

cleanup_containers() {
  # Xoá theo tên chuẩn
  docker rm -f "$NAME_RUN" "$NAME_DBG" >/dev/null 2>&1 || true
  # Xoá mọi container khớp prefix đề phòng đổi mode/đổi tên phụ
  mapfile -t ids < <(docker ps -aq --filter "name=^/rice-trainer-")
  if (( ${#ids[@]} )); then docker rm -f "${ids[@]}" >/dev/null 2>&1 || true; fi
}

run_mode() {
  local ts mode name logfile
  ts="$(date +%F_%H-%M-%S)"
  mode="run"
  name="$NAME_RUN"
  logfile="train_${mode}_${ts}.log"

  cleanup_containers
  docker run -d --rm --name "$name" --gpus all \
    --ulimit memlock=-1 --ulimit stack=67108864 \
    -v "$PROJECT_DIR":/app --user "$(id -u)":"$(id -g)" \
    -e DEBUG=0 \
    "$IMAGE" \
    bash -c "python -u trainer.py $INTERVALS > /app/log/$logfile 2>&1"

  echo "🚀 RUN started: $name"
  cd "$LOG_DIR"
  echo "📜 tail -f $logfile (Ctrl-C để dừng tail, container vẫn chạy)"
  exec tail -f "$logfile"
}

debug_mode() {
  local ts mode name logfile
  ts="$(date +%F_%H-%M-%S)"
  mode="debug"
  name="$NAME_DBG"
  logfile="train_${mode}_${ts}.log"

  cleanup_containers
  docker run -d --rm --name "$name" --gpus all \
    --ulimit memlock=-1 --ulimit stack=67108864 \
    -v "$PROJECT_DIR":/app --user "$(id -u)":"$(id -g)" \
    -e DEBUG=1 \
    "$IMAGE" \
    bash -c "python -u trainer.py $INTERVALS > /app/log/$logfile 2>&1"

  echo "🧪 DEBUG started: $name"
  cd "$LOG_DIR"
  echo "📜 tail -f $logfile (Ctrl-C để dừng tail, container vẫn chạy)"
  exec tail -f "$logfile"
}

echo "Chọn mode: [1] RUN (nền)   [2] DEBUG (nền)"
read -rp "Nhập 1 hoặc 2: " choice

case "$choice" in
  1) run_mode ;;
  2) debug_mode ;;
  *) echo "Lựa chọn không hợp lệ."; exit 1 ;;
esac
