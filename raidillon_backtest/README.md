# Raidillon Backtest Framework

A production-grade backtesting framework for event-driven options strategies, designed specifically for the Venezuela intervention / volatility catalyst thesis portfolio.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Fetch market data (populates data/raw/)
python run_ingest.py

# 3. Run backtest
python run_backtest.py

# Or run a specific variant
python run_backtest.py --variant aggressive

# Or compare all variants
python run_backtest.py --compare
```

## Architecture Overview

The framework consists of four main components that work together to simulate your options trading strategies:

```
raidillon_backtest/
├── src/
│   ├── strategies/           # Strategy framework
│   │   ├── base.py          # BaseStrategy, Signal, MarketSnapshot
│   │   └── __init__.py
│   ├── engine/              # Backtest orchestration
│   │   ├── backtest.py      # BacktestEngine, DataManager
│   │   ├── portfolio.py     # Position, Portfolio tracking
│   │   └── __init__.py
│   ├── data_loaders/        # Data ingestion and loading
│   │   ├── ingest.py        # DataIngestor (fetches from APIs)
│   │   ├── options.py       # CSV data loaders
│   │   └── sources/         # API connectors (CBOE, CFTC, TastyTrade)
│   └── utils/               # Helper functions
├── config/
│   └── strategies.yaml      # Strategy definitions and parameters
├── data/
│   ├── raw/                 # Downloaded CSV files
│   ├── processed/           # Transformed data
│   └── reference/           # Static reference data
├── outputs/                 # Backtest results
├── run_ingest.py           # Data fetching entry point
├── run_backtest.py         # Backtest entry point
└── requirements.txt        # Python dependencies
```

## How It Works

### 1. Data Ingestion (`run_ingest.py`)

The data ingestion system fetches market data from free sources:

| File | Source | Contents |
|------|--------|----------|
| `equities_ohlcv.csv` | yfinance | Daily OHLCV for VLO, MPC, KTOS, AMD, etc. |
| `vix_index.csv` | FRED | VIX spot levels |
| `rates_curve.csv` | FRED | Treasury rates (3M, 2Y, 10Y, 30Y) |
| `calendar_events.csv` | Generated | Earnings, FOMC, policy events |
| `crack_spreads.csv` | EIA | Refinery margin data |
| `cftc_cot.csv` | CFTC | Speculative positioning in VIX futures |
| `options_eod.csv` | Template | Options chains (requires ORATS for historical) |

### 2. Strategy Framework (`src/strategies/`)

Strategies are defined in `config/strategies.yaml` and loaded at runtime. The VerticalSpreadStrategy handles debit/credit spreads (most portfolio strategies). Each strategy implements `check_entry()` and `check_exit()` methods.

### 3. Backtest Engine (`src/engine/backtest.py`)

The engine steps through time day-by-day, building MarketSnapshots and processing signals through the Portfolio. It respects risk limits and includes circuit breakers.

### 4. Portfolio Management (`src/engine/portfolio.py`)

Tracks positions, cash, P&L, NAV history, and drawdowns. Supports multi-leg spreads as atomic units.

## Running Backtests

```bash
# Basic - base variant, Jan 21 - Feb 28, 2026
python run_backtest.py

# Specific variant
python run_backtest.py --variant conservative

# Custom dates
python run_backtest.py --start 2026-01-15 --end 2026-03-15

# Compare all variants
python run_backtest.py --compare
```

## Output Files

Results saved to `outputs/`:
- `daily_metrics_*.csv` - NAV, drawdown, metrics by day
- `trade_log_*.csv` - All trades with P&L
- `signals_*.csv` - Entry/exit signals
- `report_*.txt` - Summary report

## Configuration

Edit `config/strategies.yaml` to customize:
- Global parameters (NAV, commissions)
- Risk limits by variant
- Strategy definitions (entry/exit logic)
- Catalyst calendar

## Dependencies

```bash
pip install -r requirements.txt
```

Core: pandas, numpy, yfinance, pandas-datareader, pyyaml
Optional: py_vollib, tastytrade, jupyter
