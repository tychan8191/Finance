#!/usr/bin/env python3
"""
run_ingest.py - Main Entry Point for Raidillon Backtest Data Ingestion

This script provides a simple way to populate the data directory with all
required historical data from free sources. It minimizes the number of CSV
files you need to manually upload.

After running this script, you will have:
- data/raw/equities_ohlcv.csv (from yfinance - FREE)
- data/raw/vix_index.csv (from FRED - FREE)
- data/raw/rates_curve.csv (from FRED - FREE)
- data/raw/calendar_events.csv (auto-generated from strategies.yaml - FREE)
- data/raw/crack_spreads.csv (from EIA via yfinance - FREE)
- data/raw/cftc_cot.csv (from CFTC - FREE)
- data/raw/vix_futures_curve.csv (from CBOE - FREE, may require manual steps)
- data/raw/options_eod.csv (TEMPLATE ONLY - requires ORATS or Polygon subscription)

The ONLY file you may need to manually provide or enhance is options_eod.csv
with historical options data if you need full backtesting capability. For live
trading, TastyTrade's API can provide real-time options data.

Usage:
------
    # From project root directory:
    python run_ingest.py
    
    # Or with custom date range:
    python run_ingest.py --start 2024-06-01 --end 2026-03-31
    
    # Fetch specific datasets only:
    python run_ingest.py --equities --vix --rates
    
    # Include live options from TastyTrade (requires env vars):
    export TASTYTRADE_USERNAME='your_username'
    export TASTYTRADE_PASSWORD='your_password'
    python run_ingest.py --all --options

Environment Variables:
----------------------
    TASTYTRADE_USERNAME - Your TastyTrade account username
    TASTYTRADE_PASSWORD - Your TastyTrade account password

Requirements:
-------------
    pip install -r requirements.txt
"""

import sys
import os
from pathlib import Path

# Ensure the project root is in the path
PROJECT_ROOT = Path(__file__).parent / 'raidillon_backtest'
sys.path.insert(0, str(PROJECT_ROOT))

def main():
    """Main entry point for data ingestion."""
    
    # Now we can import from the package
    from src.data_loaders.ingest import DataIngestor, main as ingest_main
    
    # If called with arguments, use the CLI
    if len(sys.argv) > 1:
        ingest_main()
        return
    
    # Default behavior: fetch all free data sources
    print("=" * 70)
    print("RAIDILLON BACKTEST FRAMEWORK - DATA INGESTION")
    print("=" * 70)
    print()
    print("This will fetch data from the following FREE sources:")
    print("  • yfinance    → Equity OHLCV for all strategy underlyings")
    print("  • FRED        → VIX index daily values")
    print("  • FRED        → Treasury rates curve (3M, 2Y, 5Y, 10Y, 30Y)")
    print("  • CBOE        → VIX futures term structure")
    print("  • CFTC        → Commitment of Traders positioning")
    print("  • EIA/Yahoo   → Crack spreads for refiner thesis")
    print("  • Config YAML → Calendar events auto-generated")
    print()
    print("Date range: 2024-10-01 to 2026-02-28 (your catalyst window)")
    print()
    print("-" * 70)
    
    # Initialize and run ingestion
    ingestor = DataIngestor(
        config_path=str(PROJECT_ROOT / 'config' / 'strategies.yaml'),
        start_date='2024-10-01',
        end_date='2026-02-28'
    )
    
    # Fetch all data
    results = ingestor.fetch_all(include_options=False)
    
    # Print summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    status = ingestor.get_status()
    
    print(f"\nData saved to: {status['data_directory']}")
    print(f"Date range: {status['start_date']} to {status['end_date']}")
    print(f"Tickers tracked: {len(status['tickers'])}")
    print()
    
    print("Dataset Status:")
    for name, fetched in status['fetch_status'].items():
        status_icon = "✓" if fetched else "✗"
        print(f"  {status_icon} {name}")
    
    print()
    print("-" * 70)
    print("NEXT STEPS:")
    print("-" * 70)
    print()
    print("1. CHECK generated files in data/raw/")
    print()
    print("2. For OPTIONS DATA, you have two choices:")
    print("   a) Use TastyTrade's backtester (free with funded account)")
    print("   b) Subscribe to ORATS ($99/mo) for full historical options")
    print()
    print("   The generated options_eod.csv is a TEMPLATE. You can:")
    print("   - Enhance it with real data from ORATS or Polygon")
    print("   - Use TastyTrade's live API for forward-looking analysis")
    print()
    print("3. RUN THE BACKTEST:")
    print("   python -m src.engine.run_backtest")
    print()
    print("4. For LIVE TRADING with TastyTrade:")
    print("   export TASTYTRADE_USERNAME='your_username'")
    print("   export TASTYTRADE_PASSWORD='your_password'")
    print("   python -m src.engine.live_trader")
    print()
    

if __name__ == '__main__':
    main()
