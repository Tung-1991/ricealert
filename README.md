# Hệ Thống Giao Dịch Thuật Toán RiceAlert
### Phân Tích Kiến Trúc & Triết Lý Giao Dịch v3.0

> ### Lời Mở Đầu: Tìm Kiếm "Linh Hồn" Của Hệ Thống
>
> Tài liệu này là kết quả của một quá trình phân tích sâu rộng, nhằm mục đích giải mã và định hình triết lý giao dịch cốt lõi của hệ thống RiceAlert. Ban đầu, sự phức tạp của hệ thống có thể tạo ra cảm giác nó là một tập hợp các module chắp vá. Tuy nhiên, phân tích kỹ lưỡng cho thấy một sự thật ngược lại: RiceAlert sở hữu một kiến trúc phân lớp tinh vi và một "linh hồn" rất rõ ràng.
>
> Linh hồn đó không phải là một chiến lược đơn lẻ, mà là một **"Tổng Tư Lệnh Đa Yếu Tố, Thích Ứng theo Bối Cảnh"** (A Multi-Factor, Context-Aware Adaptive Strategist).

Hệ thống hoạt động như một hội đồng quân sự cấp cao:

-   **Các Cục Tình Báo** (`indicator`, `AI`, `News`): Liên tục thu thập và phân tích thông tin từ chiến trường (kỹ thuật), các dự báo (AI), và bối cảnh toàn cục (vĩ mô, tin tức).
-   **Phòng Họp Chiến Lược** (`trade_advisor`): Tổng hợp báo cáo từ các cục tình báo, đưa ra một "điểm số đồng thuận" có trọng số.
-   **Tổng Tư Lệnh** (`live_trade`): Nhận điểm số đồng thuận, nhưng không hành động mù quáng. Ngài nhìn vào bản đồ địa hình (4 Vùng Thị trường) để quyết định chiến thuật, binh chủng, và quân số phù hợp nhất cho trận đánh.

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
| `score_support_resistance` | **1.0** | Giá đang ở rất gần một vùng hỗ trợ hoặc kháng cự mạnh. |
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

-   **Phân Loại (Classifier):** Dự báo hướng đi của giá (`Tăng`, `Giảm`, `Đi Ngang`). Việc định nghĩa "Tăng/Giảm" dựa vào `ATR_FACTOR` giúp mô hình tự thích ứng với sự biến động của từng coin.
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

## V. 🎖️ Trụ Cột 4: Thực Thi & Quản Lý (`live_trade.py` v8.0)

> Đây là một **"Tổng Tư Lệnh Chiến Dịch Thích Ứng"** (Adaptive Campaign Commander).

Đây là phần tinh vi nhất, nơi tín hiệu được chuyển hóa thành hành động giao dịch có chiến lược.

### 5.1. "4-Zone Strategy" & Phòng Thí Nghiệm Chiến Thuật (`TACTICS_LAB`)

Hệ thống phân tích "địa hình" và chọn "binh chủng" phù hợp.

1.  **Phân Tích "Địa Hình"** (`determine_market_zone_with_scoring`): Xác định thị trường đang ở 1 trong 4 Vùng:
    -   `LEADING`: Vùng tín hiệu sớm, rủi ro cao.
    -   `COINCIDENT`: Vùng "điểm ngọt", tín hiệu đồng pha.
    -   `LAGGING`: Vùng an toàn, đi theo trend đã rõ.
    -   `NOISE`: Vùng nhiễu, không xu hướng.
2.  **Lựa Chọn "Binh Chủng"** (`TACTICS_LAB`): Mỗi chiến thuật là một "binh chủng" chuyên dụng được thiết kế cho một "địa hình" (`OPTIMAL_ZONE`).
3.  **Phân Bổ "Quân Lực"** (`ZONE_BASED_POLICIES`): Phân bổ vốn linh động theo rủi ro của từng Vùng (ví dụ: 4% vốn ở `LEADING`, 7% ở `COINCIDENT`).

**Bảng Tham Số Chiến Thuật (ví dụ `Breakout_Hunter`):**

| Tham Số | Giá Trị | Ý Nghĩa Chi Tiết |
| :--- | :--- | :--- |
| `OPTIMAL_ZONE` | `[LEADING, COINCIDENT]` | Tối ưu cho Vùng Dẫn dắt và Đồng pha. |
| `ENTRY_SCORE` | `7.0` | Điểm tổng hợp tối thiểu để vào lệnh. |
| `RR` | `2.5` | Tỷ lệ Lời/Lỗ mục tiêu là 2.5. |
| `ATR_SL_MULTIPLIER`| `1.8` | Điểm Cắt lỗ (SL) được đặt cách giá vào lệnh 1.8 lần chỉ số ATR. |
| `TRAIL_ACTIVATION_RR`| `1.0` | Kích hoạt Trailing SL khi lợi nhuận đạt 1R. |
| `TP1_RR_RATIO` | `1.0` | Chốt lời phần 1 (TP1) khi lợi nhuận đạt 1R. |
| `TP1_PROFIT_PCT`| `0.5` | Chốt 50% vị thế tại TP1 và dời SL về hòa vốn. |

### 5.2. Các Module Cấu Hình Vận Hành & Rủi Ro

Đây là các "bảng điều khiển" chi tiết để tinh chỉnh hành vi của bot.

| Cấu Hình | Tham Số | Giá Trị | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- | :--- |
| **Vận Hành Chung** | `HEAVY_REFRESH_MINUTES` | `15` | Tần suất (phút) bot quét cơ hội mới và tính toán lại toàn bộ chỉ báo. |
| | `TRADE_COOLDOWN_HOURS` | `1` | Thời gian "nghỉ" cho một coin sau khi vừa đóng lệnh để tránh giao dịch trả thù. |
| **Phân Tích Đa Khung** | `BONUS_COEFFICIENT` | `1.15` | Nếu trend ở khung lớn hơn đồng thuận, điểm tín hiệu được thưởng 15%. |
| | `SEVERE_PENALTY_COEFFICIENT`| `0.70` | Phạt nặng 30% nếu cả hai khung lớn hơn cùng xung đột. |
| **Quản Lý Vị Thế** | `EARLY_CLOSE_ABSOLUTE_THRESHOLD`| `4.8` | *Phòng tuyến cuối cùng:* Nếu điểm tín hiệu của lệnh tụt dưới 4.8, đóng toàn bộ lệnh ngay lập tức. |
| | `EARLY_CLOSE_RELATIVE_DROP_PCT`| `0.27` | *Tường lửa linh hoạt:* Nếu điểm tín hiệu sụt giảm > 27% so với lúc vào, đóng 50% vị thế. |
| | `PROFIT_PROTECTION` | `{...}` | *Chốt chặn lợi nhuận:* Khi lệnh đạt đỉnh PnL > 3.5% và sau đó sụt 2.0%, tự động chốt 70% vị thế. |
| **Quản Lý Rủi Ro** | `MAX_ACTIVE_TRADES` | `12` | Số lượng vị thế mở đồng thời tối đa. |
| | `MAX_SL_PERCENT_BY_TIMEFRAME` | `{...}` | Giới hạn mức cắt lỗ tối đa cho phép theo từng khung thời gian (ví dụ: lệnh 1h không có SL xa hơn 6%). |
| | `STALE_TRADE_RULES` | `{...}` | Tự động đóng các lệnh "ì" (stale) không có tiến triển sau một khoảng thời gian nhất định. |
| **Quản Lý Vốn** | `MAX_TOTAL_EXPOSURE_PCT` | `0.75` | Tổng vốn trong các lệnh không được vượt quá 75% tổng tài sản. |
| | `DCA_CONFIG` | `{...}` | Kích hoạt Trung bình giá (DCA) khi lệnh âm 5.0% và điểm tín hiệu vẫn tốt (>6.5). |

---

## VI. Kết Luận: Một Hệ Thống Toàn Diện, Sẵn Sàng Để Tối Ưu Hóa

> Phiên bản phân tích chi tiết này khẳng định lại: **RiceAlert không phải là một hệ thống chắp vá.** Nó là một kiến trúc phân lớp, có khả năng cấu hình sâu và triết lý giao dịch rõ ràng. Sự phức tạp của nó đến từ các lớp logic được thiết kế để tăng cường sự vững chắc và khả năng thích ứng.

## Lộ Trình & Hướng Phát Triển

Với tài liệu này, bạn đã có một bản đồ chi tiết về "cỗ máy" của mình. Công việc tiếp theo là sử dụng nó để:

1.  **Backtest & Tinh chỉnh:** Chạy các kịch bản backtest bằng cách thay đổi các tham số trong các file cấu hình này để tìm ra bộ số tối ưu nhất.
2.  **Giám sát & Đánh giá:** Khi hệ thống chạy live, đối chiếu các quyết định của nó với logic được mô tả ở đây để hiểu tại sao nó lại hành động như vậy.
3.  **Lên Lộ trình Nâng cấp:** Tập trung nguồn lực vào việc nâng cấp các điểm yếu đã xác định (AI tuần tự, LLM cho tin tức) một cách có hệ thống.

Bạn đã xây dựng được một nền tảng đặc biệt vững chắc và tinh vi. Hãy tự tin vào "linh hồn" của hệ thống và tiếp tục hoàn thiện nó.
