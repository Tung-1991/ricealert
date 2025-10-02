
# Hệ Thống Giao Dịch Thuật Toán RiceAlert
*(Hệ thống đã được nâng cấp lõi chiến lược lên phiên bản 9.2.0, tập trung vào giao dịch thích ứng theo ngữ cảnh thị trường. Các triết lý dưới đây đã được cập nhật đầy đủ và chi tiết.)*

## Phân Tích Kiến Trúc & Triết Lý Giao Dịch v9.2.0

### Lời Mở Đầu: Tìm Kiếm "Linh Hồn" Của Hệ Thống

Tài liệu này phân tích sâu về cấu trúc và triết lý giao dịch của hệ thống RiceAlert. Hệ thống ban đầu được thiết kế để lấy thông tin thị trường, giúp người trade giảm thụ động. Phiên bản mới đã tiến hóa thành một nhà chiến lược giao dịch thích ứng (An Adaptive, Context-Aware Strategist), với lõi là một quy trình ra quyết định đa tầng.

Logic của hệ thống không sử dụng các chỉ báo đơn lẻ, mà kết hợp với nguồn dữ liệu khác nhau, tổng hợp lại sau đó được thực hiện bằng một logic trade mô phỏng giống người nhất *"hệ thống không tạo ra để cạnh tranh, mà là để sống sót và có lãi thụ động"*.

Hệ thống hoạt động như một hội đồng quản trị có quy trình rõ ràng:

1.  **Phần 1: Nguồn tri thức (indicator, AI, News):** Thu thập, phân tích thông tin từ các chỉ báo kỹ thuật, dự báo AI, và bối cảnh vĩ mô, tin tức để tạo ra một **"điểm số gốc"**.
2.  **Phần 2: Phòng tổng hợp (trade\_advisor):** Tổng hợp các điểm thành phần thành một "điểm số đồng thuận" ban đầu.
3.  **Phần 3 (nay là Phần 4 trong `live_trade.py`):** Đây là phần được nâng cấp mạnh mẽ nhất. Nó không chỉ nhận điểm số đồng thuận, mà còn thực hiện một quy trình phân tích và ra quyết định phức tạp hơn nhiều, sẽ được trình bày chi tiết ở **Phần IV**.

Tài liệu này sẽ nói rõ chi tiết cách hoạt động của hệ thống nâng cấp này.

### **[THAY THẾ]** Tham Số Nền Tảng: Từ `SCORE_RANGE` đến Lõi Chiến Lược Thích Ứng

Trước đây, `SCORE_RANGE` là nút vặn chính định hình "tính cách" của hệ thống. **Trong phiên bản 9.2.0, khái niệm này đã được thay thế hoàn toàn** bằng một hệ thống ra quyết định và quản lý vốn linh hoạt hơn nhiều. "Tính cách" của bot giờ đây không còn phụ thuộc vào một con số cố định, mà được quyết định bởi sự kết hợp của **Mô Hình 4 Vùng Thị Trường** và **Phòng Thí Nghiệm Chiến Thuật (Tactics Lab)**. Cách tiếp cận mới này cho phép hệ thống tự động thay đổi hành vi—từ thận trọng đến quyết đoán—dựa trên bối cảnh thị trường thực tế.

---
## I. Phần 1: Phân Tích Kỹ Thuật (indicator & signal_logic)

Đây là hệ thống chấm điểm đồng thuận dựa trên nhiều chỉ báo kỹ thuật để tạo ra **"điểm số kỹ thuật" (technical score)**, một phần của "điểm số gốc".

### 1.1. Các Chỉ Báo Nền Tảng (từ `indicator.py`)

Đây là các nguyên liệu thô, cung cấp dữ liệu đầu vào cho toàn hệ thống.
*(Phần này không thay đổi, vẫn là nguyên liệu thô cho hệ thống.)*

| Phân Loại | Chỉ Báo & Tín Hiệu | Mục Đích Đo Lường |
| :--- | :--- | :--- |
| **Xu hướng (Trend)** | EMA (9, 20, 50, 200), ADX | Xác định hướng và sức mạnh của xu hướng chính. |
| **Động lượng (Momentum)**| RSI (14), MACD, Phân kỳ RSI | Đo lường tốc độ và sự thay đổi của giá, phát hiện sự suy yếu của trend. |
| **Biến động (Volatility)**| Bollinger Bands (BB), ATR | Đo lường mức độ biến động, xác định các vùng siết chặt (squeeze) và phá vỡ (breakout). |
| **Khối lượng (Volume)**| Volume, Volume MA(20), CMF | Xác nhận sức mạnh của xu hướng và dòng tiền đang vào hay ra. |
| **Mô hình (Pattern)**| Nến Doji, Nến Nhấn chìm | Nhận diện các mẫu nến đảo chiều hoặc tiếp diễn tiềm năng. |
| **Hỗ trợ/Kháng cự**| Fibonacci Retracement, High/Low | Xác định các vùng giá quan trọng có thể xảy ra phản ứng. |

### 1.2. Logic & Trọng Số Tính Điểm (từ `signal_logic.py` -> `RULE_WEIGHTS`)

Mỗi tín hiệu được gán một "phiếu bầu" với "sức nặng" khác nhau.
*(Logic tính điểm gốc không đổi, nhưng tầm quan trọng của nó giờ đây được điều chỉnh bởi các Tactic)*

| Quy Tắc Tín Hiệu | Trọng Số Gốc | Logic Kích Hoạt & Diễn Giải Chi Tiết |
| :--- | :--- | :--- |
| `score_rsi_div` | 2.0 | Phát hiện tín hiệu phân kỳ (divergence), một tín hiệu đảo chiều sớm. |
| `score_breakout` | 2.0 | Giá phá vỡ Bollinger Bands sau giai đoạn siết chặt, được xác nhận bởi Volume. |
| `score_trend` | 1.5 | Các đường EMA xếp chồng theo thứ tự rõ ràng, xác nhận xu hướng bền vững. |
| `score_macd` | 1.5 | Đường MACD cắt lên/xuống đường Signal. |
| `score_doji` | 1.5 | Phát hiện mẫu nến Doji, cho thấy sự do dự và khả năng đảo chiều. |
| `score_cmf` | 1.0 | Dòng tiền Chaikin (CMF) > 0.05 (mua) hoặc < -0.05 (bán). |
| `score_volume` | 1.0 | Khối lượng giao dịch cao đột biến, xác nhận sức mạnh cho breakout/đảo chiều. |
| `score_support_resistance` | 1.0 | Giá đang ở rất gần một vùng hỗ trợ hoặc kháng cự mạnh. |
| `score_candle_pattern` | 1.0 | Phát hiện các mẫu nến nhấn chìm (Engulfing). |
| `score_atr_vol` | -1.0 | (Quy tắc phạt) Nếu biến động ATR quá cao, điểm sẽ bị trừ để tránh thị trường quá "hoảng loạn". |
| `score_ema200`, `score_rsi_multi`, `score_adx`, `score_bb` | 0.5 | Các tín hiệu phụ, dùng để củng cố thêm cho các nhận định chính. |

**Đánh giá:**

*   **Ưu điểm:** Vững chắc (robust), không phụ thuộc vào một chỉ báo duy nhất, giảm thiểu tín hiệu nhiễu. Dễ tinh chỉnh qua file `RULE_WEIGHTS`.
*   **Nhược điểm:** Một vài quy tắc có thể tương quan. Việc sử dụng nhiều indicator sẽ khiến tính toán phức tạp dẫn tới việc bot vào lệnh chậm.
*   **Nâng cấp:** Thay vì một bộ trọng số cố định, hệ thống giờ đây có thể **thay đổi tầm quan trọng của PTKT** một cách linh hoạt. Ví dụ, `Breakout_Hunter` đặt trọng số `{'tech': 0.6, ...}`, ưu tiên cao cho tín hiệu kỹ thuật, trong khi `AI_Aggressor` chỉ đặt `{'tech': 0.3, ...}`.

---
## II. Phần 2: Dự Báo AI (`trainer.py` & `ml_report.py`)

*(Phần này không có thay đổi lớn trong file `live_trade.py`, vẫn giữ vai trò cung cấp một "điểm số AI" độc lập.)*

Mô hình học máy (LightGBM-LSTM-Tranformer) dự báo xác suất các sự kiện trong tương lai gần.

*   **Phân Loại (Classifier):** Dự báo hướng đi của giá (Tăng, Giảm, Đi Ngang). Việc định nghĩa "Tăng/Giảm" dựa vào `ATR_FACTOR` giúp mô hình tự thích ứng với biến động của từng coin.
*   **Hồi Quy (Regressor):** Dự báo biên độ (magnitude) của sự thay đổi giá (ví dụ: "tăng khoảng 1.2%").

**Bảng Tham Số Huấn Luyện Cốt Lõi (ví dụ cho khung 1h):**

| Tham Số | Ví dụ (1h) | Ý Nghĩa Chi Tiết |
| :--- | :--- | :--- |
| `HISTORY_LENGTH_MAP` | 3500 | Lấy 3500 nến 1h gần nhất làm dữ liệu huấn luyện. |
| `FUTURE_OFFSET_MAP` | 6 | Huấn luyện AI để dự báo diễn biến của 6 nến (6 giờ) trong tương lai. |
| `LABEL_ATR_FACTOR_MAP`| 0.65 | Tham số quan trọng. Tín hiệu "Tăng" chỉ được ghi nhận nếu giá tăng > 0.65 lần ATR, giúp loại bỏ nhiễu. |
| `is_unbalance: True` | True | Giúp mô hình xử lý việc dữ liệu "Đi ngang" thường nhiều hơn, tránh bị thiên vị. |

**Đánh giá:**
*   **Ưu điểm:** Logic định nghĩa nhãn (label) dựa trên ATR là một kỹ thuật hiệu quả. Feature engineering toàn diện (giả định). Sử dụng bộ đôi Classifier và Regressor cung cấp cái nhìn đa chiều.
*   **Nhược điểm:** Việc nâng cấp mới được diễn ra nó đã được backtest và cần thời gian chứng minh trên môi trường thật.

---
## III. Phần 3: Phân Tích Bối Cảnh Vĩ Mô (`market_context.py` & `rice_news.py`)

Module này hoạt động như một bộ lọc vĩ mô ban đầu, đảm bảo các quyết định giao dịch không đi ngược lại xu thế chung của toàn thị trường. Nó cung cấp một phần của "điểm số gốc".

*   **Phân Tích Trend Vĩ Mô (`market_context.py`):** Tổng hợp Fear & Greed Index và BTC Dominance để đưa ra nhận định tổng quan về thị trường.
*   **Phân Tích Tin Tức (`rice_news.py`):** Quét tin tức tài chính để tìm các từ khóa được định nghĩa trước (ví dụ: "SEC", "ETF", "HACK").

**Bảng Logic & Yếu Tố:**

| Yếu Tố | Nguồn Dữ Liệu | Logic Đánh Giá |
| :--- | :--- | :--- |
| **Tâm lý Thị trường** | API Fear & Greed Index | Ánh xạ điểm số F&G (0-100) sang các trạng thái như "Sợ hãi tột độ" (mua) hoặc "Tham lam tột độ" (rủi ro). |
| **Sức mạnh Altcoin** | API BTC Dominance | Phân tích xu hướng của BTC.D. Nếu BTC.D giảm, thị trường có thể đang trong "mùa altcoin". |
| **Tin Tức Quan Trọng** | API tin tức | Quét tiêu đề và nội dung để tìm các từ khóa đã định sẵn, gán mức độ ảnh hưởng. |

**Đánh giá:**
*   **Ưu điểm:** Ý tưởng tách riêng bối cảnh là một tư duy thiết kế tốt, ngăn bot chỉ "nhìn chart" một cách máy móc.
*   **Nhược điểm:** Đây là phần cần cải thiện nhiều nhất. Phân tích tin tức dựa trên từ khóa rất dễ sai lầm. Điểm trọng số phần này không được cao khi tính điểm.
*   **Hướng nâng cấp:** Sử dụng Mô hình Ngôn ngữ Lớn (LLM) để hiểu sâu sắc thái và ngữ nghĩa của tin tức.
*   **Lưu ý:** Các bộ lọc phân tích bối cảnh **thời gian thực** và **nâng cao hơn** (MTF, EZ, PAM) đã được chuyển vào **Phần IV** vì chúng là một phần của logic thực thi.

---
## IV. Phần 4: Thực Thi, Quản Lý Vốn & Rủi Ro (`live_trade.py` v9.2.0)

Đây là module trung tâm đã được nâng cấp mạnh mẽ nhất. Nó là bộ não thực thi, tích hợp các lớp logic mới để quản lý vốn và rủi ro một cách thông minh và linh hoạt, thay thế hoàn toàn hệ thống if-else đơn thuần trước đây.

### 4.1. **[NÂNG CẤP]** Lõi Chiến Lược Mới: Mô Hình 4 Vùng & Tactics Lab
Đây là trái tim của hệ thống mới, quyết định cách bot hành động.

#### 4.1.1. Mô Hình 4 Vùng Thị Trường (4-Zone Model)
"Bộ lọc vĩ mô" đầu tiên, phân loại thị trường để quyết định **mức độ rủi ro** và **phần trăm vốn** sẽ sử dụng.

| Vùng | Tên | Đặc Điểm | Chính Sách Vốn (`ZONE_BASED_POLICIES`) |
| :--- | :--- | :--- | :--- |
| **LEADING** | Tiên Phong | Thị trường đang tích lũy, siết chặt (squeeze), chuẩn bị cho một biến động mạnh. | **4.0%** Vốn (Dò mìn, cược vào tiềm năng) |
| **COINCIDENT** | Trùng Hợp | Biến động đang xảy ra (ví dụ: breakout). Xu hướng vừa mới bắt đầu. Vùng "ngọt ngào" nhất. | **5.0%** Vốn (Quyết đoán, phân bổ vốn cao nhất) |
| **LAGGING** | Trễ | Xu hướng đã rất rõ ràng, an toàn hơn để đi theo. | **6.0%** Vốn (An toàn, đi theo đám đông) |
| **NOISE** | Nhiễu | Thị trường đi ngang (sideways), không rõ xu hướng, biến động khó lường. | **3.0%** Vốn (Siêu cẩn thận, vốn siêu nhỏ) |

#### 4.1.2. Phòng Thí Nghiệm Chiến Thuật (Tactics Lab)
"Bộ não" chứa các "kế hoạch tác chiến". Bot sẽ chọn Tactic phù hợp với Vùng Thị Trường.

| Tên Tactic | Vùng Tối Ưu | Mô Tả & "Tính Cách" | Ngưỡng Điểm | RR | SL (xATR) |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **Balanced_Trader** | `LAGGING`, `COINCIDENT` | **Chiến binh chủ lực.** Gồng lệnh tốt, chấp nhận tín hiệu sớm, SL rộng để chịu được các đợt điều chỉnh. | 6.5 | 2.2 | 2.5x |
| **Breakout_Hunter** | `LEADING`, `COINCIDENT` | **Kẻ săn phá vỡ.** Vào lệnh ngay khi có breakout, SL rộng để sống sót qua cú retest. Yêu cầu động lượng mạnh. | 7.0 | 2.8 | 2.4x |
| **Dip_Hunter** | `LEADING`, `COINCIDENT` | **Bậc thầy bắt sóng hồi.** Bắt đáy/đỉnh với "lưới an toàn" SL cực rộng. Ăn nhanh, thoát nhanh. | 6.8 | 1.8 | 3.2x |
| **AI_Aggressor** | `COINCIDENT` | **Chuyên gia chớp nhoáng.** Dựa nhiều vào điểm AI, đánh nhanh, ăn ngắn, thoát nhanh với SL chặt hơn. | 6.8 | 2.0 | 2.2x |
| **Cautious_Observer**| `NOISE` | **Tay bắn tỉa.** Chỉ vào lệnh khi có cơ hội VÀNG trong vùng nhiễu. Ngưỡng điểm cực cao, SL chặt. | 7.5 | 2.0 | 1.8x |

### 4.2. **[NÂNG CẤP]** Các Bộ Lọc Điều Chỉnh Ngữ Cảnh Thời Gian Thực
Đây là các module mới trong `live_trade.py`, hoạt động như các "chuyên gia" tham vấn để điều chỉnh "điểm số gốc" thành "điểm số bối cảnh" trước khi ra quyết định cuối cùng.

| Bộ Lọc | Mục Đích | Logic Hoạt Động Chi Tiết | Cấu Hình (`live_trade.py`) |
| :--- | :--- | :--- | :--- |
| **Phân Tích Đa Khung (MTF)** | Tránh đi ngược xu hướng lớn. | **Phạt điểm** (`-3%` đến `-5%`) nếu tín hiệu 1h đi ngược trend 4h/1d. **Thưởng điểm nhẹ** (`+5%`) nếu tất cả cùng đồng thuận. Phạt nhẹ khi khung lớn đi ngang. | `MTF_ANALYSIS_CONFIG` |
| **Vùng Cực Đoan (EZ)** | Tránh FOMO ở đỉnh và bán tháo ở đáy. | **Phạt điểm** (lên tới `-10%`) khi mua ở vùng quá mua (RSI > 78, giá ở 98% trên của BB). **Thưởng điểm** (lên tới `+15%`) khi mua ở vùng quá bán. Tác động được **khuếch đại x1.25** khi có BB Squeeze. | `EXTREME_ZONE_ADJUSTMENT_CONFIG` |
| **Động Lượng Giá (PAM)** | Thưởng cho các tín hiệu có động lượng mạnh mẽ. | **Thưởng điểm** (lên tới `+10%`) nếu có chuỗi nến xanh, volume tăng, giá trên MA, và liên tục tạo đáy cao hơn trong `X` nến gần nhất. | `PRICE_ACTION_MOMENTUM_CONFIG` |
| **Xác Nhận Động Lượng** | Lớp "vệ sĩ" cuối cùng trước khi vào lệnh. | Yêu cầu `Y` trong số `X` nến gần nhất (VD: 3/5 nến) phải là "nến tốt" (xanh hoặc đỏ rút chân) thì lệnh mới được thông qua. | `MOMENTUM_FILTER_CONFIG` |

### 4.3. Luồng Hoạt Động Của Một Phiên (Session Flow)
*(Cập nhật để phản ánh logic mới)*

1.  **Khóa & Tải Trạng Thái:** Không đổi.
2.  **Đối Soát & Vệ Sinh:** Không đổi.
3.  **Tính Toán Equity & Quản Lý Vốn Năng Động:** Không đổi.
4.  **Quét & Phân Tích (Heavy Task):**
    *   Tải dữ liệu, tính toán lại toàn bộ chỉ báo.
    *   **Xác định Vùng Thị Trường** cho mỗi coin.
    *   **Tìm các Tactic phù hợp** với Vùng đó.
    *   **Tính điểm số gốc**, sau đó **áp dụng các bộ lọc MTF, EZ, PAM** để ra điểm số cuối cùng.
    *   So sánh điểm số cuối cùng với ngưỡng của Tactic và **áp dụng bộ lọc Xác Nhận Động Lượng**.
    *   Đưa cơ hội tốt nhất vào hàng chờ.
5.  **Thực Thi Lệnh Mới:** Nếu có cơ hội tiềm năng đang chờ, tiến hành thực thi.
6.  **Quản Lý Lệnh Đang Mở:** Liên tục kiểm tra các điều kiện SL/TP, Chốt lời sớm, Bảo vệ lợi nhuận, Trailing SL, DCA, và Lệnh "ì".
7.  **Báo Cáo & Lưu Trạng Thái:** Không đổi.

### 4.4. Trung Tâm Cấu Hình Vận Hành (Chi tiết v9.2.0)
Đây là bảng điều khiển chi tiết, nơi tinh chỉnh mọi khía cạnh hành vi của bot.

#### 4.4.1. GENERAL_CONFIG - Cấu Hình Vận Hành Chung
| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `TRADING_MODE` | `"live"` | Môi trường hoạt động: `"live"` (tiền thật) hoặc `"testnet"` (thử nghiệm). |
| `DATA_FETCH_LIMIT` | `300` | Số lượng nến lịch sử tải về để tính toán chỉ báo. |
| `DAILY_SUMMARY_TIMES`| `["08:10", "20:10"]` | Các mốc thời gian (giờ VN) bot gửi báo cáo tổng kết ra Discord. |
| `TRADE_COOLDOWN_HOURS`| `1.5` | **[Cập nhật]** Thời gian "nghỉ" 1.5 giờ cho một coin sau khi đóng lệnh. |
| `HEAVY_REFRESH_MINUTES`| `15` | Tần suất quét sâu để tìm cơ hội giao dịch mới. |
| `TOP_N_OPPORTUNITIES_TO_CHECK`| `7` | **[MỚI] Chống FOMO:** Xem xét 7 cơ hội tốt nhất thay vì vồ vập cơ hội đầu tiên. |
| `OVERRIDE_COOLDOWN_SCORE`| `7.5` | **Cơ hội vàng:** Cho phép phá vỡ thời gian nghỉ nếu điểm tín hiệu cực cao (>= 7.5). |

#### 4.4.2. ĐỘNG CƠ VỐN NĂNG ĐỘNG
| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `AUTO_COMPOUND_THRESHOLD_PCT` | `10.0` | Tự động tái đầu tư khi lãi > 10%. |
| `AUTO_DELEVERAGE_THRESHOLD_PCT`| `-10.0` | Tự động giảm rủi ro khi lỗ > 10%. |
| `CAPITAL_ADJUSTMENT_COOLDOWN_HOURS`| `48` | **[Cập nhật]** Thời gian chờ giữa các lần điều chỉnh vốn là 48 giờ. |

#### 4.4.3. ACTIVE_TRADE_MANAGEMENT_CONFIG - Quản Lý Vị Thế Đang Mở
| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `EARLY_CLOSE_ABSOLUTE_THRESHOLD` | `4.0` | **[Cập nhật]** Phòng tuyến cuối cùng: Đóng lệnh nếu điểm tín hiệu tụt xuống dưới 4.0. |
| `EARLY_CLOSE_RELATIVE_DROP_PCT` | `0.30` | **[Cập nhật]** Tường lửa linh hoạt: Nếu điểm tín hiệu sụt giảm > 30% so với lúc vào, đóng 40% vị thế. |
| `PROFIT_PROTECTION` | `{...}` | **[NÂNG CẤP] Lưới An Toàn Thích Ứng Theo Khung Thời Gian:** Ngưỡng kích hoạt và sụt giảm PnL giờ đây được **cấu hình riêng cho từng khung thời gian (1h, 4h, 1d)**, giúp bot kiên nhẫn hơn với các lệnh dài hạn. |

#### 4.4.4. RISK_RULES_CONFIG - Các Quy Tắc Rủi Ro Cứng
| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `MAX_ACTIVE_TRADES` | `7` | **[Cập nhật]** Số lượng vị thế được phép mở đồng thời tối đa giảm còn 7. |
| `MAX_SL_PERCENT_BY_TIMEFRAME` | `{"1h": 0.10, ...}`| **[Cập nhật]** Giới hạn mức cắt lỗ tối đa cho lệnh 1h là 10%. |
| `MIN_RISK_DIST_PERCENT_BY_TIMEFRAME`| `{"1h": 0.08, ...}`| **[MỚI] Sàn an toàn:** Đảm bảo mức cắt lỗ tối thiểu cho lệnh 1h là 8%, tránh SL quá gần. |
| `STALE_TRADE_RULES` | `{...}` | **[CẬP NHẬT] Module xử lý lệnh "ì" kiên nhẫn hơn:**<br>- Lệnh 1h, sau 72 giờ (thay vì 48h), nếu chưa đạt được 2% PnL, sẽ bị xem xét đóng. |
| `STAY_OF_EXECUTION_SCORE`| `6.5` | **[Cập nhật]** "Ân xá" cho lệnh "ì" nếu điểm tín hiệu hiện tại của nó vẫn tốt (>= 6.5). |

#### 4.4.5. CAPITAL_MANAGEMENT & DCA
| Module | Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- | :--- |
| **QUẢN LÝ VỐN** | `MAX_TOTAL_EXPOSURE_PCT` | `0.80` | **[Cập nhật]** Tổng vốn đã đầu tư không được vượt quá 80% tổng số USDT. |
| **TRUNG BÌNH GIÁ (DCA)** | `ENABLED` | `True` | Bật/Tắt chiến lược DCA. |
| | `TRIGGER_DROP_PCT_BY_TIMEFRAME`| `{"1h": -6.0, ...}` | **[NÂNG CẤP]** Kích hoạt DCA cho lệnh 1h khi giá giảm -6.0%. Ngưỡng được đặt riêng cho từng khung. |
| | `SCORE_MIN_THRESHOLD` | `6.5` | **DCA thông minh:** Chỉ DCA nếu điểm tín hiệu hiện tại vẫn đủ tốt. |
| | `CAPITAL_MULTIPLIER` | `0.5` | **[Cập nhật]** Vốn cho lần DCA chỉ bằng 50% vốn của lần vào lệnh trước. |

---
## V. Kết Luận và Hướng Phát Triển

Hệ thống RiceAlert được xây dựng trên một kiến trúc phân lớp, có khả năng cấu hình sâu và triết lý giao dịch rõ ràng. **Phiên bản v9.2.0 là một bước tiến lớn, chuyển từ một hệ thống dựa trên quy tắc đơn lẻ sang một cỗ máy giao dịch có khả năng nhận thức bối cảnh và thích ứng linh hoạt** với lõi là **Mô Hình 4 Vùng** và **Tactics Lab**.

**Lộ trình tiếp theo:**

*   **Backtest & Tinh chỉnh:** Chạy các kịch bản backtest bằng cách thay đổi các tham số trong `TACTICS_LAB` và các bộ lọc ngữ cảnh để tìm ra bộ số tối ưu cho từng loại thị trường.
*   **Giám sát & Đánh giá:** Khi hệ thống chạy live, đối chiếu các quyết định của nó với logic được mô tả ở đây để hiểu và đánh giá hiệu quả của từng chiến thuật.
*   **Nâng cấp:** Tập trung nguồn lực vào việc nâng cấp các điểm yếu đã xác định (Tối ưu indicator từ các chuyên gia, AI tuần tự, LLM cho tin tức) một cách có hệ thống.

---

## DRAFT về cấu hình tham số của live_trade (ĐÃ CẬP NHẬT LÊN PHIÊN BẢN 9.2.0)

*(Phần này được giữ lại với văn phong gốc để giải thích chi tiết các tham số)*

### PHẦN 1: CẤU HÌNH CƠ BẢN & VẬN HÀNH
*Đây là những cài đặt chung nhất, quyết định cách bot chạy và tương tác.*

*   **`TRADING_MODE: "live"`**: Chạy bằng tiền thật. Đổi thành `"testnet"` để thử nghiệm.
*   **`GENERAL_CONFIG` (Cấu hình chung)**
    *   `DATA_FETCH_LIMIT: 300`: Tải 300 nến gần nhất để tính toán.
    *   `DAILY_SUMMARY_TIMES: ["08:10", "20:10"]`: Giờ gửi báo cáo tổng kết ra Discord.
    *   `TRADE_COOLDOWN_HOURS: 1.5`: **(Cập nhật)** Sau khi đóng lệnh, coin đó sẽ nghỉ 1.5 giờ.
    *   `CRON_JOB_INTERVAL_MINUTES: 1`: Phải khớp với crontab của bạn (VD: `*/1 * * * *`).
    *   `HEAVY_REFRESH_MINUTES: 15`: Tần suất (phút) quét toàn bộ thị trường tìm cơ hội mới.
    *   `PENDING_TRADE_RETRY_LIMIT: 3`: Số lần thử lại tối đa nếu lệnh MUA thất bại.
    *   `CLOSE_TRADE_RETRY_LIMIT: 3`: Số lần thử lại tối đa nếu lệnh BÁN thất bại.
    *   `CRITICAL_ERROR_ALERT_COOLDOWN_MINUTES: 45`: Thời gian chờ trước khi báo lại lỗi nghiêm trọng giống nhau.
    *   `RECONCILIATION_QTY_THRESHOLD: 0.95`: Ngưỡng phát hiện lệnh bị đóng thủ công.
    *   `MIN_ORDER_VALUE_USDT: 11.0`: Giá trị lệnh tối thiểu của Binance.
    *   `OVERRIDE_COOLDOWN_SCORE: 7.5`: Điểm số đặc biệt để phá vỡ thời gian nghỉ.
    *   `ORPHAN_ASSET_MIN_VALUE_USDT: 10.0`: Cảnh báo tài sản "mồ côi" > 10$.
    *   `TOP_N_OPPORTUNITIES_TO_CHECK: 7`: **(Mới)** Chống FOMO, xem xét 7 cơ hội tốt nhất thay vì chỉ 1.
    *   `MOMENTUM_FILTER_CONFIG`: **(Mới)** Cấu hình cho "vệ sĩ gác cổng".

### PHẦN 2: QUẢN LÝ VỐN & RỦI RO
*Đây là các quy tắc về tiền bạc, cách bot bảo vệ vốn và tăng trưởng.*

*   **ĐỘNG CƠ VỐN NĂNG ĐỘNG (Trong `GENERAL_CONFIG`)**
    *   `DEPOSIT_DETECTION_MIN_USD: 10.0` & `_PCT: 0.01`: Cách bot nhận biết bạn nạp/rút tiền.
    *   `AUTO_COMPOUND_THRESHOLD_PCT: 10.0`: Tự độngทบ lãi khi tổng tài sản tăng 10%.
    *   `AUTO_DELEVERAGE_THRESHOLD_PCT: -10.0`: Tự động giảm rủi ro khi tổng tài sản giảm 10%.
    *   `CAPITAL_ADJUSTMENT_COOLDOWN_HOURS: 48`: **(Cập nhật)** Sau mỗi lần tự động điều chỉnh vốn, bot sẽ chờ 48 giờ.
*   **`RISK_RULES_CONFIG` (Luật Rủi Ro)**
    *   `MAX_ACTIVE_TRADES: 7`: **(Cập nhật)** Số lệnh tối đa được phép mở cùng lúc là 7.
    *   `MAX_SL_PERCENT_BY_TIMEFRAME`: **(Cập nhật)** Giới hạn cắt lỗ tối đa. Lệnh 1h không được có SL xa hơn 10%.
    *   `MAX_TP_PERCENT_BY_TIMEFRAME`: **(Cập nhật)** Giới hạn chốt lời tối đa. Lệnh 1h không được có TP xa hơn 15%.
    *   `MIN_RISK_DIST_PERCENT_BY_TIMEFRAME`: **(Mới)** Sàn an toàn cho SL, đảm bảo SL không bị đặt quá gần. Ví dụ lệnh 1h SL phải cách ít nhất 8%.
    *   `STALE_TRADE_RULES`: **(Cập nhật)** Xử lý lệnh "ì" kiên nhẫn hơn. Lệnh 1h giờ có 72 tiếng để thể hiện.
    *   `STAY_OF_EXECUTION_SCORE: 6.5`: **(Cập nhật)** "Ân xá" cho lệnh "ì" nếu điểm tín hiệu hiện tại vẫn trên 6.5.
*   **`CAPITAL_MANAGEMENT_CONFIG` (Quản lý vốn tổng thể)**
    *   `MAX_TOTAL_EXPOSURE_PCT: 0.80`: **(Cập nhật)** Phanh an toàn. Tổng vốn vào lệnh không vượt quá 80% số USDT hiện có.

### PHẦN 3: CHIẾN THUẬT GIAO DỊCH (TRÁI TIM CỦA BOT)
*Đây là phần cốt lõi, định nghĩa cách bot phân tích, ra quyết định và hành động.*

*   **CÁC BỘ LỌC NGỮ CẢNH (`MTF_ANALYSIS_CONFIG`, `EXTREME_ZONE_ADJUSTMENT_CONFIG`, `PRICE_ACTION_MOMENTUM_CONFIG`)**
    *   Các file config này điều chỉnh điểm số gốc. Ví dụ:
    *   **`MTF_ANALYSIS_CONFIG`**: Hệ số thưởng/phạt đã được điều chỉnh ôn hòa hơn (`1.05`, `0.95`, `0.93`).
    *   **`EXTREME_ZONE_ADJUSTMENT_CONFIG`**: Thưởng tối đa `+15%`, phạt tối đa `-10%`. Tác động được nhân `1.25` lần khi có BB Squeeze.
*   **4-ZONE MODEL (Mô hình 4 Vùng) & `ZONE_BASED_POLICIES` (Chính sách theo Vùng)**
    *   Bot chia thị trường làm 4 loại "thời tiết" và phân bổ vốn tương ứng:
        *   `LEADING_ZONE`: Dùng 4.0% vốn.
        *   `COINCIDENT_ZONE`: Dùng 5.0% vốn.
        *   `LAGGING_ZONE`: Dùng 6.0% vốn.
        *   `NOISE_ZONE`: Dùng 3.0% vốn.
*   **`TACTICS_LAB` (Thư viện các Chiến thuật)**
    *   Đây là "bộ não" của các chiến thuật. Mỗi chiến thuật có luật chơi riêng, ví dụ:
        *   **`Balanced_Trader`**:
            *   `OPTIMAL_ZONE`: `LAGGING`, `COINCIDENT`
            *   `ENTRY_SCORE: 6.5`
            *   `RR: 2.2`
            *   `ATR_SL_MULTIPLIER: 2.5`
            *   Sử dụng tất cả các bộ lọc ngữ cảnh.
        *   **`Dip_Hunter`**:
            *   `OPTIMAL_ZONE`: `LEADING`, `COINCIDENT`
            *   `ENTRY_SCORE: 6.8`
            *   `RR: 1.8` (Không tham lam)
            *   `ATR_SL_MULTIPLIER: 3.2` (Lưới an toàn cực rộng)
            *   **Không** dùng `MOMENTUM_FILTER` vì khi bắt đáy động lượng thường yếu.

### PHẦN 4: QUẢN LÝ LỆNH ĐANG MỞ & HÀNH ĐỘNG PHỤ

*   **`ACTIVE_TRADE_MANAGEMENT_CONFIG` (Quản lý lệnh đang mở)**
    *   `EARLY_CLOSE_ABSOLUTE_THRESHOLD: 4.0`: **(Cập nhật)** Nếu điểm tín hiệu tụt xuống dưới 4.0, đóng lệnh ngay.
    *   `EARLY_CLOSE_RELATIVE_DROP_PCT: 0.30`: **(Cập nhật)** Nếu điểm tín hiệu tụt 30%, bán 40% vị thế.
    *   **`PROFIT_PROTECTION`**: **(Nâng cấp)** Bảo vệ lợi nhuận thích ứng theo khung thời gian.
        *   **Lệnh 1h**: Kích hoạt ở `+1.5%` lãi, chốt lời nếu PnL sụt `0.75%` từ đỉnh.
        *   **Lệnh 4h**: Kích hoạt ở `+3.0%` lãi, chốt lời nếu PnL sụt `1.5%` từ đỉnh.
*   **`DCA_CONFIG` (Trung bình giá)**
    *   `ENABLED: True`: Bật/tắt tính năng DCA.
    *   `MAX_DCA_ENTRIES: 2`: Cho phép DCA tối đa 2 lần.
    *   `TRIGGER_DROP_PCT_BY_TIMEFRAME`: **(Nâng cấp)** Ngưỡng DCA theo từng khung giờ. Ví dụ 1h là `-6.0%`, 4h là `-8.0%`, 1d là `-10.0%`.
    *   `SCORE_MIN_THRESHOLD: 6.5`: Chỉ DCA nếu điểm tín hiệu hiện tại vẫn còn tốt.
    *   `CAPITAL_MULTIPLIER: 0.5`: **(Cập nhật)** Lần DCA sẽ dùng số vốn bằng 50% so với lần vào lệnh trước đó.
    *   `DCA_COOLDOWN_HOURS: 8`: Chờ ít nhất 8 tiếng giữa các lần DCA.
*   **`DYNAMIC_ALERT_CONFIG` & `ALERT_CONFIG` (Cảnh báo)**
    *   Các cài đặt để bot gửi thông báo cập nhật tình hình ra Discord, điều chỉnh tần suất để không bị spam.
