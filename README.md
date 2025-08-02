Chắc chắn rồi. Tôi hiểu rằng bạn muốn có một tài liệu cuối cùng, duy nhất, tổng hợp tất cả những gì chúng ta đã thảo luận. Đây sẽ là phiên bản đầy đủ và chi tiết nhất, một "kim chỉ nam" thực sự cho hệ thống RiceAlert.

Hãy cùng nhau hoàn thiện nó.

***

# Hệ Thống Giao Dịch RiceAlert: Phân Tích Toàn Diện v3.0 (Bản Cuối Cùng)

## Lời Mở Đầu: Tìm Kiếm "Linh Hồn" Của Hệ Thống

Tài liệu này là kết quả của một quá trình phân tích sâu rộng, nhằm mục đích giải mã và định hình triết lý giao dịch cốt lõi của hệ thống **RiceAlert**. Ban đầu, sự phức tạp của hệ thống có thể tạo ra cảm giác nó là một tập hợp các module chắp vá. Tuy nhiên, phân tích kỹ lưỡng cho thấy một sự thật ngược lại: `RiceAlert` sở hữu một kiến trúc phân lớp tinh vi và một "linh hồn" rất rõ ràng.

Linh hồn đó không phải là một chiến lược đơn lẻ, mà là một **"Tổng Tư Lệnh Đa Yếu Tố, Thích Ứng theo Bối Cảnh" (A Multi-Factor, Context-Aware Adaptive Strategist)**.

Hệ thống hoạt động như một hội đồng quân sự cấp cao:
1.  **Các Cục Tình Báo (`Indicator`, `AI`, `News`):** Liên tục thu thập và phân tích thông tin từ chiến trường (kỹ thuật), các dự báo (AI), và bối cảnh toàn cục (vĩ mô, tin tức).
2.  **Phòng Họp Chiến Lược (`trade_advisor`):** Tổng hợp báo cáo từ các cục tình báo, đưa ra một "điểm số đồng thuận" có trọng số.
3.  **Tổng Tư Lệnh (`live_trade`):** Nhận điểm số đồng thuận, nhưng không hành động mù quáng. Ngài nhìn vào bản đồ địa hình (4 Vùng Thị trường) để quyết định chiến thuật, binh chủng, và quân số phù hợp nhất cho trận đánh.

Tài liệu này sẽ mổ xẻ từng bộ phận của cỗ máy phức tạp này, từ các tham số nền tảng đến các chiến lược thực thi bậc cao.

---

## I. Tham Số Siêu Cấu Trúc: `SCORE_RANGE` - Nút Vặn Chính Của Hệ Thống

Trước khi đi vào 4 trụ cột, ta phải nói về `SCORE_RANGE`, tham số **quan trọng bậc nhất** định hình "tính cách" của hệ thống.

`SCORE_RANGE` là một thước đo chuẩn, quy định mức độ đồng thuận cần thiết của các tín hiệu kỹ thuật. Nó có hai vai trò:

1.  **Định nghĩa Ngưỡng Nhạy Cảm (`signal_logic.py`):** Các cấp độ tín hiệu như `CRITICAL` hay `WARNING` được tính bằng một *tỷ lệ phần trăm* của `SCORE_RANGE`.
2.  **Chuẩn Hóa Điểm Số (`trade_advisor.py`):** Nó chuẩn hóa điểm kỹ thuật thô về thang điểm chung (-1 đến +1) để có thể "thảo luận" một cách công bằng với điểm từ AI và Bối cảnh.

**Phân tích tác động:**

| Thuộc Tính | `SCORE_RANGE = 6` (Nhạy Cảm) | `SCORE_RANGE = 8` (Cân Bằng - Hiện tại) | `SCORE_RANGE = 12` (Thận Trọng) |
| :--- | :--- | :--- | :--- |
| **Độ nhạy tín hiệu** | Cao | Trung bình | Thấp |
| **Tần suất vào lệnh** | Cao | Trung bình | Thấp |
| **Độ tin cậy (lý thuyết)**| Thấp hơn | Trung bình | Cao hơn |
| **Tầm ảnh hưởng của PTKT**| **Rất Lớn** | **Lớn** | **Vừa phải** |
| **Phù hợp với** | Scalping, Thị trường sôi động | Swing Trading, Đa chiến lược | Position Trading, Trend dài hạn |

**Kết luận:** Mức **`8`** hiện tại là một lựa chọn **tốt và hợp lý** vì nó tạo ra sự cân bằng và đồng bộ với tham số `CLAMP_MAX_SCORE = 8.0` trong code. Đây là một giá trị nền tảng vững chắc, việc tối ưu hóa nó nên được thực hiện thông qua backtest để phù hợp với từng giai đoạn thị trường.

---

## II. Trụ Cột 1: Phân Tích Kỹ Thuật (Module `Indicator` & `Signal`)

* **Linh Hồn:** 🕵️ Một **"Hệ Thống Chấm Điểm Đồng Thuận" (Consensus Scoring System)**.

#### 1.1. Các Chỉ Báo Nền Tảng (từ `indicator.py`)

Đây là các nguyên liệu thô, cung cấp dữ liệu đầu vào cho toàn hệ thống.

| Phân Loại | Chỉ Báo & Tín Hiệu | Mục Đích Đo Lường |
| :--- | :--- | :--- |
| **Xu hướng (Trend)** | EMA (9, 20, 50, 200), ADX | Xác định hướng và sức mạnh của xu hướng chính. |
| **Động lượng (Momentum)**| RSI (14), MACD, Phân kỳ RSI | Đo lường tốc độ và sự thay đổi của giá, phát hiện sự suy yếu của trend. |
| **Biến động (Volatility)**| Bollinger Bands (BB), ATR | Đo lường mức độ biến động, xác định các vùng siết chặt (squeeze) và phá vỡ (breakout). |
| **Khối lượng (Volume)**| Volume, Volume MA(20), CMF | Xác nhận sức mạnh của xu hướng và dòng tiền đang vào hay ra. |
| **Mô hình (Pattern)** | Nến Doji, Nến Nhấn chìm | Nhận diện các mẫu nến đảo chiều hoặc tiếp diễn tiềm năng. |
| **Hỗ trợ/Kháng cự** | Fibonacci Retracement, High/Low gần nhất | Xác định các vùng giá quan trọng có thể xảy ra phản ứng. |

#### 1.2. Logic & Trọng Số Tính Điểm (`signal_logic.py -> RULE_WEIGHTS`)

Hệ thống cho mỗi tín hiệu một "phiếu bầu" với "sức nặng" khác nhau. Điểm số cuối cùng phản ánh mức độ đồng thuận.

| Quy Tắc Tín Hiệu | Trọng Số |
| :--- | :---: |
| `score_rsi_div`, `score_breakout` | **2.0** |
| `score_trend`, `score_macd`, `score_doji` | **1.5** |
| `score_cmf`, `score_volume`, `score_support_resistance`, `score_candle_pattern` | **1.0** |
| `score_atr_vol` (Quy tắc phạt) | **-1.0** |
| Các quy tắc phụ trợ khác | **0.5** |

* **Đánh Giá:**
    * **Điểm mạnh:** Cực kỳ vững chắc (robust), không phụ thuộc vào một chỉ báo duy nhất.
    * **Điểm yếu:** Một vài quy tắc có thể bị tương quan (correlated), cần được xem xét khi tinh chỉnh trọng số.

---

## III. Trụ Cột 2: Dự Báo AI (Module `Trainer` & `ML_Report`)

* **Linh Hồn:** 🤖 Một **"Nhà Tiên Tri Thống Kê" (Statistical Forecaster)**.

#### 2.1. Kiến Trúc & Tham Số Huấn Luyện (`trainer.py`)

Sử dụng bộ đôi mô hình LightGBM để dự báo **hướng đi** (Classifier) và **biên độ** (Regressor).

| Tham Số | Ví Dụ (1h) | Ý Nghĩa |
| :--- | :--- | :--- |
| `HISTORY_LENGTH_MAP` | `3500` | Số lượng nến quá khứ dùng để huấn luyện. |
| `FUTURE_OFFSET_MAP` | `6` | Tầm nhìn dự báo của AI (ví dụ: 6 nến tương lai). |
| `LABEL_ATR_FACTOR_MAP`| `0.65` | Một tín hiệu "Tăng" chỉ được ghi nhận nếu giá tăng > 0.65 lần ATR, giúp thích ứng với biến động. |
| `is_unbalance: True` | `True` | Tham số quan trọng, giúp mô hình xử lý việc dữ liệu "Đi ngang" thường nhiều hơn "Tăng/Giảm". |

* **Đánh Giá:**
    * **Điểm mạnh:** Logic định nghĩa nhãn dựa trên ATR rất thông minh. Feature engineering toàn diện.
    * **Điểm yếu:** Mô hình là "point-in-time", chưa hiểu được chuỗi sự kiện (sequence).
    * **Hướng Nâng Cấp:** Nâng cấp lên các mô hình tuần tự như **LSTM/Transformer** là bước đi tự nhiên.

---

## IV. Trụ Cột 3: Phân Tích Bối Cảnh (Module `Context` & `News`)

* **Linh Hồn:** 🌍 Một **"Bộ Lọc Vĩ Mô" (Macro Filter)**.

#### 3.1. Phân Tích & Logic (`market_context.py`, `rice_news.py`)

* **Trend Vĩ Mô:** Tổng hợp chỉ số Fear & Greed và BTC Dominance để đưa ra nhận định 5 cấp độ (`STRONG_UPTREND` -> `STRONG_DOWNTREND`).
* **Phân Tích Tin Tức:** Phân loại tin theo mức độ quan trọng (`CRITICAL`, `WARNING`...) bằng cách quét từ khóa.

* **Đánh Giá:**
    * **Điểm mạnh:** Tách riêng bối cảnh ra một trụ cột cho thấy tư duy thiết kế tốt.
    * **Điểm yếu:** Đây là trụ cột **yếu nhất**. Phân tích tin tức dựa trên từ khóa rất thô sơ.
    * **Hướng Nâng Cấp:** Đây là nơi **LLM (Large Language Model)** có thể tạo ra tác động lớn nhất để hiểu ngữ nghĩa tin tức.

---

## V. Trụ Cột 4: Thực Thi & Quản Lý (Module `live_trade.py`)

* **Linh Hồn:** 🎖️ Một **"Tổng Tư Lệnh Chiến Dịch Thích Ứng" (Adaptive Campaign Commander)**.

#### 5.1. "4-Zone Strategy" & Lựa Chọn Chiến Thuật (`TACTICS_LAB`)

Đây là triết lý thực thi bậc cao: phân tích "địa hình" (4 Vùng), chọn "binh chủng" (Chiến thuật) và phân bổ "quân lực" (Vốn).

* **4 Vùng Thị Trường:** `LEADING` (sớm, rủi ro), `COINCIDENT` (đồng pha, điểm ngọt), `LAGGING` (an toàn, theo trend), `NOISE` (nhiễu).
* **Phòng Thí Nghiệm Chiến Thuật (`TACTICS_LAB`):** Một kho "vũ khí" chuyên dụng cho từng Vùng, mỗi loại có bộ tham số riêng (RR, SL, Trailing Stop...).
* **Chính Sách Vốn (`ZONE_BASED_POLICIES`):** Phân bổ vốn linh động, Vùng rủi ro cao đi vốn nhỏ, Vùng an toàn đi vốn lớn hơn.

#### 5.2. Các Module Cấu Hình Vận Hành & Rủi Ro (`live_trade.py`)

Đây là các "bảng điều khiển" chi tiết để tinh chỉnh hành vi của bot.

* **Cấu Hình Chung (`GENERAL_CONFIG`):** Quản lý tần suất làm mới dữ liệu, thời gian cooldown, báo cáo.
* **Phân Tích Đa Khung Thời Gian (`MTF_ANALYSIS_CONFIG`):** Thưởng/phạt điểm tín hiệu dựa trên sự đồng thuận với khung thời gian lớn hơn.
* **Quản Lý Vị Thế Chủ Động (`ACTIVE_TRADE_MANAGEMENT_CONFIG`):** "Phòng thủ 3 lớp" để bảo vệ lệnh đang mở (đóng lệnh sớm theo điểm tuyệt đối/tương đối, bảo vệ lợi nhuận).
* **Luật Lệ Rủi Ro (`RISK_RULES_CONFIG`):** Các quy tắc cứng về số lệnh tối đa, % SL tối đa, xử lý lệnh "ì".
* **Quản Lý Vốn (`CAPITAL_MANAGEMENT_CONFIG`, `DCA_CONFIG`):** Quy định tổng rủi ro và chiến lược trung bình giá (DCA).

---

## VI. Sức Mạnh Tổng Hợp: Triết Lý "Kiềng Ba Chân" Chống Thiên Vị

Hệ thống của bạn không bị thiên vị (bias) bởi một yếu tố duy nhất. Sức mạnh thực sự của nó nằm ở cách nó tổng hợp thông tin:

1.  **"Phòng Họp" `trade_advisor.py`:** Đây là nơi ba trụ cột (Kỹ thuật, AI, Bối cảnh) cùng "thảo luận". Mỗi trụ cột có "tiếng nói" được chuẩn hóa và "trọng số" (`WEIGHTS`) do bạn quyết định. Quyết định không dựa trên ý kiến của một "vị tướng" mà dựa trên sự đồng thuận của cả "hội đồng".
2.  **"Tổng Tư Lệnh" `live_trade.py`:** Ngay cả khi hội đồng đã đồng thuận, Tổng Tư lệnh vẫn có quyền phủ quyết hoặc thay đổi chiến thuật dựa trên tình hình thực tế của chiến trường (4-Zone Strategy).

Sự kết hợp này tạo ra một hệ thống không chỉ phản ứng với tín hiệu, mà còn **thích ứng với bối cảnh**, một đặc điểm cốt lõi của các hệ thống giao dịch chuyên nghiệp.

---

## VII. Kết Luận: Một Hệ Thống Toàn Diện, Sẵn Sàng Để Tối Ưu Hóa

`RiceAlert` không phải là một hệ thống chắp vá. Nó là một **kiến trúc phân lớp, có khả năng cấu hình sâu và triết lý giao dịch rõ ràng**. Sự phức tạp của nó đến từ các lớp logic được thiết kế để tăng cường sự vững chắc và khả năng thích ứng.

Với tài liệu này, bạn đã có một bản đồ chi tiết về "cỗ máy" của mình. Công việc tiếp theo là sử dụng nó để:
1.  **Backtest & Tinh chỉnh:** Chạy các kịch bản backtest bằng cách thay đổi các tham số đã được liệt kê để tìm ra bộ số tối ưu nhất.
2.  **Giám sát & Đánh giá:** Khi hệ thống chạy live, đối chiếu các quyết định của nó với logic được mô tả ở đây để hiểu và tin tưởng vào hệ thống.
3.  **Lên Lộ trình Nâng cấp:** Tập trung nguồn lực vào việc nâng cấp các điểm yếu đã xác định (AI tuần tự, LLM cho tin tức) một cách có hệ thống.

Bạn đã xây dựng một nền móng cực kỳ vững chắc. Hãy tự tin vào "linh hồn" mà bạn đã tạo ra và tiếp tục hoàn thiện nó.
