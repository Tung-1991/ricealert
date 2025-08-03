rice_alert_analysis_document: |
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
  

---

## IV. Phần 4: Thực Thi & Quản Lý Rủi Ro (live_trade.py v8.6.1)

Đây là module trung tâm, kiến trúc quản lý giao dịch và rủi ro nâng cao. Nó chuyển hóa tín hiệu từ các bộ phân tích thành hành động giao dịch thực tế trên thị trường, được bảo vệ bởi nhiều lớp an toàn và tự động hóa thông minh.

### 4.1. Mô Hình Chiến Lược Cốt Lõi: "4-Zone Strategy"

Hệ thống phân loại "địa hình" thị trường thành 4 vùng để quyết định mức độ rủi ro và phân bổ vốn một cách linh hoạt.

| Vùng | `ZONE_BASED_POLICIES` (Vốn/lệnh) | Đặc Điểm & Triết Lý Vận Hành |
| :-- | :-- | :--- |
| **LEADING** | **5.5%** Vốn BĐ | **Vùng Tiên Phong:** Các tín hiệu sớm, tiềm năng cao, rủi ro cao. Phân bổ vốn nhỏ để "dò mìn" và nắm bắt cơ hội từ giai đoạn đầu. |
| **COINCIDENT**| **6.5%** Vốn BĐ | **Vùng Trùng Hợp:** "Điểm ngọt" của thị trường, nơi các yếu tố kỹ thuật và bối cảnh đồng thuận mạnh mẽ. Vào lệnh với vốn lớn nhất, quyết đoán. |
| **LAGGING** | **6.0%** Vốn BĐ | **Vùng Trễ:** Xu hướng đã được xác nhận và rõ ràng. Giao dịch an toàn hơn, đi theo "con sóng" đã hình thành. |
| **NOISE** | **5.0%** Vốn BĐ | **Vùng Nhiễu:** Thị trường đi ngang, không có xu hướng rõ ràng. Rủi ro cao, chỉ vào lệnh với tín hiệu cực mạnh (điểm số cao) và vốn nhỏ nhất. |

### 4.2. FEATURE SPOTLIGHT: Động Cơ Vốn Năng Động (Dynamic Capital Engine - v8.6.1)

Đây là nâng cấp cốt lõi của phiên bản 8.6.1, biến bot từ một công cụ thực thi thành một hệ thống quản lý vốn bán tự trị.

**Mục tiêu:** Loại bỏ sự cần thiết phải can thiệp thủ công vào vốn hoạt động của bot. Hệ thống tự động điều chỉnh cơ sở vốn (`initial_capital`) dựa trên hiệu suất thực tế.

**Cơ Chế Hoạt Động:**
1.  **Phát Hiện Nạp/Rút Tiền:** Bot tự động phát hiện khi người dùng nạp hoặc rút tiền khỏi tài khoản và điều chỉnh `initial_capital` tương ứng để phản ánh đúng số vốn thực có.
2.  **Tự Động Tái Đầu Tư (Auto-Compounding):** Khi tổng tài sản (equity) tăng trưởng vượt một ngưỡng phần trăm nhất định, bot sẽ tự động nâng mức `initial_capital` lên bằng với tổng tài sản hiện tại. Điều này giúp tái đầu tư lợi nhuận và tăng quy mô vị thế một cách tự nhiên.
3.  **Tự Động Giảm Rủi Ro (Auto-Deleveraging):** Ngược lại, trong một giai đoạn sụt giảm (drawdown), nếu tổng tài sản giảm xuống dưới một ngưỡng, bot sẽ hạ `initial_capital` xuống. Hành động này nhằm mục đích giảm quy mô vị thế, bảo toàn vốn và hạn chế rủi ro trong giai đoạn thị trường bất lợi.
4.  **Thời Gian Chờ Điều Chỉnh (Cooldown):** Một khoảng thời gian chờ được áp dụng giữa các lần điều chỉnh vốn tự động để đảm bảo sự ổn định và tránh các thay đổi quá thường xuyên do biến động ngắn hạn.

**Bảng Tham Số Cấu Hình Động Cơ Vốn:**

| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `DEPOSIT_DETECTION_THRESHOLD_PCT` | `0.005` | Ngưỡng phát hiện Nạp/Rút (0.5% tổng tài sản). Bất kỳ thay đổi nào lớn hơn ngưỡng này sẽ kích hoạt điều chỉnh vốn. |
| `AUTO_COMPOUND_THRESHOLD_PCT` | `10.0` | **Tái đầu tư:** Nếu tổng tài sản tăng **10%** so với Vốn BĐ, Vốn BĐ sẽ được nâng lên mức tài sản mới. |
| `AUTO_DELEVERAGE_THRESHOLD_PCT` | `-10.0` | **Bảo toàn vốn:** Nếu tổng tài sản giảm **10%** so với Vốn BĐ, Vốn BĐ sẽ được hạ xuống mức tài sản mới. |
| `CAPITAL_ADJUSTMENT_COOLDOWN_HOURS`| `72` | Hệ thống sẽ chờ **72 giờ** giữa các lần tự động điều chỉnh vốn do hiệu suất (không áp dụng cho việc Nạp/Rút). |

### 4.3. Toàn Cảnh Các Module Cấu Hình Vận Hành

Các "bảng điều khiển" chi tiết để tinh chỉnh mọi khía cạnh hành vi của bot.

#### 4.3.1. `GENERAL_CONFIG` - Cấu Hình Vận Hành Chung

Đây là các tham số nền tảng, ảnh hưởng đến tần suất hoạt động, giới hạn và các quy tắc cơ bản.

| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `TRADING_MODE` | `"testnet"` | Chế độ hoạt động: `"live"` (tiền thật) hoặc `"testnet"` (thử nghiệm). |
| `HEAVY_REFRESH_MINUTES`| `15` | Tần suất (phút) bot "quét sâu": tính lại toàn bộ chỉ báo và tìm kiếm cơ hội giao dịch mới trên toàn thị trường. |
| `TRADE_COOLDOWN_HOURS`| `1` | Thời gian "nghỉ" cho một coin sau khi đóng lệnh để tránh giao dịch trả thù và chờ thị trường ổn định. |
| `OVERRIDE_COOLDOWN_SCORE`| `7.5` | Cho phép bot **phá vỡ thời gian nghỉ** nếu phát hiện một cơ hội có điểm tín hiệu cực cao (>= 7.5), đảm bảo không bỏ lỡ tín hiệu vàng. |
| `RECONCILIATION_QTY_THRESHOLD`| `0.95` | **Ngưỡng tự chữa lành.** Nếu số lượng coin thực tế < **95%** so với bot ghi nhận, lệnh sẽ bị coi là 'bất đồng bộ' (do can thiệp thủ công) và tự động dọn dẹp. |
| `ORPHAN_ASSET_MIN_VALUE_USDT`| `10.0` | **Vệ sinh tài khoản:** Tự động cảnh báo nếu phát hiện tài sản "mồ côi" (có trên sàn nhưng không được bot quản lý) trị giá trên 10 USD. |
| `MIN_ORDER_VALUE_USDT` | `11.0` | Giá trị lệnh tối thiểu (USD) để đặt lệnh, tuân thủ yêu cầu của sàn giao dịch. |

#### 4.3.2. `MTF_ANALYSIS_CONFIG` - Phân Tích Đa Khung Thời Gian

Gia tăng hoặc giảm thiểu độ tin cậy của một tín hiệu bằng cách đối chiếu với xu hướng ở các khung thời gian lớn hơn.

| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `ENABLED` | `True` | Bật/Tắt tính năng phân tích đa khung thời gian. |
| `BONUS_COEFFICIENT` | `1.15` | Nếu trend khung lớn hơn **đồng thuận**, điểm tín hiệu được **thưởng 15%**. |
| `PENALTY_COEFFICIENT` | `0.85` | Nếu trend khung lớn hơn **xung đột**, điểm tín hiệu bị **phạt 15%**. |
| `SEVERE_PENALTY_COEFFICIENT`| `0.70` | **Phạt nặng 30%** nếu cả hai khung lớn hơn cùng xung đột. |
| `SIDEWAYS_PENALTY_COEFFICIENT`| `0.90` | Phạt nhẹ 10% nếu khung lớn hơn đang đi ngang (sideways). |

#### 4.3.3. `ACTIVE_TRADE_MANAGEMENT_CONFIG` - Quản Lý Vị Thế Đang Mở

Các quy tắc linh hoạt để quản lý một lệnh sau khi đã được mở, nhằm tối ưu hóa lợi nhuận và giảm thiểu rủi ro.

| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `EARLY_CLOSE_ABSOLUTE_THRESHOLD`| `4.8` | **Phòng tuyến cuối cùng:** Nếu điểm tín hiệu của lệnh tụt dưới 4.8, đóng toàn bộ lệnh ngay lập tức để tránh thua lỗ nặng. |
| `EARLY_CLOSE_RELATIVE_DROP_PCT`| `0.27` | **Tường lửa linh hoạt:** Nếu điểm tín hiệu sụt giảm > **27%** so với lúc vào lệnh, đóng 50% vị thế và dời SL về hòa vốn. |
| `PROFIT_PROTECTION` | `{...}` | **Chốt chặn lợi nhuận:** Khi lệnh đạt đỉnh PnL > **3.5%** và sau đó sụt **2.0%** từ đỉnh, tự động chốt **70%** vị thế để bảo vệ thành quả. |

#### 4.3.4. `RISK_RULES_CONFIG` - Các Quy Tắc Rủi Ro Cứng

Các giới hạn không thể vi phạm để đảm bảo kỷ luật và kiểm soát rủi ro ở cấp độ danh mục.

| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `MAX_ACTIVE_TRADES` | `12` | Số lượng vị thế được phép mở đồng thời tối đa. |
| `MAX_SL_PERCENT_BY_TIMEFRAME` | `{"1h": 0.06, ...}`| Giới hạn mức cắt lỗ tối đa cho phép theo từng khung thời gian (lệnh 1h không có SL xa hơn 6% giá vào lệnh). |
| `STALE_TRADE_RULES` | `{"1h": {"HOURS": 48, ...}}`| Tự động đóng các lệnh "ì" (stale) không có tiến triển đáng kể sau một khoảng thời gian nhất định để giải phóng vốn cho cơ hội tốt hơn. |
| `STAY_OF_EXECUTION_SCORE`| `6.8` | **Ân xá:** Một lệnh "ì" sẽ không bị đóng nếu điểm tín hiệu hiện tại của nó vẫn còn tốt (>= 6.8). |

#### 4.3.5. `CAPITAL_MANAGEMENT_CONFIG` & `DCA_CONFIG` - Quản Lý Vốn & Trung Bình Giá

| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `MAX_TOTAL_EXPOSURE_PCT` | `0.75` | **Phanh an toàn tổng thể:** Tổng vốn đã đầu tư vào các lệnh đang mở không được vượt quá **75%** tổng tài sản USDT. |
| `DCA_CONFIG` | `{...}` | Toàn bộ cấu hình cho chiến lược Trung bình giá (DCA), bao gồm số lần DCA tối đa, % giá giảm để kích hoạt, và hệ số vốn cho mỗi lần DCA. |

#### 4.3.6. `DYNAMIC_ALERT_CONFIG` - Cảnh Báo Động

Cung cấp các cập nhật theo thời gian thực về hiệu suất danh mục, giúp người dùng nắm bắt tình hình mà không cần báo cáo thủ công.

| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `ENABLED` | `True` | Bật/Tắt tính năng gửi cập nhật động ra Discord. |
| `COOLDOWN_HOURS` | `3` | Thời gian chờ tối thiểu (3 giờ) giữa các lần gửi cập nhật để tránh spam. |
| `FORCE_UPDATE_HOURS`| `10` | Bắt buộc gửi một bản cập nhật sau mỗi 10 giờ, ngay cả khi không có thay đổi lớn. |
| `PNL_CHANGE_THRESHOLD_PCT` | `2.0` | Gửi cập nhật ngay lập tức nếu Tổng PnL của danh mục thay đổi lớn hơn hoặc bằng 2.0%. |

### 4.4. Cơ Chế Tự Bảo Vệ & Tự Chữa Lành (Self-Healing & Failsafes)

Các lớp phòng thủ được thiết kế để đảm bảo sự ổn định, an toàn và toàn vẹn dữ liệu cho hệ thống.

1.  **Cơ Chế Khóa File (`.lock`)**: Đảm bảo chỉ một tiến trình (bot hoặc control panel) có thể ghi vào file trạng thái `state.json` tại một thời điểm, ngăn chặn hoàn toàn nguy cơ hỏng dữ liệu.

2.  **Đối Soát Trạng Thái (State Reconciliation)**:
    *   **Vấn đề:** "Lệnh Ma" - người dùng đóng lệnh thủ công trên sàn, nhưng bot không biết và tiếp tục quản lý một lệnh không còn tồn tại.
    *   **Giải pháp:** Đầu mỗi phiên, bot so sánh số dư tài sản thực tế trên Binance với dữ liệu nó đang lưu trữ. Nếu số dư thực tế thấp hơn **95%** so với ghi nhận, bot sẽ coi lệnh đó đã bị can thiệp.
    *   **Hành động:** Tự động đóng "lệnh ma" với trạng thái `Closed (Desynced)`, ghi vào lịch sử và giải phóng tài nguyên.

3.  **Phát Hiện Tài Sản Mồ Côi (Orphan Asset Detection)**:
    *   **Vấn đề:** Các tài sản không được theo dõi (từ airdrop, nạp thủ công, giao dịch cũ) tồn tại trên tài khoản gây nhiễu loạn.
    *   **Giải pháp:** Bot chủ động quét các tài sản có giá trị trên `10 USD` mà không thuộc bất kỳ lệnh đang mở nào.
    *   **Hành động:** Gửi cảnh báo chi tiết đến Discord, yêu cầu người dùng xử lý (bán hoặc "nhận nuôi" bằng Control Panel), giữ cho danh mục luôn sạch sẽ và được kiểm soát.
  
  ## V. Kết Luận và Hướng Phát Triển
  
  Hệ thống RiceAlert được xây dựng trên một kiến trúc phân lớp, có khả năng cấu hình sâu và triết lý giao dịch rõ ràng. Sự phức tạp của nó đến từ các lớp logic được thiết kế để tăng cường sự vững chắc và khả năng thích ứng.
  
  **Lộ trình tiếp theo:**
  
  1.  **Backtest & Tinh chỉnh:** Chạy các kịch bản backtest bằng cách thay đổi các tham số trong file cấu hình để tìm ra bộ số tối ưu.
  2.  **Giám sát & Đánh giá:** Khi hệ thống chạy live, đối chiếu các quyết định của nó với logic được mô tả ở đây để hiểu và đánh giá hiệu quả.
  3.  **Nâng cấp:** Tập trung nguồn lực vào việc nâng cấp các điểm yếu đã xác định (AI tuần tự, LLM cho tin tức) một cách có hệ thống.
  
  Tài liệu này cung cấp một bản đồ chi tiết của hệ thống, là cơ sở cho các bước tối ưu hóa và phát triển tiếp theo.
