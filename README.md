Chắc chắn rồi\! Một dự án chất lượng cần một tài liệu README tương xứng. Dưới đây là phiên bản README được viết lại hoàn toàn, làm nổi bật sức mạnh và sự tinh vi của hệ thống AI mà bạn đã xây dựng.

-----

# 🍚 RiceAlert AI - Trợ lý Tín hiệu Giao dịch

[](https://www.python.org/downloads/)
[](https://opensource.org/licenses/MIT)

**RiceAlert AI** là một hệ thống bot tự động, sử dụng các mô hình **Machine Learning** đã được huấn luyện để phân tích và dự báo tín hiệu giao dịch cho nhiều loại tiền điện tử trên nhiều khung thời gian khác nhau. Các cảnh báo và báo cáo tổng quan được gửi trực tiếp đến kênh Discord của bạn.

-----

## \#\# Tính Năng Nổi Bật ✨

  * **Phân tích Đa tài sản & Đa khung thời gian**: Theo dõi đồng thời nhiều cặp giao dịch (ví dụ: `BTCUSDT`, `ETHUSDT`) trên các khung thời gian (`1h`, `4h`, `1d`).
  * **Dựa trên Máy học (Machine Learning)**: Sử dụng các mô hình phân loại (Classification) và hồi quy (Regression) của `scikit-learn` để dự báo xác suất và mức độ thay đổi giá.
  * **Logic Tín hiệu Thích ứng**: Hệ thống tự động áp dụng các ngưỡng phân tích khác nhau cho mỗi khung thời gian, giúp tín hiệu trở nên chính xác và phù hợp hơn với ngữ cảnh thị trường.
  * **Hệ thống Cảnh báo Kép**:
      * **Cảnh báo Tức thì**: Gửi thông báo ngay lập tức khi có sự thay đổi tín hiệu quan trọng.
      * **Báo cáo Tổng quan**: Gửi báo cáo tóm tắt toàn bộ thị trường vào các thời điểm cố định trong ngày.
  * **Hệ thống Cooldown Thông minh**: Tự động quản lý tần suất cảnh báo cho từng cặp giao dịch/khung thời gian để tránh "spam" và nhiễu thông tin.
  * **Dễ dàng Cấu hình**: Toàn bộ cài đặt quan trọng được quản lý trong file `.env`.

-----

## \#\# Luồng Hoạt động ⚙️

Hệ thống hoạt động theo một chu trình tự động và khép kín:

1.  **Tải Dữ liệu**: Lấy dữ liệu K-line (nến) mới nhất từ API của Binance.
2.  **Thêm Đặc trưng (Feature Engineering)**: Tính toán hàng loạt các chỉ báo kỹ thuật phổ biến (RSI, EMA, MACD, ADX, Bollinger Bands, v.v.) để làm đầu vào cho mô hình.
3.  **Dự báo bằng AI**: Tải các mô hình Machine Learning (`.pkl`) đã được huấn luyện trước đó để đưa ra dự báo về xác suất Mua/Bán và mức độ thay đổi giá.
4.  **Phân loại Tín hiệu**: Dựa trên kết quả dự báo và khung thời gian đang xét, hệ thống phân loại thành một trong 8 mức tín hiệu rõ ràng.
5.  **Quản lý và Gửi Cảnh báo**: So sánh tín hiệu mới với trạng thái đã lưu, áp dụng logic `cooldown`, và quyết định gửi cảnh báo tức thì hoặc cập nhật vào báo cáo tổng quan.

-----

## \#\# Các Mức Tín hiệu 🚦

Hệ thống sử dụng 8 cấp độ tín hiệu để thể hiện rõ nét trạng thái của thị trường theo phân tích của AI.

| Icon | Tên Tín hiệu | Ý nghĩa |
| :--: | :--- | :--- |
| 🔥 | **STRONG BUY** | Tín hiệu Mua rất mạnh, xác suất tăng giá cao. |
| ✅ | **BUY** | Tín hiệu Mua, có khả năng tăng giá. |
| 🟡 | **WEAK BUY** | Tín hiệu Mua yếu, cần theo dõi thêm. |
| 🔍 | **HOLD** | Thị trường đi ngang (sideways) hoặc tín hiệu không rõ ràng. Nên quan sát. |
| 🚧 | **AVOID** | Tín hiệu xung đột hoặc rủi ro cao. Nên đứng ngoài. |
| 🔻 | **WEAK SELL** | Tín hiệu Bán yếu, có khả năng giảm nhẹ. |
| ❌ | **SELL** | Tín hiệu Bán, có khả năng giảm giá. |
| 🚨 | **PANIC SELL** | Tín hiệu Bán rất mạnh, xác suất giảm giá cao. |

-----

## \#\# Cấu trúc Thư mục

```
/ricealert
├── data/                  # Chứa các model (.pkl) và metadata (.json)
│   ├── model_BTCUSDT_clf_1h.pkl
│   └── meta_BTCUSDT_1h.json
├── ai_logs/               # Chứa log và output phân tích từ mỗi lần chạy
│   ├── BTCUSDT_1h.json
│   └── error_ml.log
├── ml_report.py           # Script chính để chạy phân tích và gửi cảnh báo
├── trainer.py             # (Tùy chọn) Script để huấn luyện và tạo model
├── ml_state.json          # File trạng thái để lưu tín hiệu cuối cùng và cooldown
├── requirements.txt       # Các thư viện Python cần thiết
└── .env                   # File cấu hình cho hệ thống
```

-----

## \#\# Cài đặt & Cấu hình

#### **1. Chuẩn bị môi trường**

```bash
# Clone repository
git clone https://your-repo-url/ricealert.git
cd ricealert

# Tạo môi trường ảo
python -m venv venv

# Kích hoạt môi trường ảo
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# Cài đặt các thư viện cần thiết
pip install -r requirements.txt
```

#### **2. Cấu hình**

Tạo một file tên là `.env` trong thư mục gốc và điền các thông tin sau:

```env
# Các cặp tiền tệ muốn theo dõi, cách nhau bởi dấu phẩy
SYMBOLS=BTCUSDT,ETHUSDT,SUIUSDT,LINKUSDT,AVAXUSDT

# Các khung thời gian muốn phân tích, cách nhau bởi dấu phẩy
INTERVALS=1h,4h,1d

# Webhook của kênh Discord để nhận tín hiệu chính
DISCORD_AI_WEBHOOK="https://discord.com/api/webhooks/your_main_webhook_url"

# (Tùy chọn) Webhook của kênh Discord để nhận thông báo lỗi
DISCORD_ERROR_WEBHOOK="https://discord.com/api/webhooks/your_error_webhook_url"
```

> **Lưu ý**: Bạn cần có sẵn các file model (`.pkl`) và metadata (`.json`) trong thư mục `data/` tương ứng với các `SYMBOLS` và `INTERVALS` đã cấu hình.

-----

## \#\# Sử dụng

Bạn có thể chạy bot theo cách thủ công hoặc thiết lập lịch tự động.

#### **Chạy thủ công**

Chỉ cần thực thi file `ml_report.py` trong khi môi trường ảo đang được kích hoạt:

```bash
python ml_report.py
```

#### **Chạy tự động (Sử dụng Cron)**

Để bot tự động chạy định kỳ (ví dụ: mỗi 5 phút), bạn có thể sử dụng `crontab` trên Linux/macOS.

Mở crontab để chỉnh sửa:

```bash
crontab -e
```

Thêm dòng sau vào cuối file (nhớ thay đổi đường dẫn cho đúng với hệ thống của bạn):

```cron
*/5 * * * * /path/to/your/ricealert/venv/bin/python /path/to/your/ricealert/ml_report.py >> /path/to/your/ricealert/cron.log 2>&1
```
