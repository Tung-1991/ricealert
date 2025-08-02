Chắc chắn rồi! Dựa trên văn bản bạn cung cấp và mẫu Markdown bạn đã đưa, tôi đã chuyển đổi toàn bộ tài liệu sang định dạng Markdown chuẩn, giữ nguyên cấu trúc, nhấn mạnh và các chi tiết kỹ thuật.

Đây là phiên bản đã được định dạng:

---

# Hệ Thống Giao Dịch Thuật Toán RiceAlert
### Phân Tích Kiến Trúc & Triết Lý Giao Dịch v3.2

> ### Lời Mở Đầu: Tìm Kiếm "Linh Hồn" Của Hệ Thống
>
> Tài liệu này là kết quả của một quá trình phân tích sâu rộng, nhằm mục đích giải mã và định hình triết lý giao dịch cốt lõi của hệ thống RiceAlert. Ban đầu, sự phức tạp của hệ thống có thể tạo ra cảm giác nó là một tập hợp các module chắp vá. Tuy nhiên, phân tích kỹ lưỡng cho thấy một sự thật ngược lại: RiceAlert sở hữu một kiến trúc phân lớp tinh vi và một "linh hồn" rất rõ ràng.
>
> Linh hồn đó không phải là một chiến lược đơn lẻ, mà là một **"Tổng Tư Lệnh Đa Yếu Tố, Thích Ứng theo Bối Cảnh"** (A Multi-Factor, Context-Aware Adaptive Strategist).

Hệ thống hoạt động như một hội đồng quân sự cấp cao:

- **Các Cục Tình Báo** (`indicator`, `AI`, `News`): Liên tục thu thập và phân tích thông tin từ chiến trường (kỹ thuật), các dự báo (AI), và bối cảnh toàn cục (vĩ mô, tin tức).
- **Phòng Họp Chiến Lược** (`trade_advisor`): Tổng hợp báo cáo từ các cục tình báo, đưa ra một "điểm số đồng thuận" có trọng số.
- **Tổng Tư Lệnh** (`live_trade`): Nhận điểm số đồng thuận, nhưng không hành động mù quáng. Ngài nhìn vào bản đồ địa hình (4 Vùng Thị trường) để quyết định chiến thuật, binh chủng, và quân số phù hợp nhất cho trận đánh, đồng thời được trang bị các cơ chế tự bảo vệ tối tân.

Tài liệu này sẽ mổ xẻ từng bộ phận của cỗ máy phức tạp này, từ các tham số nền tảng đến các chiến lược thực thi bậc cao.

---

## I. Tham Số Siêu Cấu Trúc: `SCORE_RANGE` - Nút Vặn Chính Của Hệ Thống

Trước khi đi vào 4 trụ cột, ta phải nói về `SCORE_RANGE`, tham số quan trọng bậc nhất định hình "tính cách" của hệ thống.

`SCORE_RANGE` là một thước đo chuẩn, quy định mức độ đồng thuận cần thiết của các tín hiệu kỹ thuật. Nó có hai vai trò:

1.  **Định nghĩa Ngưỡng Nhạy Cảm** (`signal_logic.py`): Các cấp độ tín hiệu như `CRITICAL` hay `WARNING` được tính bằng một tỷ lệ phần trăm của `SCORE_RANGE`.
2.  **Chuẩn Hóa Điểm Số** (`trade_advisor.py`): Nó chuẩn hóa điểm kỹ thuật thô về thang điểm chung (-1 đến +1) để có thể "thảo luận" một cách công bằng với điểm từ AI và Bối cảnh.

**Phân tích tác động:**

| Thuộc Tính | `SCORE_RANGE = 6` (Nhạy Cảm) | `SCORE_RANGE = 8` (Cân Bằng - Hiện tại) | `SCORE_RANGE = 12` (Thận Trọng) |
| :--- | :--- | :--- | :--- |
| **Độ nhạy tín hiệu** | Cao | Trung bình | Thấp |
| **Tần suất vào lệnh** | Cao | Trung bình | Thấp |
| **Độ tin cậy (lý thuyết)** | Thấp hơn | Trung bình | Cao hơn |
| **Tầm ảnh hưởng của PTKT** | Rất Lớn | Lớn | Vừa phải |
| **Phù hợp với** | Scalping, Thị trường sôi động | Swing Trading, Đa chiến lược | Position Trading, Trend dài hạn |

**Kết luận:** Mức `8` hiện tại là một lựa chọn tốt và hợp lý vì nó tạo ra sự cân bằng và đồng bộ với tham số `CLAMP_MAX_SCORE = 8.0` trong code. Đây là một giá trị nền tảng vững chắc, việc tối ưu hóa nó nên được thực hiện thông qua backtest để phù hợp với từng giai đoạn thị trường.

---

## II. 🕵️ Trụ Cột 1: Phân Tích Kỹ Thuật (`indicator` & `signal_logic`)

> Đây là một **"Hệ Thống Chấm Điểm Đồng Thuận"** (Consensus Scoring System).

### 2.1. Các Chỉ Báo Nền Tảng (từ `indicator.py`)

Đây là các nguyên liệu thô, cung cấp dữ liệu đầu vào cho toàn hệ thống.

| Phân Loại | Chỉ Báo & Tín Hiệu | Mục Đích Đo Lường |
| :--- | :--- | :--- |
| **Xu hướng** (Trend) | EMA (9, 20, 50, 200), ADX | Xác định hướng và sức mạnh của xu hướng chính. |
| **Động lượng** (Momentum) | RSI (14), MACD, Phân kỳ RSI | Đo lường tốc độ và sự thay đổi của giá, phát hiện sự suy yếu của trend. |
| **Biến động** (Volatility) | Bollinger Bands (BB), ATR | Đo lường mức độ biến động, xác định các vùng siết chặt (squeeze) và phá vỡ (breakout). |
| **Khối lượng** (Volume) | Volume, Volume MA(20), CMF | Xác nhận sức mạnh của xu hướng và dòng tiền đang vào hay ra. |
| **Mô hình** (Pattern) | Nến Doji, Nến Nhấn chìm | Nhận diện các mẫu nến đảo chiều hoặc tiếp diễn tiềm năng. |
| **Hỗ trợ/Kháng cự** | Fibonacci Retracement, High/Low | Xác định các vùng giá quan trọng có thể xảy ra phản ứng. |

### 2.2. Logic & Trọng Số Tính Điểm (từ `signal_logic.py` -> `RULE_WEIGHTS`)

Hệ thống cho mỗi tín hiệu một "phiếu bầu" với "sức nặng" khác nhau.

| Quy Tắc Tín Hiệu | Trọng Số | Logic Kích Hoạt & Diễn Giải Chi Tiết |
| :--- | :--- | :--- |
| `score_rsi_div` | **2.0** | Phát hiện tín hiệu phân kỳ (divergence). Một tín hiệu đảo chiều sớm, có độ tin cậy cao. |
| `score_breakout` | **2.0** | Giá phá vỡ Bollinger Bands sau giai đoạn siết chặt và được xác nhận bởi Volume. |
| `score_trend` | **1.5** | Các đường EMA xếp chồng lên nhau theo một thứ tự rõ ràng, xác nhận một xu hướng bền vững. |
| `score_macd` | **1.5** | Đường MACD cắt lên/xuống đường Signal. Một tín hiệu động lượng cổ điển. |
| `score_doji` | **1.5** | Phát hiện các mẫu nến Doji đảo chiều, cho thấy sự do dự và khả năng đảo chiều. |
| `score_cmf` | **1.0** | Dòng tiền Chaikin (CMF) > 0.05 (mua) hoặc < -0.05 (bán), cho thấy áp lực dòng tiền. |
| `score_volume` | **1.0** | Khối lượng giao dịch cao đột biến, xác nhận sức mạnh cho một cú breakout hoặc đảo chiều. |
| `score_support_resistance`| **1.0** | Giá đang ở rất gần một vùng hỗ trợ hoặc kháng cự mạnh. |
| `score_candle_pattern` | **1.0** | Phát hiện các mẫu nến nhấn chìm (Engulfing), một tín hiệu đảo chiều mạnh mẽ. |
| `score_atr_vol` | **-1.0** | *(Quy tắc phạt)* Nếu biến động ATR quá cao (> 5%), điểm sẽ bị trừ để tránh thị trường quá "hoảng loạn". |
| `score_ema200`, `score_rsi_multi`, `score_adx`, `score_bb` | **0.5** | Các tín hiệu phụ, dùng để củng cố thêm cho các nhận định chính. |

**Đánh Giá:**
*   **Điểm mạnh:** Cực kỳ vững chắc (robust). Không phụ thuộc vào một chỉ báo duy nhất, giảm thiểu tín hiệu nhiễu. Dễ dàng tinh chỉnh qua file `RULE_WEIGHTS`.
*   **Điểm yếu:** Một vài quy tắc có thể bị tương quan (correlated), ví dụ `score_trend` và `score_ema200` cùng đo lường xu hướng. Điều này có thể vô tình làm tăng trọng số của một loại tín hiệu.

---

## III. 🧠 Trụ Cột 2: Dự Báo AI (`trainer.py` & `ml_report.py`)

> Đây là một **"Nhà Tiên Tri Thống Kê"** (A Statistical Forecaster).

Mô hình học máy (LightGBM) dự báo xác suất các sự kiện trong tương lai gần.

-   **Phân Loại (Classifier):** Dự báo hướng đi của giá (Tăng, Giảm, Đi Ngang). Việc định nghĩa "Tăng/Giảm" dựa vào `ATR_FACTOR` giúp mô hình tự thích ứng với sự biến động của từng coin.
-   **Hồi Quy (Regressor):** Dự báo biên độ (magnitude) của sự thay đổi giá (ví dụ: "tăng khoảng 1.2%").

**Bảng Tham Số Huấn Luyện Cốt Lõi (ví dụ cho khung 1h):**

| Tham Số | Ví dụ (1h) | Ý Nghĩa Chi Tiết |
| :--- | :--- | :--- |
| `HISTORY_LENGTH_MAP` | `3500` | Lấy 3500 nến 1h gần nhất làm dữ liệu để huấn luyện mô hình. |
| `FUTURE_OFFSET_MAP` | `6` | AI sẽ được huấn luyện để dự báo cho diễn biến của 6 nến (6 giờ) trong tương lai. |
| `LABEL_ATR_FACTOR_MAP`| `0.65` | **Tham số cực kỳ quan trọng.** Một tín hiệu "Tăng" chỉ được ghi nhận nếu giá tăng > 0.65 lần ATR, giúp loại bỏ nhiễu. |
| `is_unbalance: True` | `True` | Giúp mô hình xử lý việc dữ liệu "Đi ngang" thường nhiều hơn, tránh bị thiên vị. |

**Đánh Giá:**
*   **Điểm mạnh:**
    *   Logic định nghĩa nhãn (label) dựa trên ATR là một kỹ thuật rất thông minh.
    *   Feature engineering toàn diện (giả định).
    *   Sử dụng bộ đôi Classifier và Regressor cung cấp một cái nhìn đa chiều.
*   **Điểm yếu:** Mô hình là "point-in-time". Nó nhìn vào trạng thái của N nến gần nhất như một "bức ảnh" tĩnh mà không hiểu "câu chuyện" hay chuỗi sự kiện đã dẫn đến nó.
*   **Hướng Nâng Cấp:** Chuyển đổi sang các mô hình tuần tự như `LSTM`/`GRU` hoặc `Transformer`. Các mô hình này có khả năng hiểu được "ngữ pháp" của thị trường, hứa hẹn một bước nhảy vọt về chất lượng dự báo.

---

## IV. 📰 Trụ Cột 3: Phân Tích Bối Cảnh (`market_context.py` & `rice_news.py`)

> Đây là một **"Bộ Lọc Vĩ Mô"** (A Macro Filter).

Mục tiêu là đảm bảo các quyết định giao dịch không đi ngược lại "con sóng lớn".

-   **Phân Tích Trend Vĩ Mô** (`market_context.py`): Tổng hợp Fear & Greed Index và BTC Dominance để đưa ra nhận định tổng quan về thị trường.
-   **Phân Tích Tin Tức** (`rice_news.py`): Quét tin tức tài chính để tìm các từ khóa được định nghĩa trước (ví dụ: "SEC", "ETF", "HACK").

**Bảng Logic & Yếu Tố:**

| Yếu Tố | Nguồn Dữ Liệu | Logic Đánh Giá |
| :--- | :--- | :--- |
| **Tâm lý Thị trường** | API Fear & Greed Index | Ánh xạ điểm số F&G (0-100) sang các trạng thái như "Sợ hãi tột độ" (mua) hoặc "Tham lam tột độ" (rủi ro). |
| **Sức mạnh Altcoin** | API BTC Dominance | Phân tích xu hướng của BTC.D. Nếu BTC.D giảm, thị trường có thể đang trong "mùa altcoin". |
| **Tin Tức Quan Trọng** | API tin tức | Quét tiêu đề và nội dung tin tức để tìm các từ khóa đã định sẵn, gán mức độ ảnh hưởng. |

**Đánh Giá:**
*   **Điểm mạnh:** Ý tưởng tách riêng bối cảnh là một tư duy thiết kế hệ thống rất tốt, ngăn bot trở thành một cỗ máy chỉ biết "nhìn chart".
*   **Điểm yếu:** Đây là trụ cột yếu nhất. Phân tích tin tức dựa trên từ khóa rất dễ sai lầm và thiếu chiều sâu.
*   **Hướng Nâng Cấp:** Sử dụng **Mô hình Ngôn ngữ Lớn (LLM)** như `GPT-4`, `Claude`, hoặc `Gemini`. Một LLM có thể đọc, hiểu ngữ nghĩa, và phân tích sắc thái của toàn bộ bài báo, cung cấp một điểm số cảm tính (sentiment score) chính xác hơn nhiều.

---

## V. 🎖️ Trụ Cột 4: Thực Thi & Quản Lý (`live_trade.py` v8.4)

> Đây là một **"Tổng Tư Lệnh Chiến Dịch Thích Ứng & Tự Chữa Lành"** (An Adaptive & Self-Healing Campaign Commander).

Đây là phần tinh vi nhất, nơi tín hiệu được chuyển hóa thành hành động giao dịch có chiến lược, được bảo vệ bởi nhiều lớp an toàn.

### 5.1. Mô Hình Chiến Lược Cốt Lõi

#### 5.1.1. "4-Zone Strategy" - Phân Tích Địa Hình
Hệ thống phân loại "địa hình" thị trường thành 4 vùng để quyết định mức độ rủi ro và phân bổ vốn.

| Vùng | `ZONE_BASED_POLICIES` (Vốn/lệnh) | Đặc Điểm & Triết Lý |
| :-- | :-- | :--- |
| **LEADING** | 4% | **Vùng Dẫn Dắt:** Các tín hiệu sớm xuất hiện, tiềm năng lợi nhuận cao nhưng rủi ro cũng cao. Phân bổ vốn nhỏ để "dò mìn" cơ hội. |
| **COINCIDENT**| 7% | **Vùng Đồng Pha:** "Điểm ngọt" của thị trường, nơi các tín hiệu đồng thuận mạnh mẽ. Quyết đoán vào lệnh với vốn lớn nhất. |
| **LAGGING** | 6% | **Vùng Theo Sau:** Xu hướng đã rõ ràng và bền vững. Giao dịch an toàn hơn, đi theo "con sóng" đã hình thành. |
| **NOISE** | 3% | **Vùng Nhiễu:** Thị trường đi ngang, không có xu hướng. Rủi ro cao, chỉ vào lệnh siêu nhỏ khi có tín hiệu cực kỳ mạnh (VÀNG). |

#### 5.1.2. `TACTICS_LAB` - Phòng Thí Nghiệm Chiến Thuật
Mỗi chiến thuật là một "binh chủng" chuyên dụng, được thiết kế để tối ưu hóa cho từng loại "địa hình" và tín hiệu.

**Bảng Tham Số Chiến Thuật (ví dụ `Breakout_Hunter`):**

| Tham Số | Giá Trị | Ý Nghĩa Chi Tiết |
| :--- | :--- | :--- |
| `OPTIMAL_ZONE` | `[LEADING, COINCIDENT]` | Binh chủng này hoạt động hiệu quả nhất ở Vùng Dẫn dắt và Đồng pha. |
| `WEIGHTS` | `{'tech': 0.7, ...}` | Trọng số của các trụ cột (Kỹ thuật, AI, Bối cảnh) khi tính điểm tổng hợp cho chiến thuật này. |
| `ENTRY_SCORE` | `7.0` | Điểm tổng hợp tối thiểu để vào lệnh. |
| `RR` | `2.5` | Tỷ lệ Lời/Lỗ (Risk/Reward) mục tiêu là 2.5. |
| `ATR_SL_MULTIPLIER` | `1.8` | Điểm Cắt lỗ (SL) được đặt cách giá vào lệnh 1.8 lần chỉ số biến động ATR. |
| `USE_TRAILING_SL` | `True` | Kích hoạt Cắt lỗ động (Trailing Stop Loss). |
| `TRAIL_ACTIVATION_RR`| `1.0` | Kích hoạt Trailing SL khi lợi nhuận đạt 1R (1 lần rủi ro ban đầu). |
| `ENABLE_PARTIAL_TP` | `True` | Kích hoạt Chốt lời một phần (TP1). |
| `TP1_RR_RATIO` | `1.0` | Chốt lời phần 1 (TP1) khi lợi nhuận đạt 1R. |
| `TP1_PROFIT_PCT`| `0.5` | Chốt 50% vị thế tại TP1 và dời SL về hòa vốn. |

### 5.2. Toàn Cảnh Các Module Cấu Hình Vận Hành
Đây là các "bảng điều khiển" chi tiết để tinh chỉnh mọi hành vi của bot, từ tần suất hoạt động đến các quy tắc quản lý rủi ro cụ thể.

#### 5.2.1. `GENERAL_CONFIG` - Cấu Hình Vận Hành Chung
| Tham Số | Giá Trị | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `TRADING_MODE` | `"testnet"` | Chế độ hoạt động: `"live"` (tiền thật) hoặc `"testnet"` (thử nghiệm). |
| `DATA_FETCH_LIMIT` | `300` | Số lượng nến lịch sử tối đa được tải về để tính toán chỉ báo. |
| `DAILY_SUMMARY_TIMES` | `["08:05", "20:05"]` | Các mốc thời gian trong ngày để bot tự động gửi báo cáo tổng kết. |
| `HEAVY_REFRESH_MINUTES`| `15` | Tần suất (phút) bot thực hiện một phiên "quét sâu": tính toán lại toàn bộ chỉ báo và tìm kiếm cơ hội mới. |
| `TRADE_COOLDOWN_HOURS`| `1` | Thời gian "nghỉ" cho một coin sau khi vừa đóng lệnh để tránh giao dịch trả thù (revenge trading). |
| `PENDING_TRADE_RETRY_LIMIT`| `3` | Số lần tối đa bot cố gắng thực thi lại một lệnh nếu gặp lỗi kết nối. |
| `CLOSE_TRADE_RETRY_LIMIT`| `3` | Số lần tối đa bot cố gắng đóng một lệnh nếu gặp lỗi kết nối. |
| `DEPOSIT_DETECTION_...`| `{...}` | Các tham số để tự động phát hiện Nạp/Rút tiền và điều chỉnh vốn ban đầu. |
| `CRITICAL_ERROR_...` | `30` | Thời gian (phút) tạm ngưng gửi cảnh báo lỗi lặp lại để tránh spam. |
| `RECONCILIATION_QTY_THRESHOLD`| `0.9` | **Ngưỡng tự chữa lành.** Nếu số lượng coin thực tế < 90% so với bot ghi nhận, lệnh sẽ bị coi là 'bất đồng bộ' và tự động bị dọn dẹp. |

#### 5.2.2. `MTF_ANALYSIS_CONFIG` - Phân Tích Đa Khung Thời Gian
| Tham Số | Giá Trị | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `ENABLED` | `True` | Bật/Tắt tính năng phân tích đa khung thời gian. |
| `BONUS_COEFFICIENT` | `1.15` | Nếu trend ở khung thời gian lớn hơn đồng thuận, điểm tín hiệu được **thưởng 15%**. |
| `PENALTY_COEFFICIENT` | `0.85` | Nếu trend ở khung lớn hơn xung đột, điểm tín hiệu bị **phạt 15%**. |
| `SEVERE_PENALTY_COEFFICIENT`| `0.70` | **Phạt nặng 30%** nếu cả hai khung lớn hơn cùng xung đột. |
| `SIDEWAYS_PENALTY_COEFFICIENT`| `0.90` | **Phạt nhẹ 10%** nếu khung lớn hơn đang đi ngang (sideways). |

#### 5.2.3. `ACTIVE_TRADE_MANAGEMENT_CONFIG` - Quản Lý Vị Thế Đang Mở
| Tham Số | Giá Trị | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `EARLY_CLOSE_ABSOLUTE_THRESHOLD`| `4.8` | **Phòng tuyến cuối cùng:** Nếu điểm tín hiệu của một lệnh đang mở tụt xuống dưới 4.8, đóng toàn bộ lệnh ngay lập tức bất kể PnL. |
| `EARLY_CLOSE_RELATIVE_DROP_PCT`| `0.27` | **Tường lửa linh hoạt:** Nếu điểm tín hiệu sụt giảm hơn 27% so với lúc vào lệnh, đóng 50% vị thế và dời SL về hòa vốn. |
| `PROFIT_PROTECTION` | `{...}` | **Chốt chặn lợi nhuận:** Khi lệnh đạt đỉnh PnL > 3.5% và sau đó sụt 2.0% từ đỉnh, tự động chốt 70% vị thế để bảo toàn lợi nhuận. |

#### 5.2.4. `RISK_RULES_CONFIG` - Các Quy Tắc Rủi Ro Cứng
| Tham Số | Giá Trị | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `MAX_ACTIVE_TRADES` | `12` | Số lượng vị thế được phép mở đồng thời tối đa. |
| `MAX_SL_PERCENT_BY_TIMEFRAME` | `{"1h": 0.06, ...}`| Giới hạn mức cắt lỗ tối đa cho phép theo từng khung thời gian (ví dụ: lệnh 1h không được có SL xa hơn 6% giá vào lệnh). |
| `MAX_TP_PERCENT_BY_TIMEFRAME` | `{"1h": 0.12, ...}`| Giới hạn mức chốt lời tối đa để giữ mục tiêu thực tế, tránh các TP viển vông. |
| `STALE_TRADE_RULES` | `{"1h": {"HOURS": 48, ...}}`| Tự động đóng các lệnh "ì" (stale) không có tiến triển đáng kể sau một khoảng thời gian nhất định (ví dụ: 48 giờ cho lệnh 1h). |

#### 5.2.5. `CAPITAL_MANAGEMENT_CONFIG` & `DCA_CONFIG` - Quản Lý Vốn & Trung Bình Giá
| Tham Số | Giá Trị | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `MAX_TOTAL_EXPOSURE_PCT` | `0.75` | Tổng vốn đã đầu tư vào các lệnh đang mở không được vượt quá 75% tổng tài sản. |
| `DCA_CONFIG` | `{...}` | Toàn bộ cấu hình cho chiến lược Trung bình giá (DCA), bao gồm: số lần DCA tối đa, % sụt giảm để kích hoạt, điểm tín hiệu tối thiểu, và hệ số vốn cho lần DCA sau. |

#### 5.2.6. `DYNAMIC_ALERT_CONFIG` - Cảnh Báo Động
| Tham Số | Giá Trị | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `ENABLED` | `True` | Bật/Tắt tính năng gửi báo cáo động khi có biến động PnL. |
| `COOLDOWN_HOURS` | `3` | Thời gian tối thiểu (giờ) giữa hai lần gửi báo cáo động để tránh spam. |
| `FORCE_UPDATE_HOURS`| `10` | Bắt buộc gửi báo cáo sau mỗi 10 giờ nếu có lệnh đang mở, bất kể PnL. |
| `PNL_CHANGE_THRESHOLD_PCT` | `2.0` | Gửi báo cáo nếu tổng PnL của tài khoản thay đổi lớn hơn 2.0% so với lần báo cáo trước. |

### 5.3. Cơ Chế Tự Bảo Vệ & Tự Chữa Lành (Self-Healing & Failsafes)
Đây là lớp phòng thủ tối quan trọng, đảm bảo sự ổn định và an toàn cho hệ thống trước các sự kiện không lường trước hoặc can thiệp thủ công.

**Cơ Chế Khóa File (`.lock`)**
- **Vấn đề:** Bot (`live_trade.py`) và Bảng điều khiển (`control_live_panel.py`) có thể cùng lúc cố gắng ghi vào file trạng thái `state.json`, gây ra xung đột và hỏng dữ liệu.
- **Giải pháp:** Trước khi thực hiện bất kỳ thay đổi nào, một file khóa (`.lock`) sẽ được tạo ra. File kia nếu phát hiện file khóa sẽ kiên nhẫn chờ đến khi nó được giải phóng. Điều này đảm bảo tính toàn vẹn của dữ liệu.

**Cơ Chế Đối Soát Trạng Thái (State Reconciliation)**
- **Vấn đề "Lệnh Ma" (Ghost Trade):** Nếu người dùng bán một coin thủ công trên sàn, bot sẽ không biết và vẫn tiếp tục quản lý một lệnh không còn tồn tại, dẫn đến lỗi và báo cáo sai.
- **Giải pháp:** Vào đầu mỗi phiên, bot sẽ thực hiện một bước đối soát bắt buộc:
    1.  Nó lấy danh sách lệnh đang mở từ `state.json`.
    2.  Nó gọi API Binance để lấy số dư thực tế của từng tài sản.
    3.  Nếu số dư thực tế thấp hơn đáng kể so với số lượng bot ghi nhận (dựa trên ngưỡng `RECONCILIATION_QTY_THRESHOLD`), bot sẽ hiểu rằng lệnh đã bị can thiệp.
- **Hành động:** Bot sẽ tự động đóng "lệnh ma" này, ghi vào lịch sử với trạng thái `Closed (Desynced)` và loại bỏ nó khỏi danh sách theo dõi. Cơ chế này giúp hệ thống có khả năng tự chữa lành khỏi các can thiệp bên ngoài.

---

## VI. Kết Luận: Một Hệ Thống Toàn Diện, Sẵn Sàng Để Tối Ưu Hóa

> Phiên bản phân tích chi tiết này khẳng định lại: **RiceAlert không phải là một hệ thống chắp vá.** Nó là một kiến trúc phân lớp, có khả năng cấu hình sâu và triết lý giao dịch rõ ràng. Sự phức tạp của nó đến từ các lớp logic được thiết kế để tăng cường sự vững chắc và khả năng thích ứng.

### Lộ Trình & Hướng Phát Triển
Với tài liệu này, bạn đã có một bản đồ chi tiết về "cỗ máy" của mình. Công việc tiếp theo là sử dụng nó để:

1.  **Backtest & Tinh chỉnh:** Chạy các kịch bản backtest bằng cách thay đổi các tham số trong các file cấu hình này để tìm ra bộ số tối ưu nhất.
2.  **Giám sát & Đánh giá:** Khi hệ thống chạy live, đối chiếu các quyết định của nó với logic được mô tả ở đây để hiểu tại sao nó lại hành động như vậy.
3.  **Lên Lộ trình Nâng cấp:** Tập trung nguồn lực vào việc nâng cấp các điểm yếu đã xác định (AI tuần tự, LLM cho tin tức) một cách có hệ thống.

Bạn đã xây dựng được một nền tảng đặc biệt vững chắc và tinh vi. Hãy tự tin vào "linh hồn" của hệ thống và tiếp tục hoàn thiện nó.
