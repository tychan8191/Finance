# Raidillon Capital: Options Backtesting Framework

**Prepared for:** Raidillon Capital
**As-Of:** January 19, 2026
**Document Version:** 1.0

---

## Table of Contents

1. [Strategy Inventory from Uploaded Documents](#1-strategy-inventory-from-uploaded-documents)
2. [Backtest Spec Cards](#2-backtest-spec-cards)
3. [Conflict Log & Reconciliation](#3-conflict-log--reconciliation)
4. [Notebook-by-Notebook Plan](#4-notebook-by-notebook-plan)
5. [Code Architecture](#5-code-architecture)
6. [Data Acquisition & Ingestion Plan](#6-data-acquisition--ingestion-plan)
7. [Required CSV Files with Schemas](#7-required-csv-files-with-schemas)
8. [Validation Checklist (Anti-Bias Protocol)](#8-validation-checklist-anti-bias-protocol)
9. [Assumptions Log](#9-assumptions-log)
10. [Next Actions: What to Upload First](#10-next-actions-what-to-upload-first)

---

## 1. Strategy Inventory from Uploaded Documents

I extracted every unique strategy/scenario from the uploaded documents. Below is the consolidated inventory grouped by underlying, structure, and catalyst type.

### 1.1 Tier A: High Conviction Strategies (Scores 75+)

| # | Ticker | Theme | Structure | Catalyst Type | Catalyst Date | Entry Window | Docs Found |
|---|--------|-------|-----------|--------------|---------------|--------------|------------|
| 1 | **VIX** | Volatility Arbitrage | Debit Call Spread (18/28 or 20/30) | FOMC + Earnings Cluster | Jan 28-30, 2026 | Jan 21-24 | All 6 docs |
| 2 | **VLO** | Refiner / Venezuela | Debit Call Spread (180/195) | Earnings (BMO) | Jan 29, 2026 | Jan 27-28 | All 6 docs |
| 3 | **KRE** | Regional Banks | Debit Call Spread (67/72) | Bank Earnings + FOMC | Jan 21-28, 2026 | Jan 22 | 4 docs |
| 4 | **KTOS** | Defense / Drone | Debit Call Spread (130/145) | Defense EO Deadline | Feb 6, 2026 | Jan 21-24 | 4 docs |
| 5 | **GS** | Investment Banking | Equity / Call Spread | Post-Earnings Drift | Post Jan 15, 2026 | Jan 21-24 | 3 docs |

### 1.2 Tier B: Medium Conviction Strategies (Scores 60-74)

| # | Ticker | Theme | Structure | Catalyst Type | Catalyst Date | Entry Window | Docs Found |
|---|--------|-------|-----------|--------------|---------------|--------------|------------|
| 6 | **MPC** | Refiner | Debit Call Spread (175/190) | Earnings (BMO) | Feb 3, 2026 | Jan 29-30 | 5 docs |
| 7 | **DHT** | Tanker / VLCC | Equity | Earnings | Feb 4-11, 2026 | Jan 21-Feb 3 | 3 docs |
| 8 | **AMD** | Semiconductor / AI | Debit Call Spread (225/245) | Earnings (AMC) | Feb 3, 2026 | Jan 28-Feb 2 | 5 docs |
| 9 | **MSFT** | Cloud / SaaS | Debit Call Spread (430/450) | Earnings (AMC) | Jan 28, 2026 | Jan 22-24 | 5 docs |
| 10 | **META** | Mega Tech | Debit Call Spread | Earnings (AMC) | Jan 28, 2026 | Jan 27 | 3 docs |
| 11 | **RTX** | Defense (Short/Hedge) | Debit Put Spread (115/105) | Defense EO + Earnings | Jan 27, Feb 6 | Jan 27 | 3 docs |

### 1.3 Hedging Positions

| # | Ticker | Theme | Structure | Purpose | Entry Window |
|---|--------|-------|-----------|---------|--------------|
| 12 | **SPY** | Portfolio Hedge | Long Put (~5% OTM) | Tail Risk Protection | Jan 21 |
| 13 | **VIX** | Convexity Hedge | Call Spread | Stress Event Insurance | Jan 21 |

### 1.4 Avoid List (Thesis Broken or Poor R/R)

| Ticker | Reason | Resolution |
|--------|--------|------------|
| HAL/SLB | Venezuela revenue years away; FY26 EPS -4% | Do not trade |
| AVAV | 151x P/E after 250% run | Use KTOS instead |
| NN | Binary FCC risk; insider selling | Max 1% lottery if any |
| NVDA (Jan) | Earnings Feb 25, not January | Wait until mid-Feb |

---

## 2. Backtest Spec Cards

Each strategy receives a detailed specification card for backtesting implementation.

---

### SPEC CARD 1: VIX Volatility Call Spread

**Strategy Name:** VIX_VOL_CALL_SPREAD_FEB

**Instruments:**
- Long: VIX Feb 18 Call (or 17/20 depending on variant)
- Short: VIX Feb 28 Call (or 25/30 depending on variant)
- Underlying: VIX Index (CBOE Volatility Index)

**Signal Rules (Entry):**
- Condition 1: VIX spot < 17 (low vol regime)
- Condition 2: CFTC net speculative shorts > 80,000 contracts (crowded short)
- Condition 3: Dense catalyst window approaching (FOMC + 3+ mega-cap earnings within 72 hours)
- Entry Timing: 3-7 days before catalyst cluster
- Entry Window: Jan 21-24, 2026 (historical: 3-7 days pre-FOMC)

**Signal Rules (Exit):**
- Take Profit: VIX spikes > 22-25 (spread at 70-80% max value)
- Time Stop: If no spike by 10 days post-catalyst, close to salvage time value
- Kill Switch: VIX drops below 12 for 2+ consecutive days (vol regime shift)
- Expiration: Feb 19, 2026

**Position Sizing Rule:**
- Allocate 3-5% of NAV as maximum risk (premium paid)
- Conservative: $250-300; Base: $300-350; Aggressive: $500

**Risk Rules:**
- Max Loss: Premium paid (defined risk)
- Max single position loss: 5% of NAV
- No rolling unless original thesis still intact

**Data Required:**
| Table | Columns Needed |
|-------|----------------|
| vix_index.csv | date, vix_open, vix_high, vix_low, vix_close |
| vix_options_eod.csv | date, expiration, strike, right, bid, ask, implied_vol, delta, theta, vega |
| vix_futures_curve.csv | date, vx1, vx2, vx3, vx4 (front 4 months) |
| vix_settlement.csv | expiration_date, settlement_value, settlement_type (SOQ) |
| calendar_events.csv | event_timestamp, event_type (FOMC, EARNINGS), ticker, confirmed |
| cftc_cot.csv | report_date, net_speculative_position |

**Known Pitfalls:**
1. **European-style exercise:** VIX options cannot be exercised early; cash-settled at SOQ
2. **AM Settlement:** VIX options settle to Special Opening Quotation (SOQ), not closing VIX
3. **Futures vs Spot:** VIX options price off futures, not spot VIX. The Feb 18c is relative to Feb VIX futures (~18-19), not spot (~15.5)
4. **Contango decay:** If VIX futures are in contango, long positions lose value as futures converge to spot
5. **Bid-ask spreads:** VIX options can have wide spreads ($0.15-0.50+); use mid-price with slippage adjustment

---

### SPEC CARD 2: VLO Earnings Call Spread

**Strategy Name:** VLO_EARNINGS_CALL_SPREAD_FEB

**Instruments:**
- Long: VLO Feb 21 $180 Call
- Short: VLO Feb 21 $195 Call
- Underlying: VLO (Valero Energy Corporation)

**Signal Rules (Entry):**
- Condition 1: Gulf Coast 3-2-1 crack spread > $17/bbl
- Condition 2: Stock price within 5% of 52-week high (momentum)
- Condition 3: Historical earnings beat rate > 60% (VLO: 75% per docs)
- Condition 4: IV Rank < 50% (options "cheap" relative to historical)
- Entry Timing: 2-5 days before earnings announcement
- Entry Window: Jan 27-28, 2026

**Signal Rules (Exit):**
- Take Profit: Stock surges to $190+ post-earnings (spread at 60-70% max value)
- Stop Loss: Stock drops >8% pre-earnings on sector news
- Time Stop: Close by Feb 14 (avoid last-week theta decay)
- Thesis Invalidation: Crack spreads collapse < $15/bbl

**Position Sizing Rule:**
- Allocate 3.5-5% of NAV as maximum risk
- Base: $350-400 premium

**Risk Rules:**
- Max Loss: $400 (debit paid)
- Exit immediately if crack spreads < $15/bbl sustained

**Data Required:**
| Table | Columns Needed |
|-------|----------------|
| equities_ohlcv.csv | timestamp, ticker='VLO', open, high, low, close, adj_close, volume |
| options_eod.csv | date, underlying='VLO', expiration, strike, right, bid, ask, implied_vol, delta, theta, vega |
| calendar_events.csv | event_timestamp, event_type='EARNINGS', ticker='VLO', event_label, confirmed |
| corporate_actions.csv | ex_date, ticker='VLO', action_type, value |
| crack_spreads.csv | date, region='USGC', spread_3_2_1 |
| earnings_surprises.csv | ticker, quarter, eps_actual, eps_estimate, surprise_pct |

**Known Pitfalls:**
1. **Earnings timestamp:** BMO (Before Market Open) earnings must be treated as pre-open catalyst; signal generates EOD prior day
2. **IV crush:** Implied volatility typically drops 30-50% post-earnings; spread structures mitigate but don't eliminate
3. **Dividend impact:** VLO pays quarterly dividend; verify no ex-date between entry and expiry that affects short call assignment risk
4. **Sector correlation:** VLO and MPC have 0.92 correlation; treat as single cluster for risk

---

### SPEC CARD 3: KRE Regional Banks Call Spread

**Strategy Name:** KRE_BANKS_CALL_SPREAD_FEB

**Instruments:**
- Long: KRE Feb 21 $67 Call
- Short: KRE Feb 21 $72 Call
- Underlying: KRE (SPDR S&P Regional Banking ETF)

**Signal Rules (Entry):**
- Condition 1: Major bank (JPM, GS) beats earnings with NIM expansion commentary
- Condition 2: Yield curve normal/steepening (not inverted)
- Condition 3: 10Y-2Y spread positive
- Condition 4: No regional bank CRE distress headlines
- Entry Timing: 1-2 days after JPM/GS earnings confirm thesis
- Entry Window: Jan 22, 2026

**Signal Rules (Exit):**
- Take Profit: KRE reaches $72+ (spread at max value)
- Time Stop: Close by Feb 14
- Thesis Invalidation: CRE write-offs spike at any regional bank; 10Y yield moves >25bps in a week

**Position Sizing Rule:**
- Allocate 1.5-2.5% of NAV as maximum risk
- Base: $150-200 premium

**Risk Rules:**
- Max Loss: $200 (debit paid)
- Exit if government shutdown extends >3 days (deposit concentration risk)

**Data Required:**
| Table | Columns Needed |
|-------|----------------|
| equities_ohlcv.csv | timestamp, ticker='KRE', open, high, low, close, adj_close, volume |
| options_eod.csv | date, underlying='KRE', expiration, strike, right, bid, ask, implied_vol |
| calendar_events.csv | event_timestamp, event_type='EARNINGS', ticker IN ('JPM','GS','PNC','USB'), confirmed |
| rates_curve.csv | date, tenor_2y, tenor_10y, rate_annualized |
| sector_flows.csv | date, ticker='KRE', net_flow_usd |

**Known Pitfalls:**
1. **ETF composition changes:** KRE holdings may shift; verify no major constituent weight changes
2. **CRE tail risk:** $936B CRE loans mature in 2026; one bank failure could cascade
3. **Government shutdown:** Regional banks hold disproportionate government deposits

---

### SPEC CARD 4: MSFT Earnings Call Spread

**Strategy Name:** MSFT_EARNINGS_CALL_SPREAD_JAN31

**Instruments:**
- Long: MSFT Jan 31 $430 Call
- Short: MSFT Jan 31 $450 Call
- Underlying: MSFT (Microsoft Corporation)

**Signal Rules (Entry):**
- Condition 1: Azure growth guidance > 20% (from prior quarter)
- Condition 2: Stock price < $435 at entry (not overextended)
- Condition 3: IV Rank < 35%
- Condition 4: No hawkish Fed surprise on same-day FOMC
- Entry Timing: 3-4 days before earnings
- Entry Window: Jan 22-24, 2026

**Signal Rules (Exit):**
- Take Profit: MSFT opens Jan 29 at $445+ (spread value ~$12-15)
- Stop Loss: MSFT drops >5% post-earnings to ~$408 (close for salvage)
- Time Stop: Close by Jan 30 (expiry Jan 31)

**Position Sizing Rule:**
- Allocate 3.5-4% of NAV
- Base: $350-400 premium

**Risk Rules:**
- Max Loss: $350 (debit paid)
- No new entries within 30 minutes of FOMC announcement

**Data Required:**
| Table | Columns Needed |
|-------|----------------|
| equities_ohlcv.csv | timestamp, ticker='MSFT', open, high, low, close, adj_close, volume |
| options_eod.csv | date, underlying='MSFT', expiration, strike, right, bid, ask, implied_vol, delta, theta, vega, open_interest |
| calendar_events.csv | event_timestamp, event_type IN ('EARNINGS','FOMC'), ticker='MSFT', confirmed |
| earnings_surprises.csv | ticker='MSFT', quarter, eps_actual, eps_estimate, guidance_revenue |

**Known Pitfalls:**
1. **Same-day FOMC:** MSFT earnings Jan 28 AMC coincides with FOMC decision at 2pm; Fed tone affects pre-earnings sentiment
2. **Mega-cap crowding:** MSFT, META, TSLA all report Jan 28 AMC; correlated moves across tech
3. **Short expiration:** Jan 31 expiry gives only 3 days post-earnings; rapid theta decay

---

### SPEC CARD 5: AMD Earnings Call Spread

**Strategy Name:** AMD_EARNINGS_CALL_SPREAD_FEB

**Instruments:**
- Long: AMD Feb 21 $225 Call
- Short: AMD Feb 21 $245 Call
- Underlying: AMD (Advanced Micro Devices)

**Signal Rules (Entry):**
- Condition 1: MSFT/META AI capex commentary positive (read-through from Jan 28)
- Condition 2: Stock price stable/up after Jan 28 tech earnings
- Condition 3: No China export control escalation
- Entry Timing: 2-4 days before earnings
- Entry Window: Jan 28-Feb 2, 2026 (after MSFT/META provide AI read-through)

**Signal Rules (Exit):**
- Take Profit: Spread reaches $12+ (>50% max value)
- Technical Stop: AMD breaks below $200 support pre-earnings
- Time Stop: Close by Feb 14

**Position Sizing Rule:**
- Allocate 4-5.5% of NAV
- Base: $450-550 premium

**Risk Rules:**
- Max Loss: $500-550 (debit paid)
- Tranche entry: 50% on Jan 28 after FOMC, 50% on Jan 30 if thesis intact

**Data Required:**
| Table | Columns Needed |
|-------|----------------|
| equities_ohlcv.csv | timestamp, ticker='AMD', open, high, low, close, adj_close, volume |
| options_eod.csv | date, underlying='AMD', expiration, strike, right, bid, ask, implied_vol, delta, theta, vega |
| calendar_events.csv | event_timestamp, event_type='EARNINGS', ticker IN ('AMD','NVDA','MSFT','META'), confirmed |
| earnings_surprises.csv | ticker='AMD', quarter, segment_datacenter_revenue, segment_client_revenue |

**Known Pitfalls:**
1. **China export risk:** New export controls could materially impact forward guidance
2. **NVDA shadow:** NVDA dominates AI GPU narrative; AMD as #2 gets disproportionate punishment on any AI slowdown signal
3. **High beta:** AMD has 1.8+ beta to SPX; macro sell-off amplifies losses

---

### SPEC CARD 6: SPY Protective Put (Hedge)

**Strategy Name:** SPY_PROTECTIVE_PUT_FEB

**Instruments:**
- Long: SPY Feb 21 $560-570 Put (~5% OTM)
- Underlying: SPY (SPDR S&P 500 ETF)

**Signal Rules (Entry):**
- Condition: Always enter at start of catalyst-dense period
- Purpose: Portfolio insurance, not speculation
- Entry Timing: Immediately at market open
- Entry Window: Jan 21, 2026

**Signal Rules (Exit):**
- Monetize: If SPY drops >5%, sell half to lock gains; roll remainder lower
- Expire: If no significant drop, accept as insurance cost (expires worthless)

**Position Sizing Rule:**
- Allocate 2-3.5% of NAV as insurance budget
- Base: $200-350 premium

**Risk Rules:**
- Max Loss: Premium paid (expected to lose in base case)
- This is a hedge, not a directional bet

**Data Required:**
| Table | Columns Needed |
|-------|----------------|
| equities_ohlcv.csv | timestamp, ticker='SPY', open, high, low, close, adj_close, volume |
| options_eod.csv | date, underlying='SPY', expiration, strike, right, bid, ask, implied_vol, delta, theta, vega |
| vix_index.csv | date, vix_close (for hedge cost timing) |

**Known Pitfalls:**
1. **Put premium sensitivity to VIX:** If VIX spikes before entry, put becomes expensive
2. **Delta drift:** 5% OTM put has ~0.15-0.20 delta; limited protection unless deep sell-off

---

### SPEC CARD 7: KTOS Defense Call Spread (Aggressive Variant)

**Strategy Name:** KTOS_DEFENSE_CALL_SPREAD_FEB

**Instruments:**
- Long: KTOS Feb 21 $130 Call
- Short: KTOS Feb 21 $145 Call
- Underlying: KTOS (Kratos Defense & Security Solutions)

**Signal Rules (Entry):**
- Condition 1: Defense EO "Prioritizing the Warfighter" confirmed (Jan 7 signed)
- Condition 2: CEO insider selling acknowledged but discounted (10b5-1 plan)
- Condition 3: Feb 6 contractor ID deadline creates binary event
- Entry Timing: Pre-deadline positioning
- Entry Window: Jan 21-24, 2026

**Signal Rules (Exit):**
- Take Profit: KTOS named as EO-compliant contractor; stock +10%
- Stop Loss: Tight -5% from entry given crowding
- Thesis Invalidation: KTOS named as underperformer or EO reversed

**Position Sizing Rule:**
- Allocate 3-3.5% of NAV (reduced due to crowding risk)
- Aggressive only: $300-350 premium

**Risk Rules:**
- Max Loss: $350 (debit paid)
- Tight stop due to P/E ~900x and $71M insider selling

**Data Required:**
| Table | Columns Needed |
|-------|----------------|
| equities_ohlcv.csv | timestamp, ticker='KTOS', open, high, low, close, adj_close, volume |
| options_eod.csv | date, underlying='KTOS', expiration, strike, right, bid, ask (WIDE SPREADS) |
| calendar_events.csv | event_timestamp, event_type='POLICY', event_label='Defense EO Deadline', confirmed |
| insider_transactions.csv | ticker='KTOS', transaction_date, insider_name, transaction_type, shares, price |

**Known Pitfalls:**
1. **Wide bid-ask spreads:** KTOS options have $0.50-$2.00+ spreads; execution challenging
2. **Limited liquidity:** Open interest may be insufficient for clean exit
3. **Valuation extreme:** P/E ~900x; any disappointment causes violent repricing
4. **Insider selling:** $71M in 90 days from CEO and others; informed selling signal

---

### SPEC CARD 8: RTX Defense Put Spread (Pairs Hedge with KTOS)

**Strategy Name:** RTX_DEFENSE_PUT_SPREAD_FEB

**Instruments:**
- Long: RTX Feb 21 $115 Put
- Short: RTX Feb 21 $105 Put
- Underlying: RTX (Raytheon Technologies)

**Signal Rules (Entry):**
- Condition: Paired with KTOS long as defense sector hedge
- Thesis: RTX explicitly named as "least responsive" in Trump's Jan 7 EO
- Entry Timing: Same as KTOS entry
- Entry Window: Jan 21-24, 2026

**Signal Rules (Exit):**
- Take Profit: RTX named as underperforming contractor; stock -5-10%
- Stop Loss: RTX surges on EO reversal
- Pairs Exit: Close both legs if defense sector narrative shifts

**Position Sizing Rule:**
- Allocate 2.5% of NAV (smaller than KTOS due to hedge nature)
- Aggressive only: $250 premium

**Risk Rules:**
- Max Loss: $250 (debit paid)
- Always exit RTX when exiting KTOS (maintain pairs integrity)

**Data Required:**
| Table | Columns Needed |
|-------|----------------|
| equities_ohlcv.csv | timestamp, ticker='RTX', open, high, low, close, adj_close, volume |
| options_eod.csv | date, underlying='RTX', expiration, strike, right, bid, ask, implied_vol |
| calendar_events.csv | event_timestamp, event_type IN ('EARNINGS','POLICY'), ticker='RTX', confirmed |

**Known Pitfalls:**
1. **Large cap stability:** RTX is $150B+ market cap; less volatile than KTOS
2. **Defense rally:** Sector momentum could lift all boats despite EO
3. **40% government revenue:** Actual contract losses take quarters to materialize in financials

---

## 3. Conflict Log & Reconciliation

The following conflicts were identified across the uploaded documents and require reconciliation before backtesting:

| Item | Document Claims | Verified Reality | Resolution for Backtest |
|------|-----------------|------------------|------------------------|
| **NVDA Earnings** | "Late January" (Q4 Playbook) | Feb 25, 2026 AMC | Exclude NVDA from Jan catalyst window; backtest as Feb 25 event |
| **VLO Strikes** | $130/$145 (old docs) | VLO at ~$183-185 | Use $180/$195 strikes; old strikes deep ITM and obsolete |
| **AMD Strikes** | $140/$155 (old docs) | AMD at ~$228 | Use $225/$245 strikes; old strikes 40% ITM |
| **KRE Strikes** | $62/$67 (old docs) | KRE at ~$66.66 | Use $67/$72 strikes; old strikes at max profit |
| **KTOS Price** | $113-130 cited | Now ~$132 (52-week high) | Backtest must account for elevated entry; validate with actual historical prices |
| **Burry/VLO Claim** | "Burry owns VLO" | Q3 2025 13F shows NO position; Scion deregistered Nov 2025 | **REJECTED** - Do not use as signal |
| **Risk Limit** | 5% per trade vs 2.5% per trade | Internal policy conflict | Use 4% for Base; 2.5% for Conservative; 5% for Aggressive |
| **VIX Regime** | "VIX ~18-20 elevated" | VIX at 15-16 near lows | Backtest must verify VIX level at entry; adjust strike selection dynamically |
| **MPC vs VLO Priority** | Both ranked as refiner plays | VLO scores 78 vs MPC 72 | VLO is primary; MPC secondary/confirmation |

---

## 4. Notebook-by-Notebook Plan

The following Jupyter notebooks implement the backtesting framework in a logical, modular sequence:

### 4.1 Environment & Setup

**`00_environment_check.ipynb`**
- Purpose: Validate Python environment, installed packages, and folder structure
- Checks: numpy, pandas, scipy, matplotlib, plotly, yfinance (optional), py_vollib (for Greeks)
- Output: Environment report; creates requirements.txt if missing

### 4.2 Data Pipeline

**`01_data_ingest_validate.ipynb`**
- Purpose: Load all CSV files from `data/raw/`, validate schemas, clean data
- Key Functions:
  - `load_equities_ohlcv()` - with split/dividend adjustment validation
  - `load_options_eod()` - with OCC symbol parsing
  - `load_calendar_events()` - with timestamp timezone normalization
  - `load_vix_data()` - spot, futures, settlements
- Output: Cleaned DataFrames saved to `data/processed/`; data quality report

**`02_strategy_inventory_from_docs.ipynb`**
- Purpose: Parse strategy definitions from uploaded documents into structured config
- Output: `config/strategies.yaml` with all strategy parameters
- This notebook operationalizes the Spec Cards into machine-readable format

### 4.3 Core Engine

**`03_backtest_core_engine.ipynb`**
- Purpose: Implement the event-driven backtesting engine
- Components:
  - `Portfolio` class: tracks positions, cash, NAV
  - `Position` class: single or multi-leg (spreads)
  - `Event` class: market data, signal, order, fill events
  - `DataHandler`: feeds bars chronologically
  - `ExecutionHandler`: simulates fills with slippage
  - `RiskManager`: position limits, drawdown stops
- Design Pattern: Event-driven architecture with event queue
- Output: Reusable engine module in `src/engine/`

### 4.4 Strategy-Specific Backtests

**`04_backtest_VIX_call_spread.ipynb`**
- Tests VIX volatility call spread strategy
- Key Validations:
  - Uses VIX futures (not spot) for option pricing
  - Handles AM settlement (SOQ)
  - Models contango decay
- Output: Trade log, P&L curve, metrics

**`05_backtest_VLO_earnings_spread.ipynb`**
- Tests VLO earnings call spread strategy
- Key Validations:
  - Earnings timestamp is point-in-time (BMO = pre-market signal)
  - IV crush post-earnings modeled
  - Crack spread signal incorporated
- Output: Trade log, P&L curve, earnings surprise analysis

**`06_backtest_KRE_banks_spread.ipynb`**
- Tests KRE regional bank call spread
- Key Validations:
  - Bank earnings read-through timing
  - Yield curve signal validation
- Output: Trade log, P&L curve, sector correlation analysis

**`07_backtest_MSFT_earnings_spread.ipynb`**
- Tests MSFT earnings call spread
- Key Validations:
  - Same-day FOMC interaction modeled
  - Short-dated expiry theta modeled
- Output: Trade log, P&L curve

**`08_backtest_AMD_earnings_spread.ipynb`**
- Tests AMD earnings call spread
- Key Validations:
  - MSFT/META read-through signal implemented
  - Tranche entry timing
- Output: Trade log, P&L curve

**`09_backtest_SPY_protective_put.ipynb`**
- Tests SPY hedge position
- Key Validations:
  - Hedge effectiveness vs directional positions
  - Cost-of-carry analysis
- Output: Hedge P&L attribution

**`10_backtest_KTOS_RTX_pairs.ipynb`** (Aggressive variant)
- Tests KTOS/RTX defense pairs trade
- Key Validations:
  - Pairs correlation maintenance
  - Wide spread execution impact
- Output: Pairs trade attribution

### 4.5 Portfolio-Level Analysis

**`11_portfolio_backtest_base.ipynb`**
- Combines all Base Case positions into unified portfolio backtest
- Implements circuit breakers (5% weekly drawdown)
- Output: Portfolio NAV curve, drawdown analysis, risk attribution

**`12_portfolio_backtest_variants.ipynb`**
- Runs Conservative and Aggressive variants
- Compares risk-adjusted returns across variants
- Output: Variant comparison report

### 4.6 Reporting

**`NN_report_pack.ipynb`**
- Generates final backtest report with:
  - Summary statistics (CAGR if multi-year, total return, max drawdown, Sharpe)
  - Per-trade attribution table
  - Position P&L waterfall charts
  - Exposure heatmaps by theme
  - Tail outcome analysis
- Output: HTML/PDF report in `outputs/`

---

## 5. Code Architecture

### 5.1 Folder Layout

```
raidillon_backtest/
├── config/
│   ├── strategies.yaml          # Strategy parameters from Spec Cards
│   ├── execution_params.yaml    # Slippage, commissions, fill assumptions
│   └── risk_limits.yaml         # Position/portfolio constraints
├── data/
│   ├── raw/                     # Original CSV uploads (immutable)
│   ├── processed/               # Cleaned, validated DataFrames
│   └── reference/               # Static reference data (tickers, mappings)
├── src/
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── portfolio.py         # Portfolio and Position classes
│   │   ├── event.py             # Event types and queue
│   │   ├── data_handler.py      # Chronological bar feeder
│   │   ├── execution.py         # Fill simulation with slippage
│   │   └── risk_manager.py      # Drawdown stops, position limits
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── base_strategy.py     # Abstract strategy interface
│   │   ├── vix_vol_spread.py    # VIX-specific logic
│   │   ├── earnings_spread.py   # Earnings catalyst spreads
│   │   └── hedge_put.py         # Protective put logic
│   ├── data_loaders/
│   │   ├── __init__.py
│   │   ├── equities.py          # Load/validate equities_ohlcv.csv
│   │   ├── options.py           # Load/validate options_eod.csv
│   │   ├── events.py            # Load/validate calendar_events.csv
│   │   └── vix.py               # Load VIX spot, futures, settlement
│   └── utils/
│       ├── __init__.py
│       ├── greeks.py            # Black-Scholes Greeks calculation
│       ├── metrics.py           # Performance metrics (Sharpe, drawdown, etc.)
│       └── validators.py        # Data quality checks
├── notebooks/                   # Jupyter notebooks (as described above)
├── outputs/                     # Backtest results, reports
├── tests/                       # Unit tests for engine components
├── requirements.txt             # Python dependencies
└── README.md                    # Project documentation
```

### 5.2 Module Responsibilities

| Module | Responsibility |
|--------|----------------|
| `portfolio.py` | Track positions, cash, NAV; handle multi-leg spreads as atomic units |
| `event.py` | Define MarketEvent, SignalEvent, OrderEvent, FillEvent; manage event queue |
| `data_handler.py` | Iterate through historical data chronologically; no lookahead |
| `execution.py` | Convert orders to fills; apply bid-ask spread, slippage, commissions |
| `risk_manager.py` | Enforce position limits; trigger circuit breakers on drawdown |
| `base_strategy.py` | Abstract class with `generate_signals()` method for each strategy |
| `greeks.py` | Calculate delta, gamma, theta, vega from Black-Scholes (if not in data) |
| `metrics.py` | Calculate CAGR, total return, max drawdown, hit rate, Sharpe, Sortino |
| `validators.py` | Check for survivorship bias, lookahead bias, timestamp alignment |

---

## 6. Data Acquisition & Ingestion Plan

### 6.1 Data Sources by Priority

| Data Type | Recommended Source | Alternative Source | Cost |
|-----------|-------------------|-------------------|------|
| Equity OHLCV | EODHD, Polygon.io | Yahoo Finance (free, limited) | $20-100/mo |
| Options EOD | ORATS, OptionMetrics | CBOE DataShop, Polygon Options | $50-500/mo |
| VIX Index | CBOE (free delayed) | FRED (VIX close) | Free |
| VIX Futures | Quandl/Nasdaq Data Link | CBOE Futures Exchange | $50-150/mo |
| VIX Options | CBOE DataShop | ORATS | $100+/mo |
| Calendar Events | Earnings Whispers, Wall Street Horizon | Yahoo Finance API | $0-50/mo |
| CFTC COT Data | CFTC.gov (free) | Quandl | Free |
| Risk-Free Rate | FRED (SOFR, T-Bills) | Treasury.gov | Free |
| Corporate Actions | EODHD, Polygon | Yahoo Finance | Included |
| Crack Spreads | EIA.gov, Bloomberg | CME Group | $0-expensive |

### 6.2 Ingestion Pipeline

```
Step 1: Download raw data → data/raw/{source}_{asset}_{daterange}.csv
Step 2: Validate schema (columns, types, nulls) → log issues
Step 3: Clean (handle missing, adjust for splits/divs) → data/processed/
Step 4: Join datasets (options to underlying, events to prices)
Step 5: Create point-in-time snapshots (no lookahead)
```

### 6.3 Critical Time Alignment Rules

1. **Earnings timestamps:** Use actual announcement time (BMO = 8:00 AM ET, AMC = 4:15 PM ET), not just date
2. **FOMC timestamps:** Decision at 2:00 PM ET; any signal before 2:00 PM must not use decision outcome
3. **Options settlement:** VIX settles at AM SOQ, not 4:00 PM close
4. **Corporate actions:** Apply ex-date adjustments to all historical prices *before* that date

---

## 7. Required CSV Files with Schemas

### 7.1 Minimum Viable Dataset (Always Required)

#### `equities_ohlcv.csv`
```
Columns:
- timestamp: ISO8601 datetime with timezone (e.g., "2025-12-15T16:00:00-05:00")
- ticker: str, uppercase (e.g., "VLO", "MSFT")
- open: float (unadjusted)
- high: float (unadjusted)
- low: float (unadjusted)
- close: float (unadjusted)
- adj_close: float (split and dividend adjusted)
- volume: int

Example Row:
2025-12-15T16:00:00-05:00,VLO,180.25,183.50,179.80,183.15,183.15,2456789
```

#### `corporate_actions.csv`
```
Columns:
- ex_date: date (YYYY-MM-DD)
- ticker: str
- action_type: enum (DIVIDEND, SPLIT, SPINOFF)
- value: float (dividend $/share or split ratio like 2.0 for 2:1)
- notes: str (optional)

Example Row:
2025-12-01,VLO,DIVIDEND,1.07,Quarterly dividend
2025-06-15,NVDA,SPLIT,10.0,10-for-1 stock split
```

#### `calendar_events.csv`
```
Columns:
- event_timestamp: ISO8601 datetime with timezone
- event_type: enum (EARNINGS, FOMC, CPI, POLICY, OTHER)
- ticker: str or NULL for macro events
- event_label: str (descriptive name)
- timing: enum (BMO, AMC, INTRADAY) for earnings
- source: str (Company IR, Fed, etc.)
- confirmed: bool

Example Row:
2026-01-29T07:00:00-05:00,EARNINGS,VLO,Q4 2025 Earnings,BMO,Company IR,true
2026-01-28T14:00:00-05:00,FOMC,NULL,January FOMC Decision,INTRADAY,Federal Reserve,true
```

#### `rates_curve.csv`
```
Columns:
- date: date (YYYY-MM-DD)
- tenor: str (1M, 3M, 6M, 1Y, 2Y, 5Y, 10Y, 30Y)
- rate_annualized: float (as decimal, e.g., 0.0425 for 4.25%)

Example Row:
2025-12-15,3M,0.0490
2025-12-15,10Y,0.0424
```

### 7.2 Options Data (Required for All Options Strategies)

#### `options_eod.csv`
```
Columns:
- date: date (YYYY-MM-DD)
- underlying: str (ticker)
- option_symbol: str (OCC format preferred)
- expiration: date (YYYY-MM-DD)
- strike: float
- right: enum (C, P)
- bid: float
- ask: float
- last: float (optional)
- volume: int (optional)
- open_interest: int (required for liquidity validation)
- implied_vol: float (annualized, as decimal)
- delta: float (-1 to 1)
- gamma: float
- theta: float (daily, negative for longs)
- vega: float
- rho: float (optional)
- underlying_price: float (for convenience)

Example Row:
2025-12-15,VLO,VLO260220C00180000,2026-02-20,180.0,C,6.80,7.20,7.00,1523,8956,0.32,-0.55,0.045,-0.08,0.12,183.15
```

**Note on Greeks:** If your data source does not provide Greeks, the backtest engine will calculate them using Black-Scholes. You will need:
- Underlying price at quote time
- Risk-free rate (from rates_curve.csv)
- Days to expiration
- Implied volatility (REQUIRED - cannot be derived without it)

### 7.3 VIX-Specific Data (Required for VIX Strategies)

#### `vix_index.csv`
```
Columns:
- date: date (YYYY-MM-DD)
- vix_open: float
- vix_high: float
- vix_low: float
- vix_close: float

Example Row:
2025-12-15,15.25,16.80,14.90,15.86
```

#### `vix_futures_curve.csv`
```
Columns:
- date: date (YYYY-MM-DD)
- vx_m1: float (front month settle)
- vx_m2: float (second month settle)
- vx_m3: float (third month)
- vx_m4: float (fourth month)
- vx_m1_expiry: date (for roll timing)
- vx_m2_expiry: date

Example Row:
2025-12-15,16.50,17.25,17.80,18.10,2026-01-22,2026-02-19
```

#### `vix_options_eod.csv`
Same schema as `options_eod.csv` but for VIX options. Critical differences:
- Underlying is "VIX" (index, not tradeable)
- Options price relative to futures, not spot
- Settlement is AM SOQ, not PM close

#### `vix_settlement.csv`
```
Columns:
- expiration_date: date
- settlement_value: float (SOQ value)
- settlement_type: str (SOQ)
- calculation_time: str (AM opening)

Example Row:
2026-01-22,17.32,SOQ,08:30-09:00 ET
```

### 7.4 CFTC Positioning Data

#### `cftc_cot.csv`
```
Columns:
- report_date: date (Tuesday of report week)
- market: str (VIX, ES, etc.)
- noncommercial_long: int
- noncommercial_short: int
- net_speculative_position: int (long - short)
- open_interest_total: int
- pct_oi_spec_long: float
- pct_oi_spec_short: float

Example Row:
2026-01-06,VIX,45678,136081,-90403,312456,0.146,0.436
```

### 7.5 Macro/Sector Data (Strategy-Specific)

#### `crack_spreads.csv` (for VLO/MPC)
```
Columns:
- date: date
- region: str (USGC for Gulf Coast, USEC for East Coast, etc.)
- spread_3_2_1: float ($/barrel)
- spread_5_3_2: float (optional, complex configuration)
- source: str (EIA, CME)

Example Row:
2025-12-15,USGC,22.70,28.45,EIA
```

#### `earnings_surprises.csv` (for all earnings strategies)
```
Columns:
- ticker: str
- fiscal_quarter: str (e.g., "Q4 2025")
- report_date: date
- eps_actual: float
- eps_estimate: float
- eps_surprise_pct: float
- revenue_actual: float (optional)
- revenue_estimate: float (optional)
- guidance_next_q_eps: float (optional)

Example Row:
VLO,Q3 2025,2025-10-29,3.66,3.05,20.0,32500000000,31800000000,3.10
```

### 7.6 Insider Transactions (for KTOS)

#### `insider_transactions.csv`
```
Columns:
- ticker: str
- transaction_date: date
- filing_date: date
- insider_name: str
- insider_title: str
- transaction_type: enum (BUY, SELL, EXERCISE)
- shares: int
- price: float
- value_total: float
- plan_10b5_1: bool

Example Row:
KTOS,2026-01-06,2026-01-07,Eric DeMarco,CEO,SELL,191699,90.28,17306586.72,true
```

---

## 8. Validation Checklist (Anti-Bias Protocol)

The following checklist ensures the backtest does not "lie" through common pitfalls:

### 8.1 Survivorship Bias Checks

| Check | Method | Pass Criteria |
|-------|--------|---------------|
| Delisted tickers included | Verify no tickers mysteriously disappear mid-period | All tickers that existed during test period are present |
| Bankrupt companies included | Check for companies that went to zero | Include full loss trajectory |
| Merged companies handled | Trace M&A events | Proper cash-out at merger price |
| ETF composition changes | Validate KRE holdings consistency | Historical constituents match test period |

### 8.2 Lookahead Bias Checks

| Check | Method | Pass Criteria |
|-------|--------|---------------|
| Signal uses only past data | Log timestamp of each data point used in signal | Signal_timestamp >= latest_data_timestamp |
| Earnings surprise not pre-known | Verify actual EPS used only after report_date | eps_actual accessed only after event_timestamp |
| Corporate actions applied correctly | Split/div adjustment only to pre-ex_date prices | adj_close matches vendor adjustment |
| VIX settlement not pre-known | SOQ value used only after settlement time | settlement_value accessed only at expiration |

### 8.3 Execution Realism Checks

| Check | Method | Pass Criteria |
|-------|--------|---------------|
| Bid-ask spread applied | Entry at ask, exit at bid (or justified alternative) | No fills at mid without justification |
| Slippage applied | Market impact model for size vs liquidity | Slippage increases with order size / avg volume |
| Commissions applied | Per-contract and per-trade fees | Realistic broker fee schedule ($0.50-1.00/contract) |
| Fills respect NBBO | No fills outside bid-ask range | fill_price >= bid and fill_price <= ask |
| After-hours fills rejected | Options don't trade extended hours | fill_timestamp during RTH only |

### 8.4 Options-Specific Checks

| Check | Method | Pass Criteria |
|-------|--------|---------------|
| Expiration handling correct | Verify ITM options exercised/assigned | ITM by >$0.01 at expiry triggers exercise |
| Early exercise (American) modeled | Deep ITM calls near dividend may exercise early | Dividend capture logic for equity options |
| European exercise (VIX) enforced | VIX options cannot exercise early | No early exercise fills on VIX |
| AM vs PM settlement correct | VIX settles AM; equities settle PM | Correct settlement price used |
| Pin risk handled | Near-the-money at expiry creates uncertainty | Document handling approach |

### 8.5 Timestamp/Calendar Checks

| Check | Method | Pass Criteria |
|-------|--------|---------------|
| Market holidays excluded | No trades on closed days | Jan 19, 2026 (MLK) has no fills |
| Early close days handled | Market closes 1pm on some days | No fills after early close |
| Earnings timing precise | BMO vs AMC distinction maintained | BMO signal generates EOD prior day |
| FOMC timing precise | 2pm decision, 2:30pm presser | No signal uses FOMC outcome before 2pm |
| Timezone consistency | All timestamps in same timezone or UTC | No mixed timezone comparisons |

### 8.6 Greeks/Pricing Checks

| Check | Method | Pass Criteria |
|-------|--------|---------------|
| IV from market, not model | Implied vol is observed, not calculated | implied_vol column from market data |
| Delta sign correct | Calls positive, puts negative | delta(call) > 0; delta(put) < 0 |
| Theta sign correct | Time decay is negative for longs | theta < 0 for long options |
| Greeks update daily | Not stale Greeks from entry | Recompute or refresh daily |

---

## 9. Assumptions Log

The following assumptions govern the backtest execution model:

### 9.1 Execution Assumptions

| Parameter | Value | Justification |
|-----------|-------|---------------|
| Entry fill price | Ask + $0.02 slippage for debit spreads | Conservative; real fills often at mid |
| Exit fill price | Bid - $0.02 slippage for credit spreads | Conservative |
| Commission | $0.65 per contract | Tastytrade standard rate |
| Assignment fee | $5.00 per contract | Tastytrade exercise/assignment |
| Minimum order size | 1 contract | Retail scale |
| Maximum order size | 10% of open interest | Liquidity constraint |
| Fill delay | 0 seconds (assume instant) | Limit orders in liquid names |

### 9.2 Position Management Assumptions

| Parameter | Value | Justification |
|-----------|-------|---------------|
| Position sizing | Fixed premium at risk | Per spec card definitions |
| Stop loss | Thesis-based, not mechanical % | Per spec card stop conditions |
| Take profit | Per spec card targets | Not mechanical trailing stops |
| Max position hold | Until expiration or stop/target | No arbitrary time limits |
| Rolling | Not modeled (exit and re-enter) | Keep backtest simple |

### 9.3 Market Microstructure Assumptions

| Parameter | Value | Justification |
|-----------|-------|---------------|
| Bid-ask spread | From market data if available | Else assume 2% of option price |
| Liquidity | Reject trades where OI < 500 | Ensure exit possible |
| Market impact | None for orders < 5% of OI | Retail scale doesn't move market |
| Trading hours | 9:30 AM - 4:00 PM ET | Regular trading hours only |

### 9.4 Options Modeling Assumptions

| Parameter | Value | Justification |
|-----------|-------|---------------|
| Exercise style | American for equities, European for VIX | Standard conventions |
| Early exercise | Not modeled (rare in practice) | Simplification |
| Assignment | Random assignment on short legs if ITM at expiry | Standard OCC procedure |
| Dividend capture | Not modeled | Short hold periods unlikely to span ex-date |
| IV interpolation | Linear between quoted strikes | For strikes without quotes |

### 9.5 Risk-Free Rate Assumptions

| Parameter | Value | Justification |
|-----------|-------|---------------|
| Rate source | 3-month T-Bill from FRED | Standard risk-free proxy |
| Rate application | Daily from rates_curve.csv | Updated daily |
| Continuous compounding | Yes | Black-Scholes convention |

---

## 10. Next Actions: What to Upload First

To get a working backtest running, upload data in the following priority order:

### Phase 1: Minimum Viable Backtest (Upload First)

These files enable backtesting the core VIX and VLO strategies:

| File | Why First | Urgency |
|------|-----------|---------|
| `equities_ohlcv.csv` | Required for all equity strategies | **CRITICAL** |
| `options_eod.csv` | Core options pricing for all spreads | **CRITICAL** |
| `calendar_events.csv` | Defines entry/exit timing for all catalysts | **CRITICAL** |
| `vix_index.csv` | VIX spot for signal generation | **CRITICAL** |
| `rates_curve.csv` | Risk-free rate for Greeks calculation | **CRITICAL** |

**Expected Outcome:** After uploading these 5 files, you can run VLO, MSFT, AMD, KRE, and SPY backtests. VIX backtest requires additional files.

### Phase 2: VIX Strategy Enhancement

| File | Why Needed | Urgency |
|------|------------|---------|
| `vix_futures_curve.csv` | VIX options price off futures | **HIGH** |
| `vix_options_eod.csv` | Actual VIX option quotes | **HIGH** |
| `vix_settlement.csv` | AM settlement values | **HIGH** |
| `cftc_cot.csv` | Positioning signal for VIX strategy | **MEDIUM** |

### Phase 3: Strategy-Specific Add-ons

| File | Strategies Enabled | Urgency |
|------|-------------------|---------|
| `crack_spreads.csv` | VLO/MPC thesis validation | **MEDIUM** |
| `earnings_surprises.csv` | All earnings strategies | **MEDIUM** |
| `corporate_actions.csv` | Dividend/split adjustment | **MEDIUM** |
| `insider_transactions.csv` | KTOS signal validation | **LOW** |

### Phase 4: Validation & Enhancement

| File | Purpose | Urgency |
|------|---------|---------|
| `benchmark_prices.csv` (SPY, QQQ) | Portfolio correlation analysis | **LOW** |
| `sector_flows.csv` | KRE sector thesis validation | **LOW** |

---

### Data Source Suggestions

| Data Type | Free Options | Paid Options (Better Quality) |
|-----------|-------------|------------------------------|
| Equity OHLCV | Yahoo Finance via `yfinance` | Polygon.io ($29/mo), EODHD ($19/mo) |
| Options EOD | None (need paid source) | ORATS ($99/mo), Polygon Options ($49/mo) |
| VIX Data | FRED (close only), CBOE delayed | Quandl/Nasdaq Data Link ($50/mo) |
| Calendar Events | Yahoo Finance, Earnings Whispers | Wall Street Horizon ($50+/mo) |
| CFTC COT | CFTC.gov (free download) | Quandl (structured, $free tier exists) |

---

### STOP CONDITION

**If any of the Phase 1 files are missing, the backtest cannot proceed.** Please upload or provide:

1. **equities_ohlcv.csv** covering: VLO, MSFT, AMD, KRE, SPY, KTOS, RTX, MPC, DHT, GS from Oct 2024 - Jan 2026
2. **options_eod.csv** covering: same tickers, same period, strikes near-the-money ±20%
3. **calendar_events.csv** covering: all earnings dates, FOMC dates, policy dates in Jan-Feb 2026
4. **vix_index.csv** covering: Oct 2024 - Jan 2026 daily
5. **rates_curve.csv** covering: Oct 2024 - Jan 2026 daily

Once these files are uploaded, I will generate the data validation notebook and proceed with strategy backtests.

---

## Appendix A: Python Environment Setup

### requirements.txt

```
# Core
numpy>=1.24.0
pandas>=2.0.0
scipy>=1.10.0

# Visualization
matplotlib>=3.7.0
plotly>=5.14.0
seaborn>=0.12.0

# Options Pricing
py_vollib>=1.0.0
mibian>=0.1.3

# Data (optional, for API access)
yfinance>=0.2.0
pandas_datareader>=0.10.0

# Jupyter
jupyter>=1.0.0
ipykernel>=6.0.0

# Testing
pytest>=7.0.0

# Config
pyyaml>=6.0.0
```

### Conda Environment (Alternative)

```bash
conda create -n raidillon python=3.11
conda activate raidillon
pip install -r requirements.txt
```

---

## Appendix B: Example Data Validation Queries

The data validation notebook will run these checks:

```python
# Check for lookahead bias in earnings
def check_earnings_lookahead(options_df, events_df):
    """Ensure no option signals generated using post-earnings data"""
    earnings = events_df[events_df['event_type'] == 'EARNINGS']
    for _, event in earnings.iterrows():
        ticker = event['ticker']
        event_ts = event['event_timestamp']
        # Find any option prices for this ticker after this event
        # that might have been used in signals before the event
        post_event_data = options_df[
            (options_df['underlying'] == ticker) & 
            (options_df['date'] > event_ts.date())
        ]
        # ... validation logic

# Check for survivorship bias
def check_survivorship(ohlcv_df, start_date, end_date):
    """Verify no tickers mysteriously disappear"""
    tickers_at_start = set(ohlcv_df[ohlcv_df['timestamp'].dt.date == start_date]['ticker'])
    tickers_at_end = set(ohlcv_df[ohlcv_df['timestamp'].dt.date == end_date]['ticker'])
    disappeared = tickers_at_start - tickers_at_end
    if disappeared:
        print(f"WARNING: Tickers disappeared: {disappeared}")
        print("Verify these are legitimate delistings, not data gaps")
```

---

*End of Raidillon Backtest Framework Document*
