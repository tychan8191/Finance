"""
sources/__init__.py - Data Source Connectors

This module provides connectors to various data sources for the Raidillon
backtest framework. Each source module handles fetching, parsing, and
transforming data from a specific provider.

Available Sources:
- cboe_vix: VIX futures term structure from CBOE CFE
- cftc_cot: Commitment of Traders data from CFTC
- tastytrade_client: TastyTrade API for options data and execution

Usage:
    from src.data_loaders.sources import cboe_vix, cftc_cot
    
    # Fetch VIX futures term structure
    vix_ts = cboe_vix.fetch_vix_futures_term_structure(start, end)
    
    # Fetch COT positioning data
    cot = cftc_cot.fetch_cot_data('VIX', start, end)
    
    # Use TastyTrade for live options
    from src.data_loaders.sources import tastytrade_client
    client = tastytrade_client.get_client()
    chain = client.get_option_chain('VLO')
"""

from .cboe_vix import (
    fetch_vix_futures_term_structure,
    fetch_vix_settlement_values,
    get_vix_futures_expiration,
)

from .cftc_cot import (
    fetch_cot_data,
    get_latest_positioning,
    calculate_positioning_percentile,
)

# TastyTrade is optional (requires authentication)
try:
    from .tastytrade_client import (
        TastyTradeClient,
        get_client,
        quick_quote,
        OptionQuote,
        AccountBalance,
        Position,
    )
    TASTYTRADE_AVAILABLE = True
except ImportError:
    TASTYTRADE_AVAILABLE = False

__all__ = [
    # CBOE VIX
    'fetch_vix_futures_term_structure',
    'fetch_vix_settlement_values',
    'get_vix_futures_expiration',
    
    # CFTC COT
    'fetch_cot_data',
    'get_latest_positioning',
    'calculate_positioning_percentile',
    
    # TastyTrade (if available)
    'TastyTradeClient',
    'get_client',
    'quick_quote',
    'OptionQuote',
    'AccountBalance',
    'Position',
    'TASTYTRADE_AVAILABLE',
]
