#!/bin/bash

echo "🚮 Đang dọn dẹp hệ thống cho Ngài..."

# Xóa file
rm -f advisor_state.json
rm -f cooldown_tracker.json
rm -f ml_state.json
rm -f ricenews/cooldown_tracker.json

# Xóa thư mục và nội dung bên trong
rm -rf advisor_log
rm -rf ai_logs
rm -rf backtest/backtest_results
rm -rf backtest/data_cache
rm -rf backtest/paper_data
rm -rf log/*
rm -rf output/*
rm -rf __pycache__
rm -rf ricenews/log
rm -rf ricenews/lognew
rm -rf ricenews/__pycache__
rm -rf trade/tradelog

echo "✅ Dọn dẹp hoàn tất. Mọi thứ đã sạch sẽ như lệnh Ngài ban ra."
