# Raidillon Backtest Framework - Data Ingestion System

## Overview

This data ingestion system automatically fetches historical market data from multiple free sources, minimizing the number of CSV files you need to manually upload. The system is designed specifically for options-focused event-driven strategies, with particular emphasis on the Venezuela intervention / volatility catalyst thesis outlined in your strategies.yaml.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the full data ingestion (fetches all free data sources)
python run_ingest.py

# Or run from within the package
python -m src.data_loaders.ingest --all
```

After running, you'll find all data files in `data/raw/`. The **only file you may need to manually enhance** is `options_eod.csv` if you need historical options data for backtesting (ORATS subscription recommended).

## Data Sources & What Gets Fetched Automatically

| Dataset | Source | Cost | File Created |
|---------|--------|------|--------------|
| Equity OHLCV | yfinance | FREE | `equities_ohlcv.csv` |
| VIX Index | FRED | FREE | `vix_index.csv` |
| Treasury Rates | FRED | FREE | `rates_curve.csv` |
| VIX Futures | CBOE CFE | FREE | `vix_futures_curve.csv` |
| Calendar Events | Auto-generated | FREE | `calendar_events.csv` |
| Crack Spreads | EIA/yfinance | FREE | `crack_spreads.csv` |
| CFTC COT | CFTC.gov | FREE | `cftc_cot.csv` |
| Options EOD | Template only | - | `options_eod.csv` (template) |

## Tickers Tracked

Based on your `strategies.yaml`, the system automatically tracks these 15 tickers:

```
AMD, AAPL, DHT, GS, KRE, KTOS, META, MPC, MSFT, NVDA, RTX, SPY, TSLA, VIX, VLO
```

## Architecture

```
raidillon_backtest/
├── src/
│   └── data_loaders/
│       ├── __init__.py          # Package exports
│       ├── options.py           # CSV data loaders (existing)
│       ├── ingest.py            # Main ingestion orchestrator (NEW)
│       └── sources/
│           ├── __init__.py      # Source connectors exports
│           ├── cboe_vix.py      # CBOE VIX futures fetcher
│           ├── cftc_cot.py      # CFTC COT data fetcher
│           └── tastytrade_client.py  # TastyTrade API wrapper
├── data/
│   ├── raw/                     # Downloaded/generated CSVs go here
│   ├── processed/               # Cleaned/transformed data
│   └── reference/               # Static reference data
├── config/
│   └── strategies.yaml          # Strategy definitions
└── run_ingest.py                # Main entry point
```

## Detailed Usage

### Option 1: Fetch Everything

```bash
python run_ingest.py
```

This is the recommended approach. It fetches all available free data sources for the date range October 2024 through February 2026 (your catalyst window).

### Option 2: Fetch Specific Datasets

```bash
# Just equities and VIX
python -m src.data_loaders.ingest --equities --vix

# Just rates and calendar
python -m src.data_loaders.ingest --rates --calendar
```

### Option 3: Custom Date Range

```bash
python -m src.data_loaders.ingest --all --start 2024-06-01 --end 2026-06-30
```

### Option 4: Programmatic Usage

```python
from src.data_loaders import DataIngestor

# Initialize with custom settings
ingestor = DataIngestor(
    config_path='config/strategies.yaml',
    start_date='2024-10-01',
    end_date='2026-02-28'
)

# Fetch all datasets
results = ingestor.fetch_all()

# Or fetch individually
equities_df = ingestor.fetch_equities()
vix_df = ingestor.fetch_vix_index()
rates_df = ingestor.fetch_rates_curve()
calendar_df = ingestor.generate_calendar_events()
```

## Options Data Strategy

### The Challenge

Historical options EOD data is the most expensive and hardest to obtain. Unlike equity prices (free via yfinance) or VIX index values (free via FRED), comprehensive options chains require paid subscriptions.

### Your Options

1. **TastyTrade Backtester API** (Free with funded account)
   - The backtester at `backtester.vast.tastyworks.com` has 10+ years of options data
   - Can be accessed via API for strategy simulation
   - Best for: Validating specific trade setups historically
   - Limitation: Not designed for bulk CSV export

2. **ORATS** ($99/month)
   - Full historical options chains with Greeks
   - Clean CSV format that matches our expected schema
   - Best for: Comprehensive backtesting infrastructure
   - Recommended if you're serious about systematic backtesting

3. **Live TastyTrade API** (Free with account)
   - Provides real-time options quotes
   - Can accumulate historical data going forward
   - Best for: Forward-looking analysis and live trading

### Using TastyTrade for Live Options

```bash
# Set environment variables
export TASTYTRADE_USERNAME='your_username'
export TASTYTRADE_PASSWORD='your_password'

# Fetch live options chains
python -m src.data_loaders.ingest --options
```

```python
from src.data_loaders.sources.tastytrade_client import TastyTradeClient

client = TastyTradeClient()

# Get option chain
chain = client.get_option_chain('VLO', expiration=date(2026, 2, 21))

# Get specific quote for your spread
quotes = client.get_chain_for_spread(
    underlying='VLO',
    expiration=date(2026, 2, 21),
    long_strike=180,
    short_strike=195,
    right='C'
)

print(f"Long leg ask: ${quotes['long'].ask}")
print(f"Short leg bid: ${quotes['short'].bid}")
print(f"Net debit: ${quotes['long'].ask - quotes['short'].bid:.2f}")
```

## VIX-Specific Data

VIX options are unique because they settle against VIX futures, not spot VIX. The system fetches:

1. **VIX Index** (spot) - From FRED
2. **VIX Futures Curve** - From CBOE CFE
3. **VIX Settlement Values** - Extracted from futures expiration data

```python
# The ingestor handles this automatically, but you can also:
from src.data_loaders.sources.cboe_vix import fetch_vix_futures_term_structure

vix_curve = fetch_vix_futures_term_structure(
    start_date=date(2024, 10, 1),
    end_date=date(2026, 2, 28)
)

# Result has: date, vx_m1, vx_m2, vx_m3, vx_m4, vx_m1_expiry, vx_m2_expiry
```

## CFTC Positioning Data

For the VIX crowded short thesis, the system fetches Commitment of Traders data:

```python
from src.data_loaders.sources.cftc_cot import fetch_cot_data, get_latest_positioning

# Get historical positioning
cot = fetch_cot_data('VIX', start_date=date(2024, 1, 1))

# Check current positioning
latest = get_latest_positioning()
print(f"Net speculative position: {latest['net_position']:,}")
print(f"Position type: {latest['position_type']}")  # NET_SHORT or NET_LONG
```

## Integration with Existing Loaders

The new data ingestion system populates files that work directly with your existing loaders:

```python
from src.data_loaders import OptionsDataLoader, EquitiesDataLoader, CalendarEventsLoader

# Load the auto-generated files
equities = EquitiesDataLoader('data/raw/equities_ohlcv.csv')
equities_df = equities.load()

calendar = CalendarEventsLoader('data/raw/calendar_events.csv')
calendar_df = calendar.load()

# Get specific data
vlo_price = equities.get_close('VLO', date(2026, 1, 27))
earnings_date = calendar.get_earnings_date('VLO')
```

## Troubleshooting

### "No module named 'tastytrade'"

```bash
pip install tastytrade
```

### "TastyTrade credentials not found"

```bash
export TASTYTRADE_USERNAME='your_username'
export TASTYTRADE_PASSWORD='your_password'
```

### "Failed to fetch VIX futures from CBOE"

The CBOE website structure occasionally changes. If direct download fails, the system creates a placeholder with instructions for manual download.

### "pandas_datareader not installed"

```bash
pip install pandas-datareader
```

## File Schemas

### equities_ohlcv.csv

```csv
timestamp,ticker,open,high,low,close,adj_close,volume
2025-12-15T16:00:00-05:00,VLO,180.25,183.50,179.80,183.15,183.15,2456789
```

### vix_index.csv

```csv
date,vix_open,vix_high,vix_low,vix_close
2025-12-15,15.25,16.80,14.90,15.86
```

### rates_curve.csv

```csv
date,tenor,rate_annualized
2025-12-15,3M,0.0490
2025-12-15,2Y,0.0420
2025-12-15,10Y,0.0385
```

### vix_futures_curve.csv

```csv
date,vx_m1,vx_m2,vx_m3,vx_m4,vx_m1_expiry,vx_m2_expiry
2025-12-15,16.50,17.25,17.80,18.10,2026-01-22,2026-02-19
```

### calendar_events.csv

```csv
event_timestamp,event_type,ticker,event_label,timing,confirmed
2026-01-29T07:00:00-05:00,EARNINGS,VLO,Q4 2025 Earnings,BMO,true
2026-01-28T14:00:00-05:00,FOMC,,FOMC Decision,14:00,true
```

### options_eod.csv (template)

```csv
date,underlying,expiration,strike,right,bid,ask,implied_vol,delta,open_interest
2025-12-15,VLO,2026-02-20,180.0,C,6.80,7.20,0.35,0.55,1500
```

## Next Steps After Data Ingestion

1. **Verify data files** in `data/raw/`
2. **Enhance options_eod.csv** with real historical data (if backtesting)
3. **Run the backtester**: `python -m src.engine.run_backtest`
4. **For live trading**: Configure TastyTrade credentials and use the execution module

## Support

If you encounter issues with specific data sources, check the README files created alongside each dataset (e.g., `VIX_FUTURES_README.txt`, `OPTIONS_EOD_README.txt`).
