---

# Hệ Thống Giao Dịch Thuật Toán RiceAlert
### Phân Tích Kiến Trúc & Triết Lý Giao Dịch v3.2

### Lời Mở Đầu: Tìm Kiếm "Linh Hồn" Của Hệ Thống

Tài liệu này phân tích sâu về cấu trúc và triết lý giao dịch của hệ thống RiceAlert. Mặc dù ban đầu có vẻ phức tạp, phân tích cho thấy RiceAlert có một kiến trúc phân lớp rõ ràng và một logic vận hành nhất quán.

Logic này không phải là một chiến lược đơn lẻ, mà là một **"Tổng Tư Lệnh Đa Yếu Tố, Thích Ứng theo Bối Cảnh"** (A Multi-Factor, Context-Aware Adaptive Strategist).

Hệ thống hoạt động như một hội đồng quân sự cấp cao:

-   **Các Cục Tình Báo** (`indicator`, `AI`, `News`): Thu thập, phân tích thông tin từ các chỉ báo kỹ thuật, dự báo AI, và bối cảnh vĩ mô, tin tức.
-   **Phòng Họp Chiến Lược** (`trade_advisor`): Tổng hợp báo cáo, đưa ra một "điểm số đồng thuận" có trọng số.
-   **Tổng Tư Lệnh** (`live_trade`): Nhận điểm số đồng thuận, kết hợp với phân tích "bản đồ địa hình" (4 Vùng Thị trường) để quyết định chiến thuật, phân bổ vốn và thực thi lệnh, đi kèm các cơ chế tự bảo vệ.

Tài liệu này sẽ mổ xẻ từng bộ phận của cỗ máy này.

---

### Tham Số Nền Tảng: `SCORE_RANGE` - Nút Vặn Chính Của Hệ Thống

Trước khi đi vào các phần chính, cần làm rõ về `SCORE_RANGE`, tham số quan trọng bậc nhất định hình "tính cách" của hệ thống.

`SCORE_RANGE` là một thước đo chuẩn, quy định mức độ đồng thuận cần thiết của các tín hiệu kỹ thuật. Nó có hai vai trò:

1.  **Định nghĩa Ngưỡng Nhạy Cảm** (`signal_logic.py`): Các cấp độ tín hiệu như `CRITICAL` hay `WARNING` được tính bằng một tỷ lệ phần trăm của `SCORE_RANGE`.
2.  **Chuẩn Hóa Điểm Số** (`trade_advisor.py`): Chuẩn hóa điểm kỹ thuật thô về thang điểm chung (-1 đến +1) để có thể so sánh công bằng với điểm từ AI và Bối cảnh.

**Phân tích tác động:**

| Thuộc Tính | `SCORE_RANGE = 6` (Nhạy Cảm) | `SCORE_RANGE = 8` (Cân Bằng - Hiện tại) | `SCORE_RANGE = 12` (Thận Trọng) |
| :--- | :--- | :--- | :--- |
| **Độ nhạy tín hiệu** | Cao | Trung bình | Thấp |
| **Tần suất vào lệnh** | Cao | Trung bình | Thấp |
| **Độ tin cậy (lý thuyết)** | Thấp hơn | Trung bình | Cao hơn |
| **Tầm ảnh hưởng của PTKT** | Rất Lớn | Lớn | Vừa phải |
| **Phù hợp với** | Scalping, Thị trường sôi động | Swing Trading, Đa chiến lược | Position Trading, Trend dài hạn |

**Kết luận:** Mức `8` hiện tại là một lựa chọn cân bằng, đồng bộ với tham số `CLAMP_MAX_SCORE = 8.0` trong code. Việc tối ưu hóa tham số này nên được thực hiện thông qua backtest để phù hợp với từng giai đoạn thị trường.

---

## I. Phần 1: Phân Tích Kỹ Thuật (indicator & signal_logic)

Đây là hệ thống chấm điểm đồng thuận dựa trên nhiều chỉ báo kỹ thuật.

### 1.1. Các Chỉ Báo Nền Tảng (từ `indicator.py`)

Đây là các nguyên liệu thô, cung cấp dữ liệu đầu vào cho toàn hệ thống.

| Phân Loại | Chỉ Báo & Tín Hiệu | Mục Đích Đo Lường |
| :--- | :--- | :--- |
| **Xu hướng** (Trend) | EMA (9, 20, 50, 200), ADX | Xác định hướng và sức mạnh của xu hướng chính. |
| **Động lượng** (Momentum) | RSI (14), MACD, Phân kỳ RSI | Đo lường tốc độ và sự thay đổi của giá, phát hiện sự suy yếu của trend. |
| **Biến động** (Volatility) | Bollinger Bands (BB), ATR | Đo lường mức độ biến động, xác định các vùng siết chặt (squeeze) và phá vỡ (breakout). |
| **Khối lượng** (Volume) | Volume, Volume MA(20), CMF | Xác nhận sức mạnh của xu hướng và dòng tiền đang vào hay ra. |
| **Mô hình** (Pattern) | Nến Doji, Nến Nhấn chìm | Nhận diện các mẫu nến đảo chiều hoặc tiếp diễn tiềm năng. |
| **Hỗ trợ/Kháng cự** | Fibonacci Retracement, High/Low | Xác định các vùng giá quan trọng có thể xảy ra phản ứng. |

### 1.2. Logic & Trọng Số Tính Điểm (từ `signal_logic.py` -> `RULE_WEIGHTS`)

Mỗi tín hiệu được gán một "phiếu bầu" với "sức nặng" khác nhau.

| Quy Tắc Tín Hiệu | Trọng Số | Logic Kích Hoạt & Diễn Giải Chi Tiết |
| :--- | :--- | :--- |
| `score_rsi_div` | **2.0** | Phát hiện tín hiệu phân kỳ (divergence), một tín hiệu đảo chiều sớm. |
| `score_breakout` | **2.0** | Giá phá vỡ Bollinger Bands sau giai đoạn siết chặt, được xác nhận bởi Volume. |
| `score_trend` | **1.5** | Các đường EMA xếp chồng theo thứ tự rõ ràng, xác nhận xu hướng bền vững. |
| `score_macd` | **1.5** | Đường MACD cắt lên/xuống đường Signal. |
| `score_doji` | **1.5** | Phát hiện mẫu nến Doji, cho thấy sự do dự và khả năng đảo chiều. |
| `score_cmf` | **1.0** | Dòng tiền Chaikin (CMF) > 0.05 (mua) hoặc < -0.05 (bán). |
| `score_volume` | **1.0** | Khối lượng giao dịch cao đột biến, xác nhận sức mạnh cho breakout/đảo chiều. |
| `score_support_resistance`| **1.0** | Giá đang ở rất gần một vùng hỗ trợ hoặc kháng cự mạnh. |
| `score_candle_pattern` | **1.0** | Phát hiện các mẫu nến nhấn chìm (Engulfing). |
| `score_atr_vol` | **-1.0** | *(Quy tắc phạt)* Nếu biến động ATR quá cao (> 5%), điểm sẽ bị trừ để tránh thị trường quá "hoảng loạn". |
| `score_ema200`, `score_rsi_multi`, `score_adx`, `score_bb` | **0.5** | Các tín hiệu phụ, dùng để củng cố thêm cho các nhận định chính. |

**Đánh giá:**
-   **Ưu điểm:** Vững chắc (robust), không phụ thuộc vào một chỉ báo duy nhất, giảm thiểu tín hiệu nhiễu. Dễ tinh chỉnh qua file `RULE_WEIGHTS`.
-   **Nhược điểm:** Một vài quy tắc có thể tương quan (correlated), ví dụ `score_trend` và `score_ema200` cùng đo lường xu hướng, có thể vô tình làm tăng trọng số của một loại tín hiệu.

---

## II. Phần 2: Dự Báo AI (trainer.py & ml_report.py)

Mô hình học máy (LightGBM) dự báo xác suất các sự kiện trong tương lai gần.

-   **Phân Loại (Classifier):** Dự báo hướng đi của giá (Tăng, Giảm, Đi Ngang). Việc định nghĩa "Tăng/Giảm" dựa vào `ATR_FACTOR` giúp mô hình tự thích ứng với biến động của từng coin.
-   **Hồi Quy (Regressor):** Dự báo biên độ (magnitude) của sự thay đổi giá (ví dụ: "tăng khoảng 1.2%").

**Bảng Tham Số Huấn Luyện Cốt Lõi (ví dụ cho khung 1h):**

| Tham Số | Ví dụ (1h) | Ý Nghĩa Chi Tiết |
| :--- | :--- | :--- |
| `HISTORY_LENGTH_MAP` | `3500` | Lấy 3500 nến 1h gần nhất làm dữ liệu huấn luyện. |
| `FUTURE_OFFSET_MAP` | `6` | Huấn luyện AI để dự báo diễn biến của 6 nến (6 giờ) trong tương lai. |
| `LABEL_ATR_FACTOR_MAP`| `0.65` | **Tham số quan trọng.** Tín hiệu "Tăng" chỉ được ghi nhận nếu giá tăng > 0.65 lần ATR, giúp loại bỏ nhiễu. |
| `is_unbalance: True` | `True` | Giúp mô hình xử lý việc dữ liệu "Đi ngang" thường nhiều hơn, tránh bị thiên vị. |

**Đánh giá:**
-   **Ưu điểm:** Logic định nghĩa nhãn (label) dựa trên ATR là một kỹ thuật hiệu quả. Feature engineering toàn diện (giả định). Sử dụng bộ đôi Classifier và Regressor cung cấp cái nhìn đa chiều.
-   **Nhược điểm:** Mô hình là "point-in-time", nó nhìn vào trạng thái N nến gần nhất như một "bức ảnh" tĩnh mà không hiểu "câu chuyện" hay chuỗi sự kiện dẫn đến nó.
-   **Hướng nâng cấp:** Chuyển sang các mô hình tuần tự như `LSTM`/`GRU` hoặc `Transformer`. Các mô hình này có khả năng hiểu được ngữ cảnh thời gian của thị trường, có thể cải thiện chất lượng dự báo.

---

## III. Phần 3: Phân Tích Bối Cảnh (market_context.py & rice_news.py)

Module này hoạt động như một bộ lọc vĩ mô, đảm bảo các quyết định giao dịch không đi ngược lại xu thế chung.

-   **Phân Tích Trend Vĩ Mô** (`market_context.py`): Tổng hợp Fear & Greed Index và BTC Dominance để đưa ra nhận định tổng quan về thị trường.
-   **Phân Tích Tin Tức** (`rice_news.py`): Quét tin tức tài chính để tìm các từ khóa được định nghĩa trước (ví dụ: "SEC", "ETF", "HACK").

**Bảng Logic & Yếu Tố:**

| Yếu Tố | Nguồn Dữ Liệu | Logic Đánh Giá |
| :--- | :--- | :--- |
| **Tâm lý Thị trường** | API Fear & Greed Index | Ánh xạ điểm số F&G (0-100) sang các trạng thái như "Sợ hãi tột độ" (mua) hoặc "Tham lam tột độ" (rủi ro). |
| **Sức mạnh Altcoin** | API BTC Dominance | Phân tích xu hướng của BTC.D. Nếu BTC.D giảm, thị trường có thể đang trong "mùa altcoin". |
| **Tin Tức Quan Trọng** | API tin tức | Quét tiêu đề và nội dung để tìm các từ khóa đã định sẵn, gán mức độ ảnh hưởng. |

**Đánh giá:**
-   **Ưu điểm:** Ý tưởng tách riêng bối cảnh là một tư duy thiết kế tốt, ngăn bot chỉ "nhìn chart" một cách máy móc.
-   **Nhược điểm:** Đây là phần cần cải thiện nhiều nhất. Phân tích tin tức dựa trên từ khóa rất dễ sai lầm, thiếu chiều sâu.
-   **Hướng nâng cấp:** Sử dụng **Mô hình Ngôn ngữ Lớn (LLM)** như `GPT-4`, `Claude`, hoặc `Gemini`. LLM có thể đọc, hiểu ngữ nghĩa, phân tích sắc thái của toàn bộ bài báo để cung cấp điểm số cảm tính (sentiment score) chính xác hơn.

---

## IV. Phần 4: Thực Thi & Quản Lý Rủi Ro (live_trade.py v8.4)

Đây là module trung tâm, nơi tín hiệu được chuyển hóa thành hành động giao dịch, được bảo vệ bởi nhiều lớp an toàn.

### 4.1. Mô Hình Chiến Lược Cốt Lõi

#### 4.1.1. "4-Zone Strategy" - Phân Tích Địa Hình
Hệ thống phân loại "địa hình" thị trường thành 4 vùng để quyết định mức độ rủi ro và phân bổ vốn.

| Vùng | `ZONE_BASED_POLICIES` (Vốn/lệnh) | Đặc Điểm & Triết Lý |
| :-- | :-- | :--- |
| **LEADING** | 4% | **Vùng Dẫn Dắt:** Các tín hiệu sớm, tiềm năng cao, rủi ro cao. Phân bổ vốn nhỏ để "dò mìn". |
| **COINCIDENT**| 7% | **Vùng Đồng Pha:** "Điểm ngọt" của thị trường, tín hiệu đồng thuận mạnh. Vào lệnh với vốn lớn nhất. |
| **LAGGING** | 6% | **Vùng Theo Sau:** Xu hướng đã rõ ràng. Giao dịch an toàn hơn, đi theo "con sóng" đã hình thành. |
| **NOISE** | 3% | **Vùng Nhiễu:** Thị trường đi ngang, không xu hướng. Rủi ro cao, chỉ vào lệnh siêu nhỏ với tín hiệu cực mạnh. |

#### 4.1.2. `TACTICS_LAB` - Phòng Thí Nghiệm Chiến Thuật
Mỗi chiến thuật là một "binh chủng" chuyên dụng, được thiết kế để tối ưu hóa cho từng loại "địa hình" và tín hiệu.

**Bảng Tham Số Chiến Thuật (ví dụ `Breakout_Hunter`):**

| Tham Số | Giá Trị | Ý Nghĩa Chi Tiết |
| :--- | :--- | :--- |
| `OPTIMAL_ZONE` | `[LEADING, COINCIDENT]` | Hoạt động hiệu quả nhất ở Vùng Dẫn dắt và Đồng pha. |
| `WEIGHTS` | `{'tech': 0.7, ...}` | Trọng số của các phần (Kỹ thuật, AI, Bối cảnh) khi tính điểm tổng hợp cho chiến thuật này. |
| `ENTRY_SCORE` | `7.0` | Điểm tổng hợp tối thiểu để vào lệnh. |
| `RR` | `2.5` | Tỷ lệ Lời/Lỗ (Risk/Reward) mục tiêu. |
| `ATR_SL_MULTIPLIER` | `1.8` | Cắt lỗ (SL) đặt cách giá vào lệnh 1.8 lần chỉ số biến động ATR. |
| `USE_TRAILING_SL` | `True` | Kích hoạt Cắt lỗ động (Trailing Stop Loss). |
| `TRAIL_ACTIVATION_RR`| `1.0` | Kích hoạt Trailing SL khi lợi nhuận đạt 1R. |
| `ENABLE_PARTIAL_TP` | `True` | Kích hoạt Chốt lời một phần (TP1). |
| `TP1_RR_RATIO` | `1.0` | Chốt lời phần 1 (TP1) khi lợi nhuận đạt 1R. |
| `TP1_PROFIT_PCT`| `0.5` | Chốt 50% vị thế tại TP1 và dời SL về hòa vốn. |

### 4.2. Toàn Cảnh Các Module Cấu Hình Vận Hành

Các "bảng điều khiển" chi tiết để tinh chỉnh hành vi của bot.

#### 4.2.1. `GENERAL_CONFIG` - Cấu Hình Vận Hành Chung
| Tham Số | Giá Trị | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `TRADING_MODE` | `"testnet"` | Chế độ hoạt động: `"live"` (tiền thật) hoặc `"testnet"` (thử nghiệm). |
| `HEAVY_REFRESH_MINUTES`| `15` | Tần suất (phút) bot "quét sâu": tính lại toàn bộ chỉ báo và tìm cơ hội mới. |
| `TRADE_COOLDOWN_HOURS`| `1` | Thời gian "nghỉ" cho một coin sau khi đóng lệnh để tránh revenge trading. |
| `RECONCILIATION_QTY_THRESHOLD`| `0.9` | **Ngưỡng tự chữa lành.** Nếu số lượng coin thực tế < 90% so với bot ghi nhận, lệnh sẽ bị coi là 'bất đồng bộ' và tự động dọn dẹp. |

#### 4.2.2. `MTF_ANALYSIS_CONFIG` - Phân Tích Đa Khung Thời Gian
| Tham Số | Giá Trị | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `ENABLED` | `True` | Bật/Tắt tính năng phân tích đa khung thời gian. |
| `BONUS_COEFFICIENT` | `1.15` | Nếu trend khung lớn hơn đồng thuận, điểm tín hiệu được **thưởng 15%**. |
| `PENALTY_COEFFICIENT` | `0.85` | Nếu trend khung lớn hơn xung đột, điểm tín hiệu bị **phạt 15%**. |
| `SEVERE_PENALTY_COEFFICIENT`| `0.70` | **Phạt nặng 30%** nếu cả hai khung lớn hơn cùng xung đột. |

#### 4.2.3. `ACTIVE_TRADE_MANAGEMENT_CONFIG` - Quản Lý Vị Thế Đang Mở
| Tham Số | Giá Trị | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `EARLY_CLOSE_ABSOLUTE_THRESHOLD`| `4.8` | **Phòng tuyến cuối cùng:** Nếu điểm tín hiệu của lệnh tụt dưới 4.8, đóng toàn bộ lệnh ngay lập tức. |
| `EARLY_CLOSE_RELATIVE_DROP_PCT`| `0.27` | **Tường lửa linh hoạt:** Nếu điểm tín hiệu sụt giảm > 27% so với lúc vào lệnh, đóng 50% vị thế và dời SL về hòa vốn. |
| `PROFIT_PROTECTION` | `{...}` | **Chốt chặn lợi nhuận:** Khi lệnh đạt đỉnh PnL > 3.5% và sau đó sụt 2.0% từ đỉnh, tự động chốt 70% vị thế. |

#### 4.2.4. `RISK_RULES_CONFIG` - Các Quy Tắc Rủi Ro Cứng
| Tham Số | Giá Trị | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `MAX_ACTIVE_TRADES` | `12` | Số lượng vị thế được phép mở đồng thời tối đa. |
| `MAX_SL_PERCENT_BY_TIMEFRAME` | `{"1h": 0.06, ...}`| Giới hạn mức cắt lỗ tối đa cho phép theo khung thời gian (lệnh 1h không có SL xa hơn 6%). |
| `STALE_TRADE_RULES` | `{"1h": {"HOURS": 48, ...}}`| Tự động đóng các lệnh "ì" (stale) không có tiến triển sau một khoảng thời gian nhất định. |

#### 4.2.5. `CAPITAL_MANAGEMENT_CONFIG` & `DCA_CONFIG` - Quản Lý Vốn & Trung Bình Giá
| Tham Số | Giá Trị | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `MAX_TOTAL_EXPOSURE_PCT` | `0.75` | Tổng vốn đầu tư vào các lệnh đang mở không vượt quá 75% tổng tài sản. |
| `DCA_CONFIG` | `{...}` | Toàn bộ cấu hình cho chiến lược Trung bình giá (DCA). |

### 4.3. Cơ Chế Tự Bảo Vệ & Tự Chữa Lành (Self-Healing & Failsafes)

Lớp phòng thủ đảm bảo sự ổn định và an toàn cho hệ thống.

**Cơ Chế Khóa File (`.lock`)**
-   **Vấn đề:** Bot (`live_trade.py`) và Bảng điều khiển (`control_live_panel.py`) có thể cùng lúc ghi vào file `state.json`, gây hỏng dữ liệu.
-   **Giải pháp:** Trước khi thay đổi, một file khóa (`.lock`) được tạo ra. Tiến trình kia sẽ chờ đến khi file được giải phóng, đảm bảo tính toàn vẹn dữ liệu.

**Cơ Chế Đối Soát Trạng Thái (State Reconciliation)**
-   **Vấn đề "Lệnh Ma" (Ghost Trade):** Người dùng bán coin thủ công trên sàn, bot không biết và tiếp tục quản lý một lệnh không còn tồn tại.
-   **Giải pháp:** Đầu mỗi phiên, bot đối soát bắt buộc: so sánh danh sách lệnh trong `state.json` với số dư thực tế trên sàn. Nếu số dư thực tế thấp hơn đáng kể (dựa trên ngưỡng `RECONCILIATION_QTY_THRESHOLD`), bot hiểu rằng lệnh đã bị can thiệp.
-   **Hành động:** Bot tự động đóng "lệnh ma", ghi vào lịch sử với trạng thái `Closed (Desynced)` và loại bỏ khỏi danh sách theo dõi.

---

## VI. Kết Luận và Hướng Phát Triển

Hệ thống RiceAlert được xây dựng trên một kiến trúc phân lớp, có khả năng cấu hình sâu và triết lý giao dịch rõ ràng. Sự phức tạp của nó đến từ các lớp logic được thiết kế để tăng cường sự vững chắc và khả năng thích ứng.

**Lộ trình tiếp theo:**

1.  **Backtest & Tinh chỉnh:** Chạy các kịch bản backtest bằng cách thay đổi các tham số trong file cấu hình để tìm ra bộ số tối ưu.
2.  **Giám sát & Đánh giá:** Khi hệ thống chạy live, đối chiếu các quyết định của nó với logic được mô tả ở đây để hiểu và đánh giá hiệu quả.
3.  **Nâng cấp:** Tập trung nguồn lực vào việc nâng cấp các điểm yếu đã xác định (AI tuần tự, LLM cho tin tức) một cách có hệ thống.

Tài liệu này cung cấp một bản đồ chi tiết của hệ thống, là cơ sở cho các bước tối ưu hóa và phát triển tiếp theo.
