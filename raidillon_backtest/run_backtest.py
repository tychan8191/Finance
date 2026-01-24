#!/usr/bin/env python3
"""
run_backtest.py - Main Entry Point for Raidillon Backtest Framework

This script provides a simple way to run backtests from the command line.
It handles all the setup and configuration, allowing you to focus on
analyzing results.

Quick Start:
------------
    # Run with default settings (base variant, Jan 21 - Feb 28, 2026)
    python run_backtest.py
    
    # Run conservative variant
    python run_backtest.py --variant conservative
    
    # Custom date range
    python run_backtest.py --start 2026-01-15 --end 2026-03-15
    
    # See all options
    python run_backtest.py --help

Prerequisites:
-------------
Before running, ensure you have:
1. Installed dependencies: pip install -r requirements.txt
2. Run data ingestion: python run_ingest.py (populates data/raw/)

Output:
-------
Results are saved to the outputs/ directory:
- daily_metrics_YYYYMMDD_HHMMSS.csv: NAV and metrics by day
- trade_log_YYYYMMDD_HHMMSS.csv: All trades with P&L
- signals_YYYYMMDD_HHMMSS.csv: All entry/exit signals
- report_YYYYMMDD_HHMMSS.txt: Human-readable summary

Architecture Notes:
------------------
This script is intentionally thin - it just sets up the environment and
delegates to the BacktestEngine. The real work happens in:
- src/engine/backtest.py: Main orchestration
- src/strategies/base.py: Strategy framework
- src/engine/portfolio.py: Position and P&L tracking
- src/data_loaders/: Data loading and validation
"""

import os
import sys
from pathlib import Path
from datetime import datetime
import argparse
import logging

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Configure logging before imports
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('raidillon')


def check_data_files():
    """Check if required data files exist and provide guidance if not."""
    data_dir = PROJECT_ROOT / 'data' / 'raw'
    
    required_files = ['equities_ohlcv.csv']
    optional_files = [
        'vix_index.csv',
        'rates_curve.csv', 
        'calendar_events.csv',
        'options_eod.csv',
        'crack_spreads.csv',
        'cftc_cot.csv',
        'vix_futures_curve.csv'
    ]
    
    missing_required = []
    missing_optional = []
    
    for f in required_files:
        if not (data_dir / f).exists():
            missing_required.append(f)
    
    for f in optional_files:
        if not (data_dir / f).exists():
            missing_optional.append(f)
    
    if missing_required:
        print("\n" + "=" * 60)
        print("ERROR: Missing required data files!")
        print("=" * 60)
        print(f"\nThe following required files are missing from {data_dir}:")
        for f in missing_required:
            print(f"  - {f}")
        print("\nTo generate these files, run:")
        print("  python run_ingest.py")
        print("\nThis will fetch data from free sources (yfinance, FRED, etc.)")
        print("=" * 60 + "\n")
        return False
    
    if missing_optional:
        print(f"\nNote: Some optional data files are missing: {', '.join(missing_optional)}")
        print("The backtest will run with reduced functionality.")
        print("Run 'python run_ingest.py' to fetch all available data.\n")
    
    return True


def print_banner():
    """Print welcome banner."""
    banner = """
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║     ██████╗  █████╗ ██╗██████╗ ██╗██╗     ██╗      ██████╗ ███╗   ██╗ ║
    ║     ██╔══██╗██╔══██╗██║██╔══██╗██║██║     ██║     ██╔═══██╗████╗  ██║ ║
    ║     ██████╔╝███████║██║██║  ██║██║██║     ██║     ██║   ██║██╔██╗ ██║ ║
    ║     ██╔══██╗██╔══██║██║██║  ██║██║██║     ██║     ██║   ██║██║╚██╗██║ ║
    ║     ██║  ██║██║  ██║██║██████╔╝██║███████╗███████╗╚██████╔╝██║ ╚████║ ║
    ║     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═════╝ ╚═╝╚══════╝╚══════╝ ╚═════╝ ╚═╝  ╚═══╝ ║
    ║                                                               ║
    ║              BACKTEST FRAMEWORK v1.0                          ║
    ║              Event-Driven Options Strategies                  ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
    """
    # Simplified banner for terminal width issues
    print("\n" + "=" * 60)
    print("RAIDILLON BACKTEST FRAMEWORK v1.0")
    print("Event-Driven Options Strategies")
    print("=" * 60 + "\n")


def run_backtest(
    variant: str = 'base',
    start_date: str = '2026-01-21',
    end_date: str = '2026-02-28',
    config_path: str = 'config/strategies.yaml',
    output_dir: str = None,
    verbose: bool = True,
    export: bool = True
):
    """
    Run a backtest with the specified parameters.
    
    This is the main function that coordinates everything. It can be called
    directly from Python or via the command line.
    
    Args:
        variant: Portfolio variant - 'conservative', 'base', or 'aggressive'
        start_date: Start date for backtest (YYYY-MM-DD)
        end_date: End date for backtest (YYYY-MM-DD)
        config_path: Path to strategies.yaml
        output_dir: Directory for output files (default: outputs/)
        verbose: Whether to print detailed progress
        export: Whether to export CSV results
        
    Returns:
        Dict containing backtest results
    """
    # Import here to allow for path setup
    from src.engine.backtest import BacktestEngine
    
    if verbose:
        print_banner()
        print(f"Configuration:")
        print(f"  Variant:    {variant}")
        print(f"  Period:     {start_date} to {end_date}")
        print(f"  Config:     {config_path}")
        print()
    
    # Create and run engine
    try:
        engine = BacktestEngine.from_yaml(
            yaml_path=config_path,
            variant=variant,
            start_date=start_date,
            end_date=end_date
        )
    except FileNotFoundError as e:
        print(f"\nError: Could not load configuration: {e}")
        print("Make sure config/strategies.yaml exists.")
        return None
    except Exception as e:
        print(f"\nError initializing backtest engine: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    # Run backtest
    results = engine.run()
    
    # Print report
    if verbose:
        print("\n" + engine.generate_report())
    
    # Export results
    if export:
        engine.export_results(output_dir)
    
    return results


def run_comparison():
    """
    Run all three variants and compare results.
    
    This is useful for understanding the risk/return tradeoff across variants.
    """
    print("\n" + "=" * 60)
    print("RUNNING VARIANT COMPARISON")
    print("=" * 60)
    
    variants = ['conservative', 'base', 'aggressive']
    results = {}
    
    for variant in variants:
        print(f"\n--- Running {variant.upper()} variant ---")
        results[variant] = run_backtest(variant=variant, verbose=False, export=False)
    
    # Print comparison
    print("\n" + "=" * 60)
    print("VARIANT COMPARISON RESULTS")
    print("=" * 60)
    print(f"{'Metric':<25} {'Conservative':>15} {'Base':>15} {'Aggressive':>15}")
    print("-" * 70)
    
    metrics = [
        ('Final NAV', 'final_nav', '${:,.2f}'),
        ('Total Return', 'total_return_pct', '{:+.2f}%'),
        ('Max Drawdown', 'max_drawdown_pct', '{:.2f}%'),
        ('Sharpe Ratio', 'sharpe_ratio', '{:.2f}'),
        ('Win Rate', 'win_rate_pct', '{:.1f}%'),
        ('Total Trades', 'total_trades', '{}'),
    ]
    
    for label, key, fmt in metrics:
        values = []
        for v in variants:
            val = results[v].get(key, 0) if results[v] else 0
            values.append(fmt.format(val))
        print(f"{label:<25} {values[0]:>15} {values[1]:>15} {values[2]:>15}")
    
    print("=" * 60 + "\n")
    
    return results


def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description='Run Raidillon Backtest Framework',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_backtest.py                    # Run with defaults (base variant)
  python run_backtest.py -v conservative    # Run conservative variant
  python run_backtest.py -v aggressive      # Run aggressive variant
  python run_backtest.py --compare          # Compare all variants
  python run_backtest.py --start 2026-01-15 --end 2026-03-01  # Custom dates
        """
    )
    
    parser.add_argument(
        '-v', '--variant',
        default='base',
        choices=['conservative', 'base', 'aggressive'],
        help='Portfolio variant to run (default: base)'
    )
    
    parser.add_argument(
        '--start',
        default='2026-01-21',
        help='Start date in YYYY-MM-DD format (default: 2026-01-21)'
    )
    
    parser.add_argument(
        '--end',
        default='2026-02-28',
        help='End date in YYYY-MM-DD format (default: 2026-02-28)'
    )
    
    parser.add_argument(
        '--config',
        default='config/strategies.yaml',
        help='Path to strategies.yaml (default: config/strategies.yaml)'
    )
    
    parser.add_argument(
        '--output-dir',
        help='Output directory for results (default: outputs/)'
    )
    
    parser.add_argument(
        '--compare',
        action='store_true',
        help='Run all variants and compare results'
    )
    
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Reduce output verbosity'
    )
    
    parser.add_argument(
        '--no-export',
        action='store_true',
        help='Skip exporting CSV results'
    )
    
    args = parser.parse_args()
    
    # Set logging level
    if args.quiet:
        logging.getLogger('raidillon').setLevel(logging.WARNING)
    
    # Check data files exist
    if not check_data_files():
        sys.exit(1)
    
    # Run backtest(s)
    if args.compare:
        results = run_comparison()
    else:
        results = run_backtest(
            variant=args.variant,
            start_date=args.start,
            end_date=args.end,
            config_path=args.config,
            output_dir=args.output_dir,
            verbose=not args.quiet,
            export=not args.no_export
        )
    
    if results is None:
        sys.exit(1)
    
    return results


if __name__ == '__main__':
    main()
