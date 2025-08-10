---

# Hệ Thống Giao Dịch Thuật Toán RiceAlert
*(hiện đã làm xong phần spot cho coin, đang dồn lực phát triển thêm tính năng đánh sóng ngắn, với đòn bảy với các coin top trên exness, đồng thời sẽ áp dụng các triết lý phía dưới cho phần phân tích CKVN (làm song song với các hệ thống))*

## Phân Tích Kiến Trúc & Triết Lý Giao Dịch v3.2

### Lời Mở Đầu: Tìm Kiếm "Linh Hồn" Của Hệ Thống

Tài liệu này phân tích sâu về cấu trúc và triết lý giao dịch của hệ thống RiceAlert. Hệ thống ban đầu được thiết kể để lấy thông tin thị trường, giúp người trade giảm thụ động, nó được thiết kế với những triết lý từ cơ bản đến phức tạp, với lõi là 3 phần chính.

Logic của hệ thống không sử dụng các chỉ báo đơn lẻ, mà kết hợp với nguồn dữ liệu khác nhau, tổng hợp lại sau đó được thực hiện bằng một logic trade mô phỏng giống người nhất *"hệ thống không tạo ra để cạnh tranh, mà là để sống sót và có lãi thụ động"* (A Multi-Factor, Context-Aware Adaptive Strategist).

Hệ thống hoạt động như một hội đồng quản trị:

1.  **Phần 1: Nguồn tri thức (indicator, AI, News):** Thu thập, phân tích thông tin từ các chỉ báo kỹ thuật, dự báo AI, và bối cảnh vĩ mô, tin tức.
2.  **Phần 2: Phòng tổng hợp (trade\_advisor):** Tổng hợp báo cáo, đưa ra một "điểm số đồng thuận" có trọng số.
3.  **Phần 3 (live\_trade):** Nhận điểm số đồng thuận, kết hợp với phân tích "Mô phòng giao dịch" với (4 Vùng Thị trường) để quyết định chiến thuật, phân bổ vốn và thực thi lệnh, đi kèm các cơ chế tự bảo vệ lợi nhuận.

Tài liệu này sẽ nói rõ chi tiết cách hoạt động của hệ thống này.

### Tham Số Nền Tảng: `SCORE_RANGE` - Nút Vặn Chính Của Hệ Thống

Trước khi đi vào các phần chính, cần làm rõ về `SCORE_RANGE`, tham số quan trọng bậc nhất định hình "tính cách" của hệ thống.

`SCORE_RANGE` là một thước đo chuẩn, quy định mức độ đồng thuận cần thiết của các tín hiệu kỹ thuật. Nó có hai vai trò:

*   **Định nghĩa Ngưỡng Nhạy Cảm (`signal_logic.py`):** Các cấp độ tín hiệu như `CRITICAL` hay `WARNING` được tính bằng một tỷ lệ phần trăm của `SCORE_RANGE`.
*   **Chuẩn Hóa Điểm Số (`trade_advisor.py`):** Chuẩn hóa điểm kỹ thuật thô về thang điểm chung (-1 đến +1) để có thể so sánh công bằng với điểm từ AI và Bối cảnh.

**Phân tích tác động:**

| Thuộc Tính | SCORE_RANGE = 6 (Nhạy Cảm) | SCORE_RANGE = 8 (Cân Bằng - Hiện tại) | SCORE_RANGE = 12 (Thận Trọng) |
| :--- | :--- | :--- | :--- |
| Độ nhạy tín hiệu | Cao | Trung bình | Thấp |
| Tần suất vào lệnh | Cao | Trung bình | Thấp |
| Độ tin cậy (lý thuyết) | Thấp hơn | Trung bình | Cao hơn |
| Tầm ảnh hưởng của PTKT | Rất Lớn | Lớn | Vừa phải |
| Phù hợp với | Scalping, Thị trường sôi động | Swing Trading, Đa chiến lược | Position Trading, Trend dài hạn |

**Kết luận:** Mức `8` hiện tại là một lựa chọn cân bằng, đồng bộ với tham số `CLAMP_MAX_SCORE = 8.0` trong code. Việc tối ưu hóa tham số này nên được thực hiện thông qua backtest để phù hợp với từng giai đoạn thị trường. Điểm Thấp sẽ để Bot lạc quan vào thị trường hơn, điểm tính ra cao hơn trong khi điểm Cao sẽ khiến bot thận trọng.

## I. Phần 1: Phân Tích Kỹ Thuật (indicator & signal_logic)

Đây là hệ thống chấm điểm đồng thuận dựa trên nhiều chỉ báo kỹ thuật.

### 1.1. Các Chỉ Báo Nền Tảng (từ `indicator.py`)

Đây là các nguyên liệu thô, cung cấp dữ liệu đầu vào cho toàn hệ thống.

| Phân Loại | Chỉ Báo & Tín Hiệu | Mục Đích Đo Lường |
| :--- | :--- | :--- |
| **Xu hướng (Trend)** | EMA (9, 20, 50, 200), ADX | Xác định hướng và sức mạnh của xu hướng chính. |
| **Động lượng (Momentum)** | RSI (14), MACD, Phân kỳ RSI | Đo lường tốc độ và sự thay đổi của giá, phát hiện sự suy yếu của trend. |
| **Biến động (Volatility)** | Bollinger Bands (BB), ATR | Đo lường mức độ biến động, xác định các vùng siết chặt (squeeze) và phá vỡ (breakout). |
| **Khối lượng (Volume)** | Volume, Volume MA(20), CMF | Xác nhận sức mạnh của xu hướng và dòng tiền đang vào hay ra. |
| **Mô hình (Pattern)** | Nến Doji, Nến Nhấn chìm | Nhận diện các mẫu nến đảo chiều hoặc tiếp diễn tiềm năng. |
| **Hỗ trợ/Kháng cự** | Fibonacci Retracement, High/Low | Xác định các vùng giá quan trọng có thể xảy ra phản ứng. |

### 1.2. Logic & Trọng Số Tính Điểm (từ `signal_logic.py` -> `RULE_WEIGHTS`)

Mỗi tín hiệu được gán một "phiếu bầu" với "sức nặng" khác nhau.

| Quy Tắc Tín Hiệu | Trọng Số | Logic Kích Hoạt & Diễn Giải Chi Tiết |
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
| `score_atr_vol` | -1.0 | (Quy tắc phạt) Nếu biến động ATR quá cao (> 5%), điểm sẽ bị trừ để tránh thị trường quá "hoảng loạn". |
| `score_ema200`, `score_rsi_multi`, `score_adx`, `score_bb` | 0.5 | Các tín hiệu phụ, dùng để củng cố thêm cho các nhận định chính. |

**Đánh giá:**

*   **Ưu điểm:** Vững chắc (robust), không phụ thuộc vào một chỉ báo duy nhất, giảm thiểu tín hiệu nhiễu. Dễ tinh chỉnh qua file `RULE_WEIGHTS`.
*   **Nhược điểm:** Một vài quy tắc có thể tương quan (correlated), ví dụ `score_trend` và `score_ema200` cùng đo lường xu hướng, có thể vô tình làm tăng trọng số của một loại tín hiệu. Ngoài ra các indicator này hiện tại được lấy theo kinh nghiệm của người bán chuyên, chưa thật sự tổng quan hóa được thị trường, API cung cấp indicator rất đầy đủ nó có gần như tất cả inidcator, việc mỗi inidcator chuẩn sẽ cho kết quả đáng tin kết hợp nhiều inidcator có thể làm người ta cảm thấy bot của tôi rất mạnh nhưng chưa chắc nó đáng tin và chính xác nếu ta dùng đúng các indicator combo, ko có một chén thánh nào cả, việc sử dụng nhiều indicator sẽ khiến tính toán phức tạp dẫn tới việc bot vào lệnh chậm (rủi ro khi trade sóng ngắn) nhưng với người có khả năng am hiểu indicator, hệ thống hoàn toàn có thể kết hợp nhiều logic indicator vào để chuẩn chỉ nhất.

## II. Phần 2: Dự Báo AI (`trainer.py` & `ml_report.py`)

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

*   **Ưu điểm:** Logic định nghĩa nhãn (label) dựa trên ATR là một kỹ thuật hiệu quả. Feature engineering toàn diện (giả định). Sử dụng bộ đôi Classifier và Regressor cung cấp cái nhìn đa chiều. cũng như việc các mô hình tuần tự như LSTM/GRU hoặc Transformer. Các mô hình này có khả năng hiểu được ngữ cảnh thời gian của thị trường, có thể cải thiện chất lượng dự báo
*   **Nhược điểm:** Việc nâng cấp mới được diễn ra nó đã được backtest và cần thời gian chứng minh trên môi trường thật, sau này có thể nâng cấp máy VPS cấu hình mạnh hơn có GPU để chạy tốc độ cao hơn.


## III. Phần 3: Phân Tích Bối Cảnh (`market_context.py` & `rice_news.py`)

Module này hoạt động như một bộ lọc vĩ mô, đảm bảo các quyết định giao dịch không đi ngược lại xu thế chung.

*   **Phân Tích Trend Vĩ Mô (`market_context.py`):** Tổng hợp Fear & Greed Index và BTC Dominance để đưa ra nhận định tổng quan về thị trường.
*   **Phân Tích Tin Tức (`rice_news.py`):** Quét tin tức tài chính để tìm các từ khóa được định nghĩa trước (ví dụ: "SEC", "ETF", "HACK").

**Bảng Logic & Yếu Tố:**

| Yếu Tố | Nguồn Dữ Liệu | Logic Đánh Giá |
| :--- | :--- | :--- |
| **Tâm lý Thị trường** | API Fear & Greed Index | Ánh xạ điểm số F&G (0-100) sang các trạng thái như "Sợ hãi tột độ" (mua) hoặc "Tham lam tột độ" (rủi ro). |
| **Sức mạnh Altcoin** | API BTC Dominance | Phân tích xu hướng của BTC.D. Nếu BTC.D giảm, thị trường có thể đang trong "mùa altcoin". |
| **Tin Tức Quan Trọng** | API tin tức | Quét tiêu đề và nội dung để tìm các từ khóa đã định sẵn, gán mức độ ảnh hưởng. |

**Đánh giá:**

*   **Ưu điểm:** Ý tưởng tách riêng bối cảnh là một tư duy thiết kế tốt, ngăn bot chỉ "nhìn chart" một cách máy móc nó đã tích hợp thêm model Embed để đọc hiểu ngữ cảnh.
*   **Nhược điểm:** Đây là phần cần cải thiện nhiều nhất. Phân tích tin tức dựa trên từ khóa rất dễ sai lầm mặc dù được cái tiến nhưng với điều kiện máy VPS thì cần một thời gian để chứng minh, nó chỉ đang đọc tiêu đề bài báo chứ chưa đọc nội dung bài báo, điểm trọng số phần này ko được cao khi tính điểm.
*   **Hướng nâng cấp:** Sử dụng Mô hình Ngôn ngữ Lớn (LLM) như GPT-4, Claude, hoặc Gemini. LLM có thể đọc, hiểu ngữ nghĩa, phân tích sắc thái của toàn bộ bài báo để cung cấp điểm số cảm tính (sentiment score) chính xác hơn. Hiện tại vì cơ chế lọc rất yếu do đó trọng số tính điểm của phần này thường thấp nhiều so với indicator và AI.

## IV. Phần 4: Thực Thi, Quản Lý Vốn & Rủi Ro (`live_trade.py` v8.6.1)

Đây là module trung tâm, bộ não thực thi của toàn bộ hệ thống. Nó chịu trách nhiệm chuyển hóa các tín hiệu phân tích thành lệnh giao dịch thực tế, quản lý vòng đời của từng vị thế, và áp dụng một hệ thống quản lý rủi ro đa tầng, tự động và thông minh. Phiên bản 8.6.1 giới thiệu Động Cơ Vốn Năng Động, một bước tiến lớn trong việc tự động hóa quản lý vốn.

### 4.1. Luồng Hoạt Động Của Một Phiên (Session Flow)

Mỗi khi bot được kích hoạt (ví dụ: mỗi phút qua cron job), nó sẽ thực hiện một chu trình logic nghiêm ngặt:

1.  **Khóa & Tải Trạng Thái:** Tạo file `.lock` để ngăn xung đột dữ liệu và tải file `state.json` chứa thông tin về các lệnh đang mở và lịch sử.
2.  **Đối Soát & Vệ Sinh:** So sánh trạng thái của bot với số dư thực tế trên sàn để phát hiện và xử lý "Lệnh Ma" (lệnh bị đóng thủ công) và "Tài Sản Mồ Côi" (tài sản không được quản lý).
3.  **Tính Toán Equity:** Lấy giá thực tế của tất cả tài sản và tính toán tổng giá trị tài khoản (equity) hiện tại.
4.  **Quản Lý Vốn Năng Động: (v8.6.1)** Chạy `manage_dynamic_capital()` để kiểm tra Nạp/Rút, và tự động điều chỉnh Vốn Ban Đầu (initial\_capital) nếu có lãi/lỗ đáng kể.
5.  **Quét & Phân Tích (Heavy Task):** Theo định kỳ (`HEAVY_REFRESH_MINUTES`), bot sẽ tải dữ liệu mới, tính toán lại toàn bộ chỉ báo cho các cặp coin và tìm kiếm cơ hội giao dịch mới.
6.  **Thực Thi Lệnh Mới:** Nếu có cơ hội tiềm năng đang chờ (`pending_trade_opportunity`), bot sẽ tiến hành thực thi lệnh mua.
7.  **Quản Lý Lệnh Đang Mở:** Đối với mỗi lệnh đang hoạt động, bot sẽ:
    *   Kiểm tra điều kiện SL (Cắt Lỗ) / TP (Chốt Lời).
    *   Đánh giá lại điểm tín hiệu để quyết định có đóng sớm (Early Close).
    *   Kích hoạt cơ chế "Bảo Vệ Lợi Nhuận" (Profit Protection).
    *   Di dời SL nếu đủ điều kiện (Trailing SL).
    *   Tìm cơ hội Trung Bình Giá (DCA).
    *   Xử lý các lệnh "ì" (Stale Trades).
8.  **Báo Cáo:** Gửi báo cáo tổng kết định kỳ hoặc cảnh báo động đến Discord nếu đủ điều kiện.
9.  **Lưu & Kết Thúc:** Lưu lại trạng thái mới vào `state.json` và giải phóng file `.lock`.

### 4.2. Trung Tâm Cấu Hình Vận Hành (v8.6.1)

Đây là bảng điều khiển chi tiết, nơi tinh chỉnh mọi khía cạnh hành vi của bot. Mỗi cấu hình đều có mục đích riêng và tác động trực tiếp đến chiến lược giao dịch và quản lý rủi ro.

#### 4.2.1. GENERAL_CONFIG - Cấu Hình Vận Hành Chung
*Ghi chú: Đây là các tham số nền tảng, ảnh hưởng đến tần suất hoạt động, giới hạn và các quy tắc cơ bản.*

| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `TRADING_MODE` | `"testnet"` | Môi trường hoạt động: `"live"` (tiền thật) hoặc `"testnet"` (thử nghiệm). Tham số quan trọng nhất, cần kiểm tra kỹ trước khi chạy. |
| `DATA_FETCH_LIMIT` | `300` | **Độ sâu phân tích:** Số lượng nến (dữ liệu lịch sử) tải về để tính toán chỉ báo. Con số lớn hơn cho các chỉ báo dài hạn (như EMA 200) chính xác hơn. |
| `DAILY_SUMMARY_TIMES` | `["08:10", "20:10"]` | **Giao tiếp định kỳ:** Các mốc thời gian (giờ Việt Nam) bot sẽ tự động gửi báo cáo tổng kết chi tiết trong ngày ra Discord. |
| `TRADE_COOLDOWN_HOURS` | `1` | **Kỷ luật giao dịch:** Thời gian "nghỉ" (giờ) cho một coin sau khi đóng lệnh. Giúp tránh "giao dịch trả thù" và cho thị trường thời gian để ổn định. |
| `CRON_JOB_INTERVAL_MINUTES` | `1` | **Đồng bộ thời gian:** Phải khớp với tần suất bạn đặt trên crontab/scheduler. Bot dùng nó để tính toán một số logic liên quan đến thời gian. |
| `HEAVY_REFRESH_MINUTES` | `15` | **Tần suất quét sâu:** Cứ mỗi 15 phút, bot sẽ thực hiện "quét sâu" - tính lại toàn bộ chỉ báo và tìm kiếm cơ hội giao dịch mới trên toàn thị trường. |
| `PENDING_TRADE_RETRY_LIMIT` | `3` | **Tính bền bỉ:** Số lần thử lại tối đa nếu một lệnh MUA mới thất bại (ví dụ do lỗi mạng hoặc API của sàn). |
| `CLOSE_TRADE_RETRY_LIMIT` | `3` | **Đảm bảo thoát lệnh:** Số lần thử lại tối đa nếu một lệnh BÁN (đóng) thất bại. |
| `CRITICAL_ERROR_ALERT_COOLDOWN_MINUTES` | `45` | **Giảm nhiễu cảnh báo:** Nếu gặp lỗi nghiêm trọng lặp đi lặp lại, bot sẽ chỉ gửi cảnh báo về lỗi đó mỗi 45 phút để tránh spam Discord. |
| `RECONCILIATION_QTY_THRESHOLD` | `0.95` | **Ngưỡng tự chữa lành:** Nếu số lượng coin thực tế trên sàn < 95% so với bot ghi nhận, lệnh sẽ bị coi là 'bất đồng bộ' (do bạn đã bán thủ công) và tự động dọn dẹp. |
| `OVERRIDE_COOLDOWN_SCORE` | `7.5` | **Cơ hội vàng:** Cho phép bot phá vỡ thời gian nghỉ nếu phát hiện một cơ hội có điểm tín hiệu cực cao (>= 7.5), đảm bảo không bỏ lỡ tín hiệu tốt nhất. |
| `ORPHAN_ASSET_MIN_VALUE_USDT` | `10.0` | **Vệ sinh tài khoản:** Tự động cảnh báo nếu phát hiện tài sản "mồ côi" (có trên sàn nhưng không được bot quản lý) trị giá trên 10 USD. |
| `MIN_ORDER_VALUE_USDT` | `11.0` | **Tuân thủ quy định sàn:** Giá trị lệnh tối thiểu (USD) để đặt lệnh. Binance yêu cầu 10 USD, đặt 11 để an toàn do trượt giá. |

#### 4.2.2. FEATURE SPOTLIGHT: ĐỘNG CƠ VỐN NĂNG ĐỘNG (v8.6.1)
*Ghi chú: Đây là nâng cấp cốt lõi, biến bot từ một công cụ thực thi thành một hệ thống quản lý vốn bán tự trị. Nó giúp vốn hóa lợi nhuận và giảm rủi ro một cách tự động.*

| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `DEPOSIT_DETECTION_MIN_USD` | `5.0` | **Phát hiện Nạp/Rút (tuyệt đối):** Bất kỳ thay đổi ròng nào trong số dư USDT > 5 USD sẽ được coi là hành động nạp/rút và điều chỉnh Vốn Ban Đầu. |
| `DEPOSIT_DETECTION_THRESHOLD_PCT` | `0.005` | **Phát hiện Nạp/Rút (tương đối):** Tương tự, nhưng dựa trên 0.5% tổng vốn. Bot sẽ dùng giá trị lớn hơn giữa ngưỡng tuyệt đối và tương đối. |
| `AUTO_COMPOUND_THRESHOLD_PCT` | `10.0` | **Tự động tái đầu tư:** Nếu tổng tài sản tăng +10% so với Vốn Ban Đầu, Vốn Ban Đầu sẽ được nâng lên mức tài sản mới. Điều này giúp tăng quy mô lệnh trong giai đoạn tăng trưởng. |
| `AUTO_DELEVERAGE_THRESHOLD_PCT` | `-10.0` | **Tự động bảo toàn vốn:** Nếu tổng tài sản giảm -10% so với Vốn Ban Đầu, Vốn Ban Đầu sẽ được hạ xuống mức tài sản mới. Điều này giúp giảm quy mô lệnh trong giai đoạn sụt giảm (drawdown). |
| `CAPITAL_ADJUSTMENT_COOLDOWN_HOURS` | `72` | **Ổn định vốn:** Hệ thống sẽ chờ 72 giờ giữa các lần tự động điều chỉnh vốn do hiệu suất (không áp dụng cho việc Nạp/Rút) để tránh các quyết định vội vàng do biến động ngắn hạn. |

#### 4.2.3. MTF_ANALYSIS_CONFIG - Phân Tích Đa Khung Thời Gian
*Ghi chú: Tăng cường độ tin cậy của tín hiệu bằng cách đối chiếu với xu hướng ở các khung thời gian lớn hơn. Một tín hiệu "MUA" ở khung 1h sẽ mạnh hơn nếu khung 4h và 1d cũng đang trong xu hướng tăng.*

| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `ENABLED` | `True` | Bật/Tắt hoàn toàn mô-đun này. Nếu False, mọi tín hiệu sẽ có hệ số là 1.0. |
| `BONUS_COEFFICIENT` | `1.15` | **Thưởng đồng thuận:** Nếu trend khung lớn hơn đồng thuận, điểm tín hiệu được nhân thêm 15% (ví dụ: điểm 7.0 -> 8.05). |
| `PENALTY_COEFFICIENT` | `0.85` | **Phạt xung đột:** Nếu có 1 khung lớn hơn xung đột, điểm tín hiệu bị nhân với 0.85 (phạt 15%). |
| `SEVERE_PENALTY_COEFFICIENT`| `0.70` | **Phạt nặng:** Phạt 30% nếu tất cả các khung lớn hơn cùng xung đột, một dấu hiệu rủi ro rất cao. |
| `SIDEWAYS_PENALTY_COEFFICIENT`| `0.90` | **Phạt do thiếu xác nhận:** Phạt nhẹ 10% nếu khung lớn hơn đang đi ngang (sideways), vì thiếu sự hỗ trợ từ xu hướng lớn. |

#### 4.2.4. ACTIVE_TRADE_MANAGEMENT_CONFIG - Quản Lý Vị Thế Đang Mở
*Ghi chú: Các quy tắc linh hoạt để quản lý một lệnh sau khi đã được mở. Mục tiêu là tối ưu hóa lợi nhuận và giảm thiểu rủi ro một cách chủ động thay vì chỉ chờ SL/TP.*

| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `EARLY_CLOSE_ABSOLUTE_THRESHOLD` | `4.8` | **Phòng tuyến cuối cùng:** Nếu điểm tín hiệu của lệnh (được tính lại mỗi phiên) tụt xuống dưới 4.8, đóng toàn bộ lệnh ngay lập tức, bất kể PnL. |
| `EARLY_CLOSE_RELATIVE_DROP_PCT` | `0.27` | **Tường lửa linh hoạt:** Nếu điểm tín hiệu sụt giảm > 27% so với lúc vào lệnh (ví dụ từ 8.0 xuống 5.8), kích hoạt hành động chốt lời một phần. |
| `PARTIAL_EARLY_CLOSE_PCT` | `0.5` | Khi `EARLY_CLOSE_RELATIVE_DROP_PCT` được kích hoạt, bot sẽ đóng 50% vị thế và dời SL về hòa vốn. |
| `PROFIT_PROTECTION` | `{...}` | **Module Chốt Chặn Lợi Nhuận:**<br>- **`ENABLED`**: `True` - Bật/tắt tính năng bảo vệ lợi nhuận.<br>- **`MIN_PEAK_PNL_TRIGGER`**: `3.5` - Lệnh phải đạt lãi tối thiểu +3.5% để kích hoạt chế độ bảo vệ.<br>- **`PNL_DROP_TRIGGER_PCT`**: `2.0` - Sau khi kích hoạt, nếu PnL sụt giảm 2.0% từ đỉnh (ví dụ từ +8% xuống +6%), bot sẽ bán.<br>- **`PARTIAL_CLOSE_PCT`**: `0.7` - Khi `PNL_DROP_TRIGGER_PCT` được kích hoạt, bot sẽ chốt 70% vị thế để hiện thực hóa lợi nhuận. |

#### 4.2.5. RISK_RULES_CONFIG - Các Quy Tắc Rủi Ro Cứng
*Ghi chú: Các giới hạn không thể vi phạm để đảm bảo kỷ luật và kiểm soát rủi ro ở cấp độ toàn danh mục.*

| Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- |
| `MAX_ACTIVE_TRADES` | `12` | **Kiểm soát đa dạng hóa:** Số lượng vị thế được phép mở đồng thời tối đa. Tránh rủi ro tập trung quá mức. |
| `MAX_SL_PERCENT_BY_TIMEFRAME` | `{"1h": 0.06, ...}` | **Kiểm soát rủi ro/lệnh:** Giới hạn mức cắt lỗ tối đa cho phép theo từng khung thời gian (lệnh 1h không có SL xa hơn 6% giá vào lệnh). |
| `MAX_TP_PERCENT_BY_TIMEFRAME` | `{"1h": 0.12, ...}` | **Kỳ vọng thực tế:** Giới hạn mức chốt lời tối đa để tránh kỳ vọng phi thực tế và đảm bảo tỷ lệ Risk/Reward hợp lý. |
| `STALE_TRADE_RULES` | `{...}` | **Module xử lý lệnh "ì":**<br>- ` "1h": {"HOURS": 48, ...}` - Một lệnh 1h, sau 48 giờ, nếu chưa đạt được 25% chặng đường tới TP, sẽ bị xem xét đóng để giải phóng vốn cho cơ hội tốt hơn. |
| `STAY_OF_EXECUTION_SCORE` | `6.8` | **Ân xá:** Một lệnh "ì" sẽ KHÔNG bị đóng nếu điểm tín hiệu hiện tại của nó vẫn còn tốt (>= 6.8), cho nó thêm cơ hội "sống". |

#### 4.2.6. CAPITAL_MANAGEMENT, DCA & ALERTS - Các Module Chuyên Biệt

| Module | Tham Số | Giá Trị Mẫu | Ý Nghĩa & Tác Động |
| :--- | :--- | :--- | :--- |
| **QUẢN LÝ VỐN TỔNG THỂ** | `MAX_TOTAL_EXPOSURE_PCT` | `0.75` | **Phanh an toàn tổng thể:** Tổng vốn đã đầu tư vào các lệnh đang mở không được vượt quá 75% tổng số USDT có trên sàn. Đây là lớp bảo vệ cuối cùng chống lại việc "all-in". |
| **TRUNG BÌNH GIÁ (DCA)** | `ENABLED` | `True` | Bật/Tắt chiến lược DCA: Cho phép bot mua thêm khi giá giảm để cải thiện giá vào lệnh trung bình. |
| | `MAX_DCA_ENTRIES` | `2` | Mỗi lệnh chỉ được phép DCA tối đa 2 lần. |
| | `TRIGGER_DROP_PCT` | `-5.0` | Kích hoạt DCA khi giá giảm -5% so với lần vào lệnh gần nhất. |
| | `SCORE_MIN_THRESHOLD` | `6.5` | **DCA thông minh:** Chỉ DCA nếu điểm tín hiệu hiện tại vẫn đủ tốt (>= 6.5). Tránh "bắt dao rơi" một cách mù quáng. |
| | `CAPITAL_MULTIPLIER` | `0.75` | Quản lý vốn DCA: Vốn cho lần DCA này sẽ bằng 75% vốn của lần vào lệnh trước. |
| | `DCA_COOLDOWN_HOURS` | `8` | Phải chờ ít nhất 8 giờ giữa các lần DCA để tránh mua vào liên tục trong một cú sập nhanh. |
| **CẢNH BÁO** | `DISCORD_WEBHOOK_URL` | `os.getenv(...)` | Link webhook để gửi thông báo đến kênh Discord của bạn. |
| | `DISCORD_CHUNK_DELAY_SECONDS` | `2` | Thời gian chờ (giây) giữa các phần của tin nhắn dài để đảm bảo Discord không chặn vì gửi quá nhanh. |
| **CẢNH BÁO ĐỘNG** | `ENABLED` | `True` | Bật/tắt tính năng gửi cập nhật động về hiệu suất danh mục ra Discord. |
| | `COOLDOWN_HOURS` | `3` | Thời gian chờ tối thiểu (3 giờ) giữa các lần gửi cập nhật để tránh spam. |
| | `FORCE_UPDATE_HOURS` | `10` | Bắt buộc gửi một bản cập nhật sau mỗi 10 giờ, ngay cả khi không có thay đổi lớn. |
| | `PNL_CHANGE_THRESHOLD_PCT` | `2.0` | Gửi cập nhật ngay lập tức nếu Tổng PnL của danh mục thay đổi lớn hơn hoặc bằng 2.0%. |

## V. Kết Luận và Hướng Phát Triển

Hệ thống RiceAlert được xây dựng trên một kiến trúc phân lớp, có khả năng cấu hình sâu và triết lý giao dịch rõ ràng. Sự phức tạp của nó đến từ các lớp logic được thiết kế để tăng cường sự vững chắc và khả năng thích ứng.

**Lộ trình tiếp theo:**

*   **Backtest & Tinh chỉnh:** Chạy các kịch bản backtest bằng cách thay đổi các tham số trong file cấu hình để tìm ra bộ số tối ưu.
*   **Giám sát & Đánh giá:** Khi hệ thống chạy live, đối chiếu các quyết định của nó với logic được mô tả ở đây để hiểu và đánh giá hiệu quả.
*   **Nâng cấp:** Tập trung nguồn lực vào việc nâng cấp các điểm yếu đã xác định (Tối ưu indicator từ các chuyên gia,AI tuần tự, LLM cho tin tức, nâng cấp Livetrade để nó dynamic và giống người thay vì hiện tại đang là If-else đơn thuần) một cách có hệ thống, các công việc này thật sự cần thời gian cả về kỹ thuật và máy móc và không thể làm nhanh.

Tài liệu này cung cấp một bản đồ chi tiết của hệ thống, là cơ sở cho các bước tối ưu hóa và phát triển tiếp theo.

---

## DRAFT về cấu hình tham số của live_trade

### PHẦN 1: CẤU HÌNH CƠ BẢN & VẬN HÀNH
*Đây là những cài đặt chung nhất, quyết định cách bot chạy và tương tác.*

*   **`TRADING_MODE`**
    *   **`"live"`**: Chạy bằng tiền thật trên tài khoản Binance chính.
    *   **`"testnet"`**: Chạy bằng tiền ảo trên môi trường thử nghiệm của Binance. Dùng để kiểm tra chiến thuật mà không sợ mất tiền.
*   **`GENERAL_CONFIG` (Cấu hình chung)**
    *   **`DATA_FETCH_LIMIT: 300`**: Mỗi lần phân tích, bot sẽ tải về 300 nến gần nhất để tính toán các chỉ báo.
    *   **`DAILY_SUMMARY_TIMES: ["08:10", "20:10"]`**: Các mốc giờ (Việt Nam) trong ngày bot sẽ tự động gửi báo cáo tổng kết chi tiết ra Discord.
    *   **`TRADE_COOLDOWN_HOURS: 1`**: Sau khi đóng một lệnh (lời hay lỗ), bot sẽ không mở lệnh mới cho chính đồng coin đó trong vòng 1 giờ. Giúp tránh việc vào lại ngay một thị trường đang biến động khó lường.
    *   **`CRON_JOB_INTERVAL_MINUTES: 1`**: Rất quan trọng. Số này phải khớp với tần suất bạn đặt trên hệ thống crontab (VD: `*/1 * * * *`). Nó báo cho bot biết là nó được chạy 1 phút/lần.
    *   **`HEAVY_REFRESH_MINUTES: 15`**: Tần suất (phút) để bot thực hiện một tác vụ "nặng": quét toàn bộ thị trường để tìm cơ hội mới. Giữa các lần quét nặng này, bot chỉ tập trung quản lý các lệnh đang mở.
    *   **`PENDING_TRADE_RETRY_LIMIT: 3`**: Nếu bot quyết định vào một lệnh MUA nhưng gặp lỗi (VD: mạng lag), nó sẽ thử lại tối đa 3 lần trước khi hủy bỏ cơ hội đó.
    *   **`CLOSE_TRADE_RETRY_LIMIT: 3`**: Tương tự, nếu lệnh BÁN (chốt lời/cắt lỗ) bị lỗi, nó sẽ thử lại 3 lần. Nếu vẫn thất bại, nó sẽ gửi cảnh báo khẩn cấp.
    *   **`CRITICAL_ERROR_ALERT_COOLDOWN_MINUTES: 45`**: Nếu bot gặp một lỗi nghiêm trọng lặp đi lặp lại, nó sẽ chỉ gửi cảnh báo ra Discord 45 phút/lần để tránh spam.
    *   **`RECONCILIATION_QTY_THRESHOLD: 0.95`**: Dùng để phát hiện bạn có can thiệp thủ công hay không. Ví dụ: bot ghi nhận đang giữ 1 ETH, nhưng trên sàn chỉ còn 0.9 ETH (< 95%). Bot sẽ hiểu là lệnh đã bị bán thủ công và tự động xóa lệnh đó khỏi bộ nhớ.
    *   **`MIN_ORDER_VALUE_USDT: 11.0`**: Giá trị lệnh tối thiểu (tính bằng USD) mà sàn Binance cho phép. Bất kỳ lệnh nào tính ra nhỏ hơn số này sẽ được tự động nâng lên mức này.
    *   **`OVERRIDE_COOLDOWN_SCORE: 7.5`**: Điểm số "đặc biệt". Nếu một cơ hội có điểm cao hơn 7.5, nó sẽ được phép phá vỡ `TRADE_COOLDOWN_HOURS` và vào lệnh ngay.
    *   **`ORPHAN_ASSET_MIN_VALUE_USDT: 10.0`**: Phát hiện "tài sản mồ côi". Nếu bot thấy trong ví của bạn có một đồng coin nào đó (trị giá trên 10$) mà nó không quản lý, nó sẽ cảnh báo để bạn xử lý.
    *   **`TOP_N_OPPORTUNITIES_TO_CHECK: 3`**: (Cái này ta vừa thêm) Thay vì chỉ xem xét cơ hội tốt nhất, bot sẽ xem xét top 3 cơ hội có điểm cao nhất. Nó sẽ lấy cơ hội đầu tiên trong top 3 mà vượt qua được ngưỡng vào lệnh của chính nó.

### PHẦN 2: QUẢN LÝ VỐN & RỦI RO
*Đây là các quy tắc về tiền bạc, cách bot bảo vệ vốn và tăng trưởng.*

*   **ĐỘNG CƠ VỐN NĂNG ĐỘNG (Trong `GENERAL_CONFIG`)**
    *   **`DEPOSIT_DETECTION_MIN_USD: 10.0` & `_PCT: 0.01`**: Cách bot nhận biết bạn nạp/rút tiền. Nếu tổng tài sản thay đổi bất thường (lớn hơn 10$ VÀ lớn hơn 1% tổng vốn) mà không phải do lời/lỗ, bot sẽ hiểu là có giao dịch nạp/rút và tự động cập nhật lại Vốn Ban Đầu.
    *   **`AUTO_COMPOUND_THRESHOLD_PCT: 10.0`**: Tự độngทบ lãi. Khi tổng tài sản tăng 10% so với Vốn Ban Đầu, bot sẽ tự động nâng Vốn Ban Đầu lên bằng với tổng tài sản hiện tại. Điều này làm cho các lệnh sau này có kích thước lớn hơn.
    *   **`AUTO_DELEVERAGE_THRESHOLD_PCT: -10.0`**: Tự động giảm rủi ro. Ngược lại, khi tổng tài sản giảm 10% (thua lỗ), bot sẽ tự động hạ Vốn Ban Đầu xuống. Điều này làm các lệnh sau này có kích thước nhỏ hơn để bảo toàn vốn.
    *   **`CAPITAL_ADJUSTMENT_COOLDOWN_HOURS: 72`**: Sau mỗi lần tự động điều chỉnh vốn (dù là tăng hay giảm), bot sẽ chờ 72 giờ (3 ngày) trước khi có thể điều chỉnh lần nữa, giúp vốn ổn định.
*   **`RISK_RULES_CONFIG` (Luật Rủi Ro)**
    *   **`MAX_ACTIVE_TRADES: 12`**: Số lệnh tối đa được phép mở cùng một lúc.
    *   **`MAX_SL_PERCENT_BY_TIMEFRAME`**: Giới hạn mức cắt lỗ tối đa cho phép để tránh rủi ro quá lớn. Ví dụ, lệnh 1h không được có SL xa hơn 6% giá vào lệnh.
    *   **`MAX_TP_PERCENT_BY_TIMEFRAME`**: Giới hạn mức chốt lời tối đa để tránh kỳ vọng phi thực tế.
    *   **`STALE_TRADE_RULES`**: Xử lý các lệnh "ì" (lâu không chạy). Ví dụ, một lệnh khung 1h đã mở 48 tiếng mà lãi chưa được 25% so với kỳ vọng thì sẽ bị xem xét đóng.
    *   **`STAY_OF_EXECUTION_SCORE: 6.8`**: "Ân xá" cho lệnh "ì". Nếu một lệnh "ì" nhưng điểm tín hiệu hiện tại của nó vẫn cao (trên 6.8), bot sẽ tạm thời không đóng nó.
*   **`CAPITAL_MANAGEMENT_CONFIG` (Quản lý vốn tổng thể)**
    *   **`MAX_TOTAL_EXPOSURE_PCT: 0.75`**: Cái phanh an toàn cuối cùng. Tổng số tiền bạn đã bỏ vào các lệnh đang mở sẽ không bao giờ được vượt quá 75% tổng số USDT bạn có. Luôn giữ lại 25% tiền mặt để phòng thân.

### PHẦN 3: CHIẾN THUẬT GIAO DỊCH (TRÁI TIM CỦA BOT)
*Đây là phần cốt lõi, định nghĩa cách bot phân tích, ra quyết định và hành động.*

*   **`MTF_ANALYSIS_CONFIG` (Phân tích Đa Khung Thời Gian)**
    *   Bot sẽ xem xét xu hướng ở các khung thời gian lớn hơn (4h, 1d) để đánh giá tín hiệu ở khung nhỏ (1h).
    *   **`BONUS_COEFFICIENT: 1.15`**: Nếu khung lớn cùng xu hướng, điểm tín hiệu sẽ được nhân với 1.15 (thưởng điểm).
    *   **`PENALTY_COEFFICIENT: 0.85`**: Nếu khung lớn ngược xu hướng, điểm sẽ bị nhân với 0.85 (phạt điểm).
    *   ... và các hệ số phạt khác cho các trường hợp xấu hơn.
*   **4-ZONE MODEL (Mô hình 4 Vùng)**
    *   Bot chia thị trường làm 4 loại "thời tiết":
        1.  **LEADING (Tiên phong):** Thị trường đang tích lũy, chuẩn bị có biến động mạnh.
        2.  **COINCIDENT (Trùng hợp):** Biến động đang xảy ra (ví dụ: breakout).
        3.  **LAGGING (Trễ):** Xu hướng đã rất rõ ràng.
        4.  **NOISE (Nhiễu):** Thị trường đi ngang, không rõ xu hướng.
*   **`ZONE_BASED_POLICIES` (Chính sách theo Vùng)**
    *   Cực kỳ quan trọng. Bot sẽ quyết định dùng bao nhiêu % vốn cho một lệnh dựa vào "thời tiết" của thị trường:
        *   **`LEADING_ZONE` (Dò mìn):** Dùng 5.5% vốn.
        *   **`COINCIDENT_ZONE` (Quyết đoán):** Dùng 6.5% vốn (nhiều nhất).
        *   **`LAGGING_ZONE` (An toàn):** Dùng 6.0% vốn.
        *   **`NOISE_ZONE` (Siêu cẩn thận):** Dùng 5.0% vốn.
*   **`TACTICS_LAB` (Thư viện các Chiến thuật)**
    *   Đây là "bộ não" của các chiến thuật. Mỗi chiến thuật có luật chơi riêng:
        *   **`Breakout_Hunter`**: Săn các cú phá vỡ.
            *   **`OPTIMAL_ZONE`**: Hoạt động tốt nhất ở vùng LEADING và COINCIDENT.
            *   **`ENTRY_SCORE: 7.0`**: Điểm tín hiệu phải từ 7.0 trở lên mới vào lệnh.
            *   **`RR: 2.5`**: Tỷ lệ Lời/Lỗ mục tiêu là 2.5.
            *   **`ATR_SL_MULTIPLIER: 1.8`**: Đặt Stoploss bằng 1.8 lần chỉ báo ATR.
            *   **`USE_TRAILING_SL: True`**: Bật chế độ tự động dời Stoploss lên khi có lời.
        *   ... và các chiến thuật khác (`Dip_Hunter`, `AI_Aggressor`...) với các quy tắc tương tự.

### PHẦN 4: QUẢN LÝ LỆNH ĐANG MỞ & HÀNH ĐỘNG PHỤ

*   **`ACTIVE_TRADE_MANAGEMENT_CONFIG` (Quản lý lệnh đang mở)**
    *   **`EARLY_CLOSE_ABSOLUTE_THRESHOLD: 4.8`**: Nếu điểm tín hiệu của một lệnh đang mở tụt xuống dưới 4.8, bot sẽ đóng lệnh đó ngay lập tức để tránh lỗ nặng hơn.
    *   **`EARLY_CLOSE_RELATIVE_DROP_PCT: 0.27`**: Nếu điểm tín hiệu tụt 27% so với lúc vào lệnh, bot sẽ bán một phần (50%) của lệnh đó để giảm rủi ro.
    *   **`PROFIT_PROTECTION`**: Bảo vệ lợi nhuận.
        *   Khi lệnh đã lời được `3.5%`, tính năng này được kích hoạt.
        *   Nếu sau đó lợi nhuận bị sụt giảm `2.0%` từ đỉnh, bot sẽ tự động bán `70%` lệnh để chốt lời.
*   **`DCA_CONFIG` (Trung bình giá)**
    *   **`ENABLED: True`**: Bật/tắt tính năng DCA.
    *   **`MAX_DCA_ENTRIES: 2`**: Cho phép DCA tối đa 2 lần cho một lệnh.
    *   **`TRIGGER_DROP_PCT: -5.0`**: Khi giá giảm 5% so với lần vào lệnh gần nhất, bot sẽ xem xét DCA.
    *   **`SCORE_MIN_THRESHOLD: 6.5`**: Chỉ DCA nếu điểm tín hiệu hiện tại vẫn còn tốt (trên 6.5). Không "bơm tiền" cho một lệnh đã xấu đi.
    *   **`CAPITAL_MULTIPLIER: 0.75`**: Lần DCA sẽ dùng số vốn bằng 75% so với lần vào lệnh trước đó.
    *   **`DCA_COOLDOWN_HOURS: 8`**: Chờ ít nhất 8 tiếng giữa các lần DCA.
*   **`DYNAMIC_ALERT_CONFIG` & `ALERT_CONFIG` (Cảnh báo)**
    *   Các cài đặt để bot gửi thông báo cập nhật tình hình ra Discord, điều chỉnh tần suất để không bị spam.
