"""
data_loaders/__init__.py - Data Loading and Ingestion Package

This package provides all data loading functionality for the Raidillon
backtest framework. It includes:

1. Data Loaders (options.py):
   - OptionsDataLoader: Load and validate options EOD data
   - EquitiesDataLoader: Load and validate equity OHLCV data
   - CalendarEventsLoader: Load and validate calendar events

2. Data Ingestion (ingest.py):
   - DataIngestor: Fetch data from multiple sources (yfinance, FRED, CBOE, etc.)

3. Source Connectors (sources/):
   - cboe_vix: VIX futures term structure
   - cftc_cot: CFTC Commitment of Traders data

Quick Start:
------------
    # Option 1: Fetch all data automatically
    from src.data_loaders import DataIngestor
    
    ingestor = DataIngestor()
    ingestor.fetch_all()  # Populates data/raw/ with all required CSVs
    
    # Option 2: Load existing CSV files
    from src.data_loaders import OptionsDataLoader, EquitiesDataLoader
    
    options_loader = OptionsDataLoader('data/raw/options_eod.csv')
    options_df = options_loader.load()
    
    equities_loader = EquitiesDataLoader('data/raw/equities_ohlcv.csv')
    equities_df = equities_loader.load()

CLI Usage:
----------
    # Fetch all data from command line
    python -m src.data_loaders.ingest --all
    
    # Fetch specific datasets
    python -m src.data_loaders.ingest --equities --vix --rates
"""

# Import loaders from options.py
from .options import (
    OptionsDataLoader,
    EquitiesDataLoader,
    CalendarEventsLoader,
)

# Import ingestion orchestrator
from .ingest import DataIngestor

# Import source connectors
from . import sources

__all__ = [
    # Data Loaders
    'OptionsDataLoader',
    'EquitiesDataLoader', 
    'CalendarEventsLoader',
    
    # Data Ingestion
    'DataIngestor',
    
    # Source Connectors
    'sources',
]

# Version info
__version__ = '1.0.0'
