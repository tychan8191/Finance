"""
sources/cboe_vix.py - CBOE VIX Futures Data Fetcher

This module handles fetching VIX futures term structure data from CBOE CFE.
VIX options are priced off futures, not spot VIX, making this data critical
for accurate VIX option strategy backtesting.

Data Source: https://www.cboe.com/us/futures/market_statistics/historical_data/
"""

import pandas as pd
import numpy as np
from datetime import date, datetime, timedelta
from typing import Optional, Dict, List, Tuple
from pathlib import Path
import requests
import io
import logging
import re

logger = logging.getLogger('raidillon.ingest.cboe_vix')


# VIX futures contract months follow the calendar
# F=Jan, G=Feb, H=Mar, J=Apr, K=May, M=Jun, N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec
MONTH_CODES = {
    1: 'F', 2: 'G', 3: 'H', 4: 'J', 5: 'K', 6: 'M',
    7: 'N', 8: 'Q', 9: 'U', 10: 'V', 11: 'X', 12: 'Z'
}

CODE_TO_MONTH = {v: k for k, v in MONTH_CODES.items()}


def get_vix_futures_expiration(year: int, month: int) -> date:
    """
    Calculate VIX futures expiration date for a given month.
    
    VIX futures expire on the Wednesday that is 30 days before the third
    Friday of the calendar month following the expiration month.
    
    In practice, this is usually the Wednesday before the third Friday
    of the expiration month, but not always.
    
    Args:
        year: Expiration year
        month: Expiration month (1-12)
    
    Returns:
        Expiration date
    """
    # Find third Friday of the FOLLOWING month
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1
    
    # Start with first day of next month
    first_day = date(next_year, next_month, 1)
    
    # Find the first Friday
    days_until_friday = (4 - first_day.weekday()) % 7
    first_friday = first_day + timedelta(days=days_until_friday)
    
    # Third Friday
    third_friday = first_friday + timedelta(weeks=2)
    
    # VIX settlement is 30 days before this, which lands on a Wednesday
    settlement = third_friday - timedelta(days=30)
    
    # Adjust to Wednesday if needed (should already be Wednesday)
    while settlement.weekday() != 2:  # 2 = Wednesday
        settlement -= timedelta(days=1)
    
    return settlement


def generate_vix_futures_symbols(start_date: date, end_date: date) -> List[str]:
    """
    Generate list of VIX futures symbols needed to cover a date range.
    
    Args:
        start_date: Start of date range
        end_date: End of date range
    
    Returns:
        List of symbols like ['VXF26', 'VXG26', ...]
    """
    symbols = []
    current = start_date
    
    while current <= end_date + timedelta(days=90):  # Extra buffer for front months
        year_2digit = current.year % 100
        month_code = MONTH_CODES[current.month]
        symbol = f"VX{month_code}{year_2digit:02d}"
        
        if symbol not in symbols:
            symbols.append(symbol)
        
        # Move to next month
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    
    return symbols


def fetch_single_vix_contract(symbol: str) -> Optional[pd.DataFrame]:
    """
    Fetch historical data for a single VIX futures contract from CBOE.
    
    Args:
        symbol: Contract symbol (e.g., 'VXF26')
    
    Returns:
        DataFrame with OHLC + Settle data, or None if not found
    """
    # Parse symbol
    match = re.match(r'VX([A-Z])(\d{2})', symbol)
    if not match:
        logger.warning(f"Invalid VIX futures symbol: {symbol}")
        return None
    
    month_code = match.group(1)
    year_2digit = int(match.group(2))
    
    # CBOE URL pattern for VIX futures
    # Note: This URL structure may change - check CBOE website if it stops working
    base_url = "https://markets.cboe.com/us/futures/market_statistics/historical_data/products/csv/VX/"
    
    # Try downloading
    try:
        # CBOE organizes by year
        year_4digit = 2000 + year_2digit
        url = f"{base_url}{year_4digit}/VX_{year_4digit}{CODE_TO_MONTH[month_code]:02d}_futures_data.csv"
        
        logger.debug(f"Fetching {symbol} from {url}")
        
        response = requests.get(url, timeout=30)
        
        if response.status_code == 404:
            logger.debug(f"Contract {symbol} not found (likely not yet traded or expired)")
            return None
        
        response.raise_for_status()
        
        df = pd.read_csv(io.StringIO(response.text))
        df['Symbol'] = symbol
        
        return df
        
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch {symbol}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error parsing {symbol} data: {e}")
        return None


def build_term_structure(contracts: Dict[str, pd.DataFrame], as_of_date: date) -> Dict:
    """
    Build the VIX futures term structure for a specific date.
    
    Args:
        contracts: Dict mapping symbol to DataFrame with contract data
        as_of_date: Date for which to build the term structure
    
    Returns:
        Dict with M1, M2, M3, M4 prices and expiration dates
    """
    # Get all contracts with data for this date, sorted by expiration
    valid_contracts = []
    
    for symbol, df in contracts.items():
        # Parse expiration from symbol
        match = re.match(r'VX([A-Z])(\d{2})', symbol)
        if not match:
            continue
        
        month_code = match.group(1)
        year_2digit = int(match.group(2))
        month = CODE_TO_MONTH[month_code]
        year = 2000 + year_2digit
        
        expiration = get_vix_futures_expiration(year, month)
        
        # Skip if already expired
        if expiration <= as_of_date:
            continue
        
        # Get settle price for as_of_date
        df['Trade Date'] = pd.to_datetime(df['Trade Date']).dt.date
        row = df[df['Trade Date'] == as_of_date]
        
        if len(row) == 0:
            continue
        
        settle = row.iloc[0]['Settle']
        if pd.isna(settle) or settle == 0:
            continue
        
        valid_contracts.append({
            'symbol': symbol,
            'expiration': expiration,
            'settle': settle,
            'days_to_exp': (expiration - as_of_date).days
        })
    
    # Sort by expiration
    valid_contracts.sort(key=lambda x: x['expiration'])
    
    # Build term structure (M1 through M4)
    result = {
        'date': as_of_date.isoformat(),
        'vx_m1': None,
        'vx_m2': None,
        'vx_m3': None,
        'vx_m4': None,
        'vx_m1_expiry': None,
        'vx_m2_expiry': None,
    }
    
    for i, contract in enumerate(valid_contracts[:4]):
        month_key = f'vx_m{i+1}'
        result[month_key] = contract['settle']
        
        if i < 2:
            result[f'{month_key}_expiry'] = contract['expiration'].isoformat()
    
    return result


def fetch_vix_futures_term_structure(
    start_date: date,
    end_date: date,
    cache_dir: Optional[Path] = None
) -> pd.DataFrame:
    """
    Fetch complete VIX futures term structure for a date range.
    
    This is the main entry point for VIX futures data. It downloads
    all required contracts and builds the daily term structure.
    
    Args:
        start_date: Start of date range
        end_date: End of date range
        cache_dir: Optional directory to cache downloaded contract data
    
    Returns:
        DataFrame with columns:
        - date
        - vx_m1, vx_m2, vx_m3, vx_m4 (settle prices)
        - vx_m1_expiry, vx_m2_expiry (expiration dates)
    """
    logger.info(f"Fetching VIX futures term structure: {start_date} to {end_date}")
    
    # Generate required symbols
    symbols = generate_vix_futures_symbols(start_date, end_date)
    logger.info(f"Need {len(symbols)} contracts: {symbols[:5]}...{symbols[-2:]}")
    
    # Fetch all contracts
    contracts = {}
    for symbol in symbols:
        df = fetch_single_vix_contract(symbol)
        if df is not None:
            contracts[symbol] = df
            logger.debug(f"Loaded {symbol}: {len(df)} rows")
    
    if not contracts:
        logger.error("No VIX futures contracts could be loaded")
        return pd.DataFrame()
    
    logger.info(f"Loaded {len(contracts)} contracts")
    
    # Build daily term structure
    records = []
    current = start_date
    
    while current <= end_date:
        # Skip weekends
        if current.weekday() < 5:  # Monday=0, Friday=4
            ts = build_term_structure(contracts, current)
            if ts['vx_m1'] is not None:  # Only add if we have data
                records.append(ts)
        
        current += timedelta(days=1)
    
    df = pd.DataFrame(records)
    logger.info(f"Built term structure with {len(df)} trading days")
    
    return df


def fetch_vix_settlement_values(
    start_date: date,
    end_date: date
) -> pd.DataFrame:
    """
    Extract VIX futures settlement values at expiration.
    
    This is needed for calculating P&L on VIX option positions,
    which settle to the Special Opening Quotation (SOQ).
    
    Args:
        start_date: Start of date range  
        end_date: End of date range
    
    Returns:
        DataFrame with columns: expiration_date, settlement_value, settlement_type
    """
    logger.info("Extracting VIX settlement values...")
    
    symbols = generate_vix_futures_symbols(start_date, end_date)
    records = []
    
    for symbol in symbols:
        df = fetch_single_vix_contract(symbol)
        if df is None:
            continue
        
        # Parse expiration from symbol
        match = re.match(r'VX([A-Z])(\d{2})', symbol)
        if not match:
            continue
        
        month_code = match.group(1)
        year_2digit = int(match.group(2))
        month = CODE_TO_MONTH[month_code]
        year = 2000 + year_2digit
        
        expiration = get_vix_futures_expiration(year, month)
        
        # Settlement is the last row where Settle has a value and OHLC are 0
        df['Trade Date'] = pd.to_datetime(df['Trade Date']).dt.date
        
        # Look for settlement row (Open=High=Low=Close=0, but Settle has value)
        settlement_rows = df[
            (df['Open'] == 0) & 
            (df['High'] == 0) & 
            (df['Low'] == 0) & 
            (df['Close'] == 0) &
            (df['Settle'] > 0)
        ]
        
        if len(settlement_rows) > 0:
            settlement_val = settlement_rows.iloc[-1]['Settle']
            records.append({
                'expiration_date': expiration.isoformat(),
                'settlement_value': settlement_val,
                'settlement_type': 'SOQ',  # Special Opening Quotation
            })
    
    df = pd.DataFrame(records)
    df = df.sort_values('expiration_date')
    
    return df


# Alternative: Use vix-utils package if available
def fetch_vix_term_structure_via_vix_utils(
    start_date: date,
    end_date: date
) -> pd.DataFrame:
    """
    Alternative method using the vix-utils package.
    
    Install with: pip install vix-utils
    
    This package automates downloading and processing CBOE VIX data.
    """
    try:
        import vix_utils as vu
        
        # Load term structure using async method
        import asyncio
        
        async def load():
            return await vu.async_load_vix_term_structure()
        
        df = asyncio.run(load())
        
        # Filter to date range
        df = df[(df.index >= start_date) & (df.index <= end_date)]
        
        # Transform to our expected format
        result = pd.DataFrame({
            'date': df.index.date,
            'vx_m1': df['VX1'].values,
            'vx_m2': df['VX2'].values,
            'vx_m3': df['VX3'].values,
            'vx_m4': df['VX4'].values,
            'vx_m1_expiry': None,  # Would need additional processing
            'vx_m2_expiry': None,
        })
        
        return result
        
    except ImportError:
        logger.warning("vix-utils not installed, falling back to direct CBOE fetch")
        raise ImportError("vix-utils package required: pip install vix-utils")


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    
    # Test fetching term structure
    start = date(2025, 1, 1)
    end = date(2025, 1, 31)
    
    df = fetch_vix_futures_term_structure(start, end)
    print(df.head(20))
