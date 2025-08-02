# Bản Phân Tích Toàn Diện Hệ thống Giao dịch RiceAlert v8.0

Đây là tài liệu giải thích chi tiết cơ chế hoạt động, triết lý và các tham số cốt lõi của hệ thống giao dịch tự động RiceAlert. Hệ thống được xây dựng dựa trên 4 trụ cột chính, hoạt động phối hợp để đưa ra quyết định giao dịch một cách toàn diện.

---

## I. Trụ cột 1: Phân tích Kỹ thuật (Module `Indicator` & `Signal`)

**Linh hồn:** Hoạt động như một "Hệ thống Chấm điểm Đồng thuận". Nó tổng hợp tín hiệu từ nhiều chỉ báo khác nhau, mỗi chỉ báo có một "trọng số" (uy tín) riêng, để đưa ra một điểm số kỹ thuật cuối cùng (`raw_tech_score`).

**Khung thời gian áp dụng:** 1h, 4h, 1d.

### Logic & Tham số Tính điểm (`signal_logic.py -> RULE_WEIGHTS`):

Mỗi quy tắc được kích hoạt sẽ cộng hoặc trừ điểm vào điểm kỹ thuật thô.

| Quy tắc Tín hiệu | Điểm Tối đa | Mô tả Kích hoạt |
| :--- | :--- | :--- |
| **`score_rsi_div`** | **`2.0`** | Có Phân kỳ Tăng (giá đáy sau thấp hơn, RSI đáy sau cao hơn) hoặc Phân kỳ Giảm. |
| **`score_breakout`** | **`2.0`** | Giá phá vỡ dải Bollinger Band sau một giai đoạn co thắt (BBW thấp), có xác nhận của Volume. |
| **`score_trend`** | **`1.5`** | Các đường EMA (9, 20, 50) xếp chồng lên nhau theo thứ tự Tăng (uptrend) hoặc Giảm (downtrend). |
| **`score_macd`** | **`1.5`** | Đường MACD cắt lên đường Signal (bullish) hoặc cắt xuống (bearish). |
| **`score_doji`** | **`1.5`** | Xuất hiện nến Doji đảo chiều mạnh (ví dụ: Dragonfly ở cuối downtrend). |
| **`score_cmf`** | **`1.0`** | Dòng tiền Chaikin (CMF) > `0.05` (dòng tiền vào) hoặc < `-0.05` (dòng tiền ra). |
| **`score_volume`** | **`1.0`** | Volume hiện tại > `1.8` lần Volume trung bình 20 nến (`vol_ma20`). |
| **`score_support_resistance`**| **`1.0`** | Giá tiến đến gần (trong phạm vi 2%) vùng Hỗ trợ (`+1.0`) hoặc Kháng cự (`-1.0`). |
| **`score_candle_pattern`**| **`1.0`** | Xuất hiện các mẫu nến nhấn chìm (Engulfing) ngược với xu hướng trước đó. |
| **`score_atr_vol`** | **`-1.0`** | **(Trừ điểm)** Biến động ATR quá lớn (`atr_percent` > 5.0%), tín hiệu rủi ro cao. |
| **`score_ema200`** | **`0.5`** | Cộng/trừ điểm nhẹ khi giá nằm trên/dưới đường EMA 200. |
| **`score_rsi_multi`** | **`0.5`** | RSI trên cả 1h và 4h đều đồng thuận mạnh (`>60` & `>55`) hoặc yếu (`<40` & `<45`). |
| **`score_adx`** | **`0.5`** | Cộng/trừ điểm nhẹ khi Trend mạnh (ADX > 25) hoặc yếu (ADX < 20). |
| **`score_bb`** | **`0.5`** | Cộng/trừ điểm nhẹ khi giá vượt ra ngoài dải Bollinger Band trên/dưới. |

---

## II. Trụ cột 2: Dự báo AI (Module `AI`)

**Linh hồn:** Hoạt động như một "Nhà Dự báo Thống kê", sử dụng bộ đôi mô hình LightGBM để dự báo xác suất hướng đi và biên độ biến động.

**Khung thời gian áp dụng:** 1h, 4h, 1d.

### Logic & Tham số Dự báo:

AI đưa ra 2 kết quả độc lập:

**1. Dự báo Hướng đi (Classifier):**
- **Mục tiêu:** Dự báo xác suất giá sẽ **Tăng**, **Giảm**, hay **Đi ngang**.
- **Ngưỡng tín hiệu "có ý nghĩa":** Một cú Tăng/Giảm chỉ được công nhận nếu nó lớn hơn `0.65` (1h), `0.75` (4h), hoặc `0.85` (1d) lần độ biến động trung bình (ATR).

**2. Dự báo Biên độ (Regressor):**
- **Mục tiêu:** Dự đoán mức độ thay đổi của giá (% so với giá hiện tại). Kết quả này có thể được dùng để tính TP/SL động.

### Quy tắc phiên dịch kết quả thành hành động (`ml_report.py -> classify_level`):

| Điều kiện | Nhãn Hành động |
| :--- | :--- |
| Xác suất Mua (pb) > `75%` | `STRONG_BUY` |
| Xác suất Mua (pb) > `65%` | `BUY` |
| Xác suất Mua (pb) > `55%` | `WEAK_BUY` |
| Xác suất Bán (ps) > `75%` | `PANIC_SELL` |
| Xác suất Bán (ps) > `65%` | `SELL` |
| Xác suất Bán (ps) > `55%` | `WEAK_SELL` |
| Biên độ dự đoán quá nhỏ | `HOLD` (có các cấp độ phụ) |
| Các trường hợp còn lại | `AVOID` (có các cấp độ phụ) |

---

## III. Trụ cột 3: Phân tích Bối cảnh (Module `Context & News`)

**Linh hồn:** Hoạt động như một "Bộ lọc Vĩ mô", đảm bảo các quyết định giao dịch không đi ngược lại bối cảnh chung của thị trường.

### Logic & Tham số:

**1. Xác định Trend Vĩ mô (`analyze_market_context_trend`):**
- Fear & Greed Index > `70` ➡️ Điểm Tăng `+1`
- Fear & Greed Index < `30` ➡️ Điểm Giảm `+1`
- BTC Dominance > `55` ➡️ Điểm Tăng `+1`
- BTC Dominance < `48` ➡️ Điểm Giảm `+1`
- **Kết quả:** `STRONG_UPTREND`, `UPTREND`, `STRONG_DOWNTREND`, `DOWNTREND`, `NEUTRAL`.

**2. Phân tích Tin tức (`rice_news.py`):**
- **Cơ chế hiện tại:** Phân loại tin tức theo mức độ quan trọng bằng các bộ từ khóa. Ví dụ: `CRITICAL` chứa `["will list", "etf approval", "halving", "fomc"]`.
- **Hướng nâng cấp:** Trong tương lai, cơ chế này sẽ được thay thế bằng LLM để phân tích ngữ nghĩa và sắc thái của tin tức, giúp nhận định sâu sắc và chính xác hơn.

---

## IV. Trụ cột 4: Thực thi & Quản lý (Module `Live Trade v8.0`)

**Linh hồn:** Một "Tổng Tư lệnh Chiến lược Thích ứng". Nó phân tích địa hình chiến trường (Vùng thị trường), sau đó lựa chọn vũ khí (chiến thuật) và phân bổ binh lực (vốn) phù hợp nhất.

### 1. Phân tích "Chiến trường" (`determine_market_zone_with_scoring`):

Hệ thống chấm điểm để xác định Vùng thị trường (`LEADING`, `COINCIDENT`, `LAGGING`, `NOISE`).

| Điều kiện Kích hoạt | Điểm Cộng | Vùng được cộng điểm |
| :--- | :--- | :--- |
| ADX < `20` | `+3` | `NOISE_ZONE` |
| BB Width < 20% percentile (100 nến) | `+2.5` | `LEADING_ZONE` |
| RSI điều chỉnh ngược trend lớn | `+2` | `LEADING_ZONE` |
| `breakout_signal` != "none" | `+3` | `COINCIDENT_ZONE` |
| `macd_cross` != "neutral" | `+2` | `COINCIDENT_ZONE` |
| ADX > `25` | `+2.5` | `LAGGING_ZONE` |
| `trend` != "sideway" | `+2` | `LAGGING_ZONE` |

### 2. Lựa chọn "Vũ khí" & "Binh lực" (`TACTICS_LAB` & `ZONE_BASED_POLICIES`):

Bot chọn chiến thuật có `OPTIMAL_ZONE` khớp với Vùng thị trường hiện tại và áp dụng chính sách vốn tương ứng.

**Ví dụ giải thích chi tiết tham số của chiến thuật `Breakout_Hunter`:**

| Tham số | Giá trị | Ý nghĩa & Cách Hoạt động |
| :--- | :--- | :--- |
| **`OPTIMAL_ZONE`** | `LEADING_ZONE` | Chỉ được kích hoạt trong Vùng Dẫn dắt. |
| **`WEIGHTS`** | `{'tech': 0.7, ...}` | Trọng số khi tính điểm tổng hợp, ưu tiên Tín hiệu Kỹ thuật (70%). |
| **`ENTRY_SCORE`** | `7.0` | Điểm tổng hợp cuối cùng phải >= 7.0 mới vào lệnh. |
| **`RR`** | `2.5` | Tỷ lệ Lời/Lỗ mục tiêu. `TP = Giá vào lệnh + (2.5 * Khoảng cách tới SL)`. |
| **`ATR_SL_MULTIPLIER`**| `1.8` | Khoảng cách `Stop Loss = 1.8 * giá trị ATR` tại thời điểm vào lệnh. |
| **`USE_TRAILING_SL`**| `True` | Kích hoạt tính năng dời Stop Loss tự động để gồng lời. |
| **`TRAIL_ACTIVATION_RR`**|`1.0`| Bắt đầu dời SL khi lợi nhuận đạt **1R** (giá đi được 1 lần khoảng cách SL). |
| **`TRAIL_DISTANCE_RR`**| `0.8` | Luôn giữ SL mới cách giá hiện tại một khoảng bằng **0.8R**. |
| **`ENABLE_PARTIAL_TP`**| `True`| Kích hoạt chốt lời một phần (TP1). |
| **`TP1_RR_RATIO`** | `1.0` | Chốt lời TP1 khi lợi nhuận đạt **1R**. |
| **`TP1_PROFIT_PCT`** | `0.5` | Chốt **50%** khối lượng vị thế tại TP1 và dời SL về điểm vào lệnh. |

### 3. "Phòng thủ" Vị thế (`ACTIVE_TRADE_MANAGEMENT_CONFIG`):

Khi một lệnh đã mở, nó được bảo vệ bởi 3 lớp phòng thủ tự động.

- **Phòng tuyến cuối cùng (`EARLY_CLOSE_ABSOLUTE_THRESHOLD: 4.8`):** Nếu điểm tín hiệu của lệnh đang mở tụt xuống dưới `4.8`, đóng **toàn bộ** lệnh ngay lập tức.
- **Tường lửa linh hoạt (`EARLY_CLOSE_RELATIVE_DROP_PCT: 0.27`):** Nếu điểm tín hiệu sụt giảm hơn `27%` so với điểm lúc vào lệnh, đóng **50%** vị thế để giảm rủi ro.
- **Chốt chặn lợi nhuận (`PROFIT_PROTECTION`):** Nếu lệnh đã từng lời tối thiểu `3.5%`, sau đó lợi nhuận bị sụt giảm đi `2.0%` từ đỉnh, bot sẽ tự động chốt **70%** vị thế để bảo vệ thành quả.
