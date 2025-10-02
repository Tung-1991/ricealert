# RiceAlert Algorithmic Trading System
*(The system's core strategy has been upgraded to version 9.2.0, focusing on adaptive trading according to market context. The philosophies below have been fully and detailedly updated.)*

## Architecture Analysis & Trading Philosophy v9.2.0

### Foreword: Searching for the "Soul" of the System

This document provides an in-depth analysis of the structure and trading philosophy of the RiceAlert system. The system was initially designed to gather market information, helping traders reduce passivity. The new version has evolved into An Adaptive, Context-Aware Strategist, with a multi-layered decision-making process at its core.

The system's logic does not use single indicators but combines various data sources, which are then synthesized by a trading logic that simulates human behavior as closely as possible—*"the system is not designed to compete, but to survive and generate passive profit"*.

The system operates like a board of directors with a clear process:

1.  **Part 1: Knowledge Sources (indicator, AI, News):** Collects and analyzes information from technical indicators, AI forecasts, and macro context/news to generate a **"base score"**.
2.  **Part 2: Synthesis Chamber (trade\_advisor):** Aggregates the component scores into an initial "consensus score".
3.  **Part 3 (now Part 4 in `live_trade.py`):** This is the most significantly upgraded part. It not only receives the consensus score but also performs a much more complex analysis and decision-making process, which will be detailed in **Part IV**.

This document will detail how this upgraded system operates.

### **[REPLACED]** Foundational Parameter: From `SCORE_RANGE` to an Adaptive Strategic Core

Previously, `SCORE_RANGE` was the main knob that shaped the system's "personality." **In version 9.2.0, this concept has been completely replaced** by a much more flexible decision-making and capital management system. The bot's "personality" no longer depends on a fixed number but is determined by the combination of the **4-Zone Market Model** and the **Tactics Lab**. This new approach allows the system to automatically change its behavior—from cautious to decisive—based on the actual market context.

---
## I. Part 1: Technical Analysis (indicator & signal_logic)

This is a consensus scoring system based on multiple technical indicators to create a **"technical score"**, which is part of the "base score".

### 1.1. Foundational Indicators (from `indicator.py`)

These are the raw materials, providing input data for the entire system.
*(This part has not changed; it remains the raw material for the system.)*

| Category | Indicator & Signal | Measurement Purpose |
| :--- | :--- | :--- |
| **Trend** | EMA (9, 20, 50, 200), ADX | Identify the direction and strength of the main trend. |
| **Momentum**| RSI (14), MACD, RSI Divergence | Measure the speed and change of price, detect trend weakness. |
| **Volatility**| Bollinger Bands (BB), ATR | Measure the degree of volatility, identify squeeze and breakout zones. |
| **Volume**| Volume, Volume MA(20), CMF | Confirm the strength of a trend and whether money is flowing in or out. |
| **Pattern**| Doji Candle, Engulfing Candle | Identify potential reversal or continuation candlestick patterns. |
| **Support/Resistance**| Fibonacci Retracement, High/Low | Identify important price levels where a reaction may occur. |

### 1.2. Scoring Logic & Weights (from `signal_logic.py` -> `RULE_WEIGHTS`)

Each signal is assigned a "vote" with a different "weight."
*(The base scoring logic remains unchanged, but its importance is now adjusted by Tactics)*

| Signal Rule | Base Weight | Trigger Logic & Detailed Interpretation |
| :--- | :--- | :--- |
| `score_rsi_div` | 2.0 | Detects divergence signals, an early reversal signal. |
| `score_breakout` | 2.0 | Price breaks out of Bollinger Bands after a squeeze, confirmed by Volume. |
| `score_trend` | 1.5 | EMAs are stacked in a clear order, confirming a sustainable trend. |
| `score_macd` | 1.5 | MACD line crosses above/below the Signal line. |
| `score_doji` | 1.5 | Detects a Doji candle pattern, indicating indecision and potential reversal. |
| `score_cmf` | 1.0 | Chaikin Money Flow (CMF) > 0.05 (buy) or < -0.05 (sell). |
| `score_volume` | 1.0 | A sharp spike in trading volume, confirming strength for a breakout/reversal. |
| `score_support_resistance` | 1.0 | Price is very close to a strong support or resistance zone. |
| `score_candle_pattern` | 1.0 | Detects Engulfing candlestick patterns. |
| `score_atr_vol` | -1.0 | (Penalty rule) If ATR volatility is too high, the score is penalized to avoid overly "panicked" markets. |
| `score_ema200`, `score_rsi_multi`, `score_adx`, `score_bb` | 0.5 | Supplementary signals used to further reinforce the main assessments. |

**Assessment:**

*   **Pros:** Robust, not dependent on a single indicator, minimizing noisy signals. Easy to fine-tune via the `RULE_WEIGHTS` file.
*   **Cons:** Some rules may be correlated. Using many indicators can complicate calculations, leading to slower trade entries for the bot.
*   **Upgrade:** Instead of a fixed set of weights, the system can now **dynamically change the importance of TA**. For example, `Breakout_Hunter` sets weights `{'tech': 0.6, ...}`, prioritizing technical signals, while `AI_Aggressor` only sets `{'tech': 0.3, ...}`.

---
## II. Part 2: AI Prediction (`trainer.py` & `ml_report.py`)

*(This part has no major changes in `live_trade.py` and still serves to provide an independent "AI score".)*

The machine learning model (LightGBM-LSTM-Transformer) predicts the probability of events in the near future.

*   **Classifier:** Predicts the price direction (Up, Down, Sideways). Defining "Up/Down" based on `ATR_FACTOR` helps the model adapt to the volatility of each coin.
*   **Regressor:** Predicts the magnitude of the price change (e.g., "increase by about 1.2%").

**Core Training Parameters Table (example for 1h timeframe):**

| Parameter | Example (1h) | Detailed Meaning |
| :--- | :--- | :--- |
| `HISTORY_LENGTH_MAP` | 3500 | Use the last 3500 1-hour candles as training data. |
| `FUTURE_OFFSET_MAP` | 6 | Train the AI to predict the price action of the next 6 candles (6 hours). |
| `LABEL_ATR_FACTOR_MAP`| 0.65 | A crucial parameter. An "Up" signal is only registered if the price increases > 0.65 times the ATR, helping to filter out noise. |
| `is_unbalance: True` | True | Helps the model handle the fact that "Sideways" data is often more frequent, avoiding bias. |

**Assessment:**
*   **Pros:** The label definition logic based on ATR is an effective technique. Comprehensive feature engineering (assumed). Using both a Classifier and a Regressor provides a multi-dimensional view.
*   **Cons:** The new upgrade has been backtested and needs time to prove itself in a live environment.

---
## III. Part 3: Macro Context Analysis (`market_context.py` & `rice_news.py`)

This module acts as an initial macro filter, ensuring that trading decisions do not go against the overall market trend. It provides a part of the "base score."

*   **Macro Trend Analysis (`market_context.py`):** Synthesizes the Fear & Greed Index and BTC Dominance to provide a general market overview.
*   **News Analysis (`rice_news.py`):** Scans financial news for predefined keywords (e.g., "SEC", "ETF", "HACK").

**Logic & Factors Table:**

| Factor | Data Source | Assessment Logic |
| :--- | :--- | :--- |
| **Market Sentiment** | Fear & Greed Index API | Maps the F&G score (0-100) to states like "Extreme Fear" (buy) or "Extreme Greed" (risk). |
| **Altcoin Strength** | BTC Dominance API | Analyzes the trend of BTC.D. If BTC.D is decreasing, the market may be in an "altcoin season." |
| **Significant News** | News API | Scans headlines and content for predefined keywords, assigning an impact level. |

**Assessment:**
*   **Pros:** The idea of separating the context is a good design philosophy, preventing the bot from just "looking at the chart" mechanically.
*   **Cons:** This is the area that needs the most improvement. Keyword-based news analysis is very prone to errors. The weight of this section in the score calculation is not high.
*   **Upgrade Path:** Use a Large Language Model (LLM) to deeply understand the sentiment and semantics of news.
*   **Note:** The **real-time** and **more advanced** context analysis filters (MTF, EZ, PAM) have been moved to **Part IV** as they are part of the execution logic.

---
## IV. Part 4: Execution, Capital & Risk Management (`live_trade.py` v9.2.0)

This is the central module that has been most heavily upgraded. It is the execution brain, integrating new layers of logic to manage capital and risk intelligently and flexibly, completely replacing the previous simple if-else system.

### 4.1. **[UPGRADE]** New Strategic Core: 4-Zone Model & Tactics Lab
This is the heart of the new system, deciding how the bot acts.

#### 4.1.1. 4-Zone Market Model
The first "macro filter," classifying the market to determine the **risk level** and the **percentage of capital** to use.

| Zone | Name | Characteristics | Capital Policy (`ZONE_BASED_POLICIES`) |
| :--- | :--- | :--- | :--- |
| **LEADING** | Pioneering | The market is accumulating, squeezing, preparing for a strong move. | **4.0%** Capital (Probing, betting on potential) |
| **COINCIDENT** | Concurrent | The move is happening (e.g., a breakout). The trend has just begun. The "sweetest" zone. | **5.0%** Capital (Decisive, highest capital allocation) |
| **LAGGING** | Lagging | The trend is already very clear, safer to follow. | **6.0%** Capital (Safe, following the crowd) |
| **NOISE** | Noise | The market is sideways, with no clear trend and unpredictable volatility. | **3.0%** Capital (Ultra-cautious, micro capital) |

#### 4.1.2. Tactics Lab
The "brain" containing "battle plans." The bot will choose the Tactic appropriate for the Market Zone.

| Tactic Name | Optimal Zone(s) | Description & "Personality" | Score Threshold | RR | SL (xATR) |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **Balanced_Trader** | `LAGGING`, `COINCIDENT` | **The main workhorse.** Good at holding trades, accepts early signals, wide SL to withstand pullbacks. | 6.5 | 2.2 | 2.5x |
| **Breakout_Hunter** | `LEADING`, `COINCIDENT` | **The breakout hunter.** Enters immediately on a breakout, wide SL to survive a retest. Requires strong momentum. | 7.0 | 2.8 | 2.4x |
| **Dip_Hunter** | `LEADING`, `COINCIDENT` | **The master of catching pullbacks.** Buys dips/sells rips with an extra-wide SL "safety net." Quick profits, quick exits. | 6.8 | 1.8 | 3.2x |
| **AI_Aggressor** | `COINCIDENT` | **The lightning-fast specialist.** Relies heavily on the AI score, trades fast, takes small profits, and exits quickly with a tighter SL. | 6.8 | 2.0 | 2.2x |
| **Cautious_Observer**| `NOISE` | **The sniper.** Only enters on GOLDEN opportunities in a noisy zone. Extremely high score threshold, tight SL. | 7.5 | 2.0 | 1.8x |

### 4.2. **[UPGRADE]** Real-Time Contextual Adjustment Filters
These are new modules in `live_trade.py` that act as "expert consultants" to adjust the "base score" into a "contextual score" before making the final decision.

| Filter | Purpose | Detailed Operational Logic | Configuration (`live_trade.py`) |
| :--- | :--- | :--- | :--- |
| **Multi-Timeframe Analysis (MTF)** | Avoid going against the major trend. | **Penalizes score** (`-3%` to `-5%`) if the 1h signal contradicts the 4h/1d trend. **Slightly rewards score** (`+5%`) if all align. Slight penalty if the higher timeframe is sideways. | `MTF_ANALYSIS_CONFIG` |
| **Extreme Zone (EZ)** | Avoid FOMO at the top and panic selling at the bottom. | **Penalizes score** (up to `-10%`) when buying in an overbought zone (RSI > 78, price at 98th percentile of BB). **Rewards score** (up to `+15%`) when buying in an oversold zone. Impact is **amplified x1.25** during a BB Squeeze. | `EXTREME_ZONE_ADJUSTMENT_CONFIG` |
| **Price Action Momentum (PAM)** | Reward signals with strong momentum. | **Rewards score** (up to `+10%`) if there is a series of green candles, increasing volume, price above MAs, and continuously making higher lows over the last `X` candles. | `PRICE_ACTION_MOMENTUM_CONFIG` |
| **Momentum Confirmation** | The final "gatekeeper" before entering a trade. | Requires `Y` out of the last `X` candles (e.g., 3 out of 5) to be "good candles" (green or red with a long wick) for the trade to be approved. | `MOMENTUM_FILTER_CONFIG` |

### 4.3. Session Flow
*(Updated to reflect the new logic)*

1.  **Lock & Load State:** Unchanged.
2.  **Reconciliation & Cleanup:** Unchanged.
3.  **Equity Calculation & Dynamic Capital Management:** Unchanged.
4.  **Scan & Analyze (Heavy Task):**
    *   Load data, recalculate all indicators.
    *   **Determine the Market Zone** for each coin.
    *   **Find suitable Tactics** for that Zone.
    *   **Calculate the base score**, then **apply MTF, EZ, and PAM filters** to get the final score.
    *   Compare the final score with the Tactic's threshold and **apply the Momentum Confirmation filter**.
    *   Add the best opportunity to the queue.
5.  **Execute New Trades:** If a potential opportunity is waiting, proceed with execution.
6.  **Manage Open Trades:** Continuously check for SL/TP conditions, Early Close, Profit Protection, Trailing SL, DCA, and "Stale" Trade rules.
7.  **Report & Save State:** Unchanged.

### 4.4. Operational Configuration Hub (v9.2.0 Details)
This is the detailed control panel where every aspect of the bot's behavior is fine-tuned.

#### 4.4.1. GENERAL_CONFIG - General Operational Configuration
| Parameter | Sample Value | Meaning & Impact |
| :--- | :--- | :--- |
| `TRADING_MODE` | `"live"` | Operating environment: `"live"` (real money) or `"testnet"` (testing). |
| `DATA_FETCH_LIMIT` | `300` | Number of historical candles to fetch for indicator calculations. |
| `DAILY_SUMMARY_TIMES`| `["08:10", "20:10"]` | Times (Vietnam time) for the bot to send daily summary reports to Discord. |
| `TRADE_COOLDOWN_HOURS`| `1.5` | **[Updated]** A 1.5-hour "rest" period for a coin after a trade is closed. |
| `HEAVY_REFRESH_MINUTES`| `15` | Frequency for deep scans to find new trading opportunities. |
| `TOP_N_OPPORTUNITIES_TO_CHECK`| `7` | **[NEW] Anti-FOMO:** Considers the top 7 best opportunities instead of jumping on the first one. |
| `OVERRIDE_COOLDOWN_SCORE`| `7.5` | **Golden opportunity:** Allows breaking the cooldown period if the signal score is extremely high (>= 7.5). |

#### 4.4.2. DYNAMIC CAPITAL ENGINE
| Parameter | Sample Value | Meaning & Impact |
| :--- | :--- | :--- |
| `AUTO_COMPOUND_THRESHOLD_PCT` | `10.0` | Automatically reinvests profits when they exceed 10%. |
| `AUTO_DELEVERAGE_THRESHOLD_PCT`| `-10.0` | Automatically reduces risk when losses exceed 10%. |
| `CAPITAL_ADJUSTMENT_COOLDOWN_HOURS`| `48` | **[Updated]** A 48-hour waiting period between capital adjustments. |

#### 4.4.3. ACTIVE_TRADE_MANAGEMENT_CONFIG - Managing Open Positions
| Parameter | Sample Value | Meaning & Impact |
| :--- | :--- | :--- |
| `EARLY_CLOSE_ABSOLUTE_THRESHOLD` | `4.0` | **[Updated]** Final line of defense: Closes a trade if the signal score drops below 4.0. |
| `EARLY_CLOSE_RELATIVE_DROP_PCT` | `0.30` | **[Updated]** Flexible firewall: If the signal score drops by >30% from its entry value, close 40% of the position. |
| `PROFIT_PROTECTION` | `{...}` | **[UPGRADE] Adaptive Safety Net by Timeframe:** Activation thresholds and PnL drawdowns are now **configured separately for each timeframe (1h, 4h, 1d)**, allowing the bot to be more patient with long-term trades. |

#### 4.4.4. RISK_RULES_CONFIG - Hard Risk Rules
| Parameter | Sample Value | Meaning & Impact |
| :--- | :--- | :--- |
| `MAX_ACTIVE_TRADES` | `7` | **[Updated]** The maximum number of simultaneously open positions is reduced to 7. |
| `MAX_SL_PERCENT_BY_TIMEFRAME` | `{"1h": 0.10, ...}`| **[Updated]** Limits the maximum stop loss for a 1h trade to 10%. |
| `MIN_RISK_DIST_PERCENT_BY_TIMEFRAME`| `{"1h": 0.08, ...}`| **[NEW] Safety floor:** Ensures a minimum stop loss for a 1h trade is 8%, preventing SL from being too close. |
| `STALE_TRADE_RULES` | `{...}` | **[UPDATED] More patient "stale" trade handling module:**<br>- A 1h trade, after 72 hours (instead of 48h), if it hasn't reached 2% PnL, will be considered for closure. |
| `STAY_OF_EXECUTION_SCORE`| `6.5` | **[Updated]** "Pardon" for a stale trade if its current signal score is still good (>= 6.5). |

#### 4.4.5. CAPITAL_MANAGEMENT & DCA
| Module | Parameter | Sample Value | Meaning & Impact |
| :--- | :--- | :--- | :--- |
| **CAPITAL MGMT** | `MAX_TOTAL_EXPOSURE_PCT` | `0.80` | **[Updated]** Total invested capital cannot exceed 80% of the total USDT balance. |
| **DCA** | `ENABLED` | `True` | Enable/Disable the DCA strategy. |
| | `TRIGGER_DROP_PCT_BY_TIMEFRAME`| `{"1h": -6.0, ...}` | **[UPGRADE]** Activates DCA for a 1h trade when the price drops -6.0%. Thresholds are set per timeframe. |
| | `SCORE_MIN_THRESHOLD` | `6.5` | **Smart DCA:** Only perform DCA if the current signal score is still good enough. |
| | `CAPITAL_MULTIPLIER` | `0.5` | **[Updated]** The capital for a DCA entry is only 50% of the previous entry's capital. |

---
## V. Conclusion and Future Development

The RiceAlert system is built on a layered architecture, is highly configurable, and has a clear trading philosophy. **Version v9.2.0 is a major step forward, transitioning from a system based on single rules to a context-aware and flexibly adaptive trading machine** with the **4-Zone Model** and **Tactics Lab** at its core.

**Next Roadmap:**

*   **Backtest & Fine-tune:** Run backtesting scenarios by changing parameters in the `TACTICS_LAB` and context filters to find the optimal set of numbers for each market type.
*   **Monitor & Evaluate:** When the system is running live, compare its decisions against the logic described here to understand and evaluate the effectiveness of each tactic.
*   **Upgrade:** Systematically focus resources on upgrading identified weaknesses (Indicator optimization from experts, sequential AI, LLM for news).

---

## DRAFT of live_trade configuration parameters (UPDATED TO VERSION 9.2.0)

*(This section is kept in its original style to explain the parameters in detail)*

### PART 1: BASIC & OPERATIONAL CONFIGURATION
*These are the most general settings that determine how the bot runs and interacts.*

*   **`TRADING_MODE: "live"`**: Runs with real money. Change to `"testnet"` for testing.
*   **`GENERAL_CONFIG`**
    *   `DATA_FETCH_LIMIT: 300`: Loads the last 300 candles for calculations.
    *   `DAILY_SUMMARY_TIMES: ["08:10", "20:10"]`: Times to send summary reports to Discord.
    *   `TRADE_COOLDOWN_HOURS: 1.5`: **(Updated)** After closing a trade, that coin will rest for 1.5 hours.
    *   `CRON_JOB_INTERVAL_MINUTES: 1`: Must match your crontab (e.g., `*/1 * * * *`).
    *   `HEAVY_REFRESH_MINUTES: 15`: Frequency (in minutes) to scan the entire market for new opportunities.
    *   `PENDING_TRADE_RETRY_LIMIT: 3`: Max retry attempts if a BUY order fails.
    *   `CLOSE_TRADE_RETRY_LIMIT: 3`: Max retry attempts if a SELL order fails.
    *   `CRITICAL_ERROR_ALERT_COOLDOWN_MINUTES: 45`: Cooldown period before reporting the same critical error again.
    *   `RECONCILIATION_QTY_THRESHOLD: 0.95`: Threshold to detect manually closed orders.
    *   `MIN_ORDER_VALUE_USDT: 11.0`: Binance's minimum order value.
    *   `OVERRIDE_COOLDOWN_SCORE: 7.5`: Special score to bypass the cooldown period.
    *   `ORPHAN_ASSET_MIN_VALUE_USDT: 10.0`: Warns about "orphan" assets > $10.
    *   `TOP_N_OPPORTUNITIES_TO_CHECK: 7`: **(New)** Anti-FOMO, considers the top 7 opportunities instead of just 1.
    *   `MOMENTUM_FILTER_CONFIG`: **(New)** Configuration for the "gatekeeper" filter.

### PART 2: CAPITAL & RISK MANAGEMENT
*These are the rules about money, how the bot protects and grows capital.*

*   **DYNAMIC CAPITAL ENGINE (Inside `GENERAL_CONFIG`)**
    *   `DEPOSIT_DETECTION_MIN_USD: 10.0` & `_PCT: 0.01`: How the bot detects if you've deposited/withdrawn funds.
    *   `AUTO_COMPOUND_THRESHOLD_PCT: 10.0`: Automatically compounds profits when total equity increases by 10%.
    *   `AUTO_DELEVERAGE_THRESHOLD_PCT: -10.0`: Automatically reduces risk when total equity decreases by 10%.
    *   `CAPITAL_ADJUSTMENT_COOLDOWN_HOURS: 48`: **(Updated)** After each automatic capital adjustment, the bot will wait 48 hours.
*   **`RISK_RULES_CONFIG`**
    *   `MAX_ACTIVE_TRADES: 7`: **(Updated)** The maximum number of concurrently open trades is 7.
    *   `MAX_SL_PERCENT_BY_TIMEFRAME`: **(Updated)** Maximum stop-loss limit. A 1h trade cannot have an SL further than 10%.
    *   `MAX_TP_PERCENT_BY_TIMEFRAME`: **(Updated)** Maximum take-profit limit. A 1h trade cannot have a TP further than 15%.
    *   `MIN_RISK_DIST_PERCENT_BY_TIMEFRAME`: **(New)** Safety floor for SL, ensuring SL is not set too close. E.g., a 1h trade's SL must be at least 8% away.
    *   `STALE_TRADE_RULES`: **(Updated)** Handles "stale" trades more patiently. A 1h trade now has 72 hours to perform.
    *   `STAY_OF_EXECUTION_SCORE: 6.5`: **(Updated)** "Pardon" for a stale trade if its current signal score is still above 6.5.
*   **`CAPITAL_MANAGEMENT_CONFIG` (Overall Capital Management)**
    *   `MAX_TOTAL_EXPOSURE_PCT: 0.80`: **(Updated)** Safety brake. Total capital in trades will not exceed 80% of the current USDT balance.

### PART 3: TRADING TACTICS (THE BOT'S HEART)
*This is the core part, defining how the bot analyzes, decides, and acts.*

*   **CONTEXT FILTERS (`MTF_ANALYSIS_CONFIG`, `EXTREME_ZONE_ADJUSTMENT_CONFIG`, `PRICE_ACTION_MOMENTUM_CONFIG`)**
    *   These config files adjust the base score. For example:
    *   **`MTF_ANALYSIS_CONFIG`**: Reward/penalty factors have been made more moderate (`1.05`, `0.95`, `0.93`).
    *   **`EXTREME_ZONE_ADJUSTMENT_CONFIG`**: Max reward `+15%`, max penalty `-10%`. The impact is multiplied by `1.25` during a BB Squeeze.
*   **4-ZONE MODEL & `ZONE_BASED_POLICIES`**
    *   The bot divides the market into 4 types of "weather" and allocates capital accordingly:
        *   `LEADING_ZONE`: Uses 4.0% of capital.
        *   `COINCIDENT_ZONE`: Uses 5.0% of capital.
        *   `LAGGING_ZONE`: Uses 6.0% of capital.
        *   `NOISE_ZONE`: Uses 3.0% of capital.
*   **`TACTICS_LAB` (Library of Tactics)**
    *   This is the "brain" of the tactics. Each tactic has its own rules, for example:
        *   **`Balanced_Trader`**:
            *   `OPTIMAL_ZONE`: `LAGGING`, `COINCIDENT`
            *   `ENTRY_SCORE: 6.5`
            *   `RR: 2.2`
            *   `ATR_SL_MULTIPLIER: 2.5`
            *   Uses all context filters.
        *   **`Dip_Hunter`**:
            *   `OPTIMAL_ZONE`: `LEADING`, `COINCIDENT`
            *   `ENTRY_SCORE: 6.8`
            *   `RR: 1.8` (Not greedy)
            *   `ATR_SL_MULTIPLIER: 3.2` (Extra wide safety net)
            *   Does **not** use `MOMENTUM_FILTER` because momentum is usually weak when catching a dip.

### PART 4: ACTIVE TRADE MANAGEMENT & AUXILIARY ACTIONS

*   **`ACTIVE_TRADE_MANAGEMENT_CONFIG`**
    *   `EARLY_CLOSE_ABSOLUTE_THRESHOLD: 4.0`: **(Updated)** If the signal score drops below 4.0, close the trade immediately.
    *   `EARLY_CLOSE_RELATIVE_DROP_PCT: 0.30`: **(Updated)** If the signal score drops by 30%, sell 40% of the position.
    *   **`PROFIT_PROTECTION`**: **(Upgraded)** Adaptive profit protection by timeframe.
        *   **1h Trade**: Activates at `+1.5%` profit, takes profit if PnL drops `0.75%` from its peak.
        *   **4h Trade**: Activates at `+3.0%` profit, takes profit if PnL drops `1.5%` from its peak.
*   **`DCA_CONFIG` (Dollar-Cost Averaging)**
    *   `ENABLED: True`: Enables/disables the DCA feature.
    *   `MAX_DCA_ENTRIES: 2`: Allows a maximum of 2 DCA entries.
    *   `TRIGGER_DROP_PCT_BY_TIMEFRAME`: **(Upgraded)** DCA threshold per timeframe. E.g., 1h is `-6.0%`, 4h is `-8.0%`, 1d is `-10.0%`.
    *   `SCORE_MIN_THRESHOLD: 6.5`: Only DCA if the current signal score is still good.
    *   `CAPITAL_MULTIPLIER: 0.5`: **(Updated)** The next DCA entry will use 50% of the capital of the previous entry.
    *   `DCA_COOLDOWN_HOURS: 8`: Wait at least 8 hours between DCA entries.
*   **`DYNAMIC_ALERT_CONFIG` & `ALERT_CONFIG`**
    *   Settings for the bot to send update notifications to Discord, with adjustable frequency to avoid spam.
