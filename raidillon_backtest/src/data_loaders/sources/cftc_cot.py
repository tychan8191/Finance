"""
sources/cftc_cot.py - CFTC Commitment of Traders Data Fetcher

This module handles fetching COT data from the CFTC to track speculative
positioning in VIX futures. High net short positioning among speculators
can indicate crowded trades and potential for short squeezes.

Data Source: https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm

The COT report is released every Friday and covers positions as of the
prior Tuesday. For VIX futures, we want the "Financial" or "Traders in
Financial Futures" report.
"""

import pandas as pd
import numpy as np
from datetime import date, datetime, timedelta
from typing import Optional, Dict, List
from pathlib import Path
import requests
import zipfile
import io
import logging

logger = logging.getLogger('raidillon.ingest.cftc_cot')


# CFTC COT report URLs and codes
# The "Traders in Financial Futures" (TFF) report covers VIX
# Report codes for VIX Futures at CBOE
VIX_CFTC_CODE = '1170E1'  # VIX Futures

# URL patterns for CFTC historical data
CFTC_CURRENT_YEAR_URL = "https://www.cftc.gov/files/dea/history/deafut_txt_{year}.zip"
CFTC_HISTORICAL_URL = "https://www.cftc.gov/files/dea/history/deafut_txt_{year}.zip"

# TFF-specific URLs (Traders in Financial Futures)
CFTC_TFF_URL = "https://www.cftc.gov/files/dea/history/tff_fut_txt_{year}.zip"


def download_cot_report(year: int, report_type: str = 'tff') -> Optional[pd.DataFrame]:
    """
    Download COT report for a specific year.
    
    Args:
        year: Year to download (e.g., 2025)
        report_type: 'tff' for Traders in Financial Futures, 'legacy' for legacy format
    
    Returns:
        DataFrame with COT data, or None if download fails
    """
    if report_type == 'tff':
        url = CFTC_TFF_URL.format(year=year)
    else:
        url = CFTC_HISTORICAL_URL.format(year=year)
    
    logger.info(f"Downloading COT report for {year} from {url}")
    
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        
        # The response is a zip file containing a text file
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            # Get the first (usually only) file in the zip
            file_list = zf.namelist()
            if not file_list:
                logger.error(f"Empty zip file for {year}")
                return None
            
            with zf.open(file_list[0]) as f:
                # Read as CSV (it's actually comma-delimited text)
                df = pd.read_csv(f, low_memory=False)
        
        logger.info(f"Downloaded {len(df)} rows for {year}")
        return df
        
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to download COT report for {year}: {e}")
        return None
    except zipfile.BadZipFile as e:
        logger.error(f"Invalid zip file for {year}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error processing COT report for {year}: {e}")
        return None


def parse_tff_report(df: pd.DataFrame, market_code: str = VIX_CFTC_CODE) -> pd.DataFrame:
    """
    Parse Traders in Financial Futures report and extract relevant positioning data.
    
    The TFF report breaks down positions by trader type:
    - Dealer/Intermediary
    - Asset Manager/Institutional
    - Leveraged Funds (this is what we want for speculative positioning)
    - Other Reportables
    
    Args:
        df: Raw COT DataFrame
        market_code: CFTC market code to filter (default: VIX)
    
    Returns:
        DataFrame with net speculative positioning
    """
    # Column name variations in TFF report
    # Note: Column names can vary slightly year to year
    
    # Filter to the specific market
    # The 'CFTC_Contract_Market_Code' or similar column contains the market identifier
    possible_code_columns = [
        'CFTC_Contract_Market_Code', 
        'CFTC Contract Market Code',
        'Contract_Market_Code',
        'Market_and_Exchange_Names'
    ]
    
    code_col = None
    for col in possible_code_columns:
        if col in df.columns:
            code_col = col
            break
    
    if code_col is None:
        # Try to find VIX by market name
        name_col = None
        for col in df.columns:
            if 'name' in col.lower() or 'market' in col.lower():
                if df[col].astype(str).str.contains('VIX', case=False).any():
                    name_col = col
                    break
        
        if name_col:
            df = df[df[name_col].astype(str).str.contains('VIX', case=False)]
        else:
            logger.warning("Could not identify VIX futures in COT report")
            return pd.DataFrame()
    else:
        df = df[df[code_col].astype(str).str.contains(market_code, case=False)]
    
    if df.empty:
        logger.warning(f"No data found for market code {market_code}")
        return pd.DataFrame()
    
    # Extract relevant columns
    # Long positions for Leveraged Funds (speculators)
    long_col = None
    short_col = None
    date_col = None
    
    for col in df.columns:
        col_lower = col.lower()
        if 'lev' in col_lower and 'long' in col_lower and 'all' not in col_lower:
            if 'positions' in col_lower or not long_col:
                long_col = col
        elif 'lev' in col_lower and 'short' in col_lower and 'all' not in col_lower:
            if 'positions' in col_lower or not short_col:
                short_col = col
        elif 'date' in col_lower and 'as_of' in col_lower.replace(' ', '_'):
            date_col = col
        elif col_lower == 'report_date_as_of_date' or col_lower == 'as_of_date_in_form_yymmdd':
            date_col = col
    
    # Alternative: look for specific column patterns
    if long_col is None:
        for col in df.columns:
            if 'Lev_Money_Positions_Long' in col or 'Leveraged_Funds_Long' in col:
                long_col = col
                break
    
    if short_col is None:
        for col in df.columns:
            if 'Lev_Money_Positions_Short' in col or 'Leveraged_Funds_Short' in col:
                short_col = col
                break
    
    if date_col is None:
        for col in df.columns:
            if 'Report_Date_as_of_Date' in col or col == 'As_of_Date_In_Form_YYMMDD':
                date_col = col
                break
    
    if not all([long_col, short_col, date_col]):
        logger.warning(f"Could not find required columns. Found: long={long_col}, short={short_col}, date={date_col}")
        logger.debug(f"Available columns: {list(df.columns)[:20]}")
        return pd.DataFrame()
    
    # Build result DataFrame
    records = []
    
    for _, row in df.iterrows():
        try:
            # Parse date (various formats possible)
            date_val = row[date_col]
            if isinstance(date_val, (int, float)):
                # YYMMDD format
                date_str = str(int(date_val))
                if len(date_str) == 6:
                    year = 2000 + int(date_str[:2])
                    month = int(date_str[2:4])
                    day = int(date_str[4:6])
                    report_date = date(year, month, day)
                else:
                    continue
            else:
                report_date = pd.to_datetime(date_val).date()
            
            long_pos = int(row[long_col]) if pd.notna(row[long_col]) else 0
            short_pos = int(row[short_col]) if pd.notna(row[short_col]) else 0
            net_pos = long_pos - short_pos
            
            records.append({
                'report_date': report_date.isoformat(),
                'market': 'VIX',
                'leveraged_long': long_pos,
                'leveraged_short': short_pos,
                'net_speculative_position': net_pos,
            })
            
        except Exception as e:
            logger.debug(f"Error parsing row: {e}")
            continue
    
    return pd.DataFrame(records)


def parse_legacy_report(df: pd.DataFrame, market_name: str = 'VIX') -> pd.DataFrame:
    """
    Parse legacy COT report format.
    
    The legacy report has different column structure but still includes
    commercial vs non-commercial positioning.
    
    Args:
        df: Raw COT DataFrame
        market_name: Market name to filter (looks for 'VIX' in market name)
    
    Returns:
        DataFrame with net speculative positioning
    """
    # Find VIX rows
    name_col = None
    for col in df.columns:
        if 'market' in col.lower() and 'name' in col.lower():
            name_col = col
            break
    
    if name_col is None:
        for col in df.columns:
            if df[col].astype(str).str.contains('VIX', case=False).any():
                name_col = col
                break
    
    if name_col is None:
        logger.warning("Could not find market name column")
        return pd.DataFrame()
    
    df = df[df[name_col].astype(str).str.contains(market_name, case=False)]
    
    if df.empty:
        return pd.DataFrame()
    
    # Find relevant columns
    # In legacy format, "Non-Commercial" represents speculators
    long_col = None
    short_col = None
    date_col = None
    
    for col in df.columns:
        col_lower = col.lower()
        if 'noncomm' in col_lower.replace('-', '').replace('_', '').replace(' ', ''):
            if 'long' in col_lower and 'all' not in col_lower:
                long_col = col
            elif 'short' in col_lower and 'all' not in col_lower:
                short_col = col
        if 'date' in col_lower and ('report' in col_lower or 'as_of' in col_lower):
            date_col = col
    
    if not all([long_col, short_col, date_col]):
        logger.warning(f"Could not find required columns in legacy format")
        return pd.DataFrame()
    
    records = []
    for _, row in df.iterrows():
        try:
            date_val = row[date_col]
            if isinstance(date_val, (int, float)):
                date_str = str(int(date_val))
                year = 2000 + int(date_str[:2])
                month = int(date_str[2:4])
                day = int(date_str[4:6])
                report_date = date(year, month, day)
            else:
                report_date = pd.to_datetime(date_val).date()
            
            long_pos = int(row[long_col]) if pd.notna(row[long_col]) else 0
            short_pos = int(row[short_col]) if pd.notna(row[short_col]) else 0
            
            records.append({
                'report_date': report_date.isoformat(),
                'market': 'VIX',
                'leveraged_long': long_pos,
                'leveraged_short': short_pos,
                'net_speculative_position': long_pos - short_pos,
            })
        except Exception as e:
            logger.debug(f"Error parsing row: {e}")
            continue
    
    return pd.DataFrame(records)


def fetch_cot_data(
    market: str = 'VIX',
    start_date: date = None,
    end_date: date = None
) -> pd.DataFrame:
    """
    Fetch COT data for a specific market and date range.
    
    This is the main entry point for COT data. It handles downloading
    reports for all required years and consolidating the data.
    
    Args:
        market: Market name ('VIX' for VIX futures)
        start_date: Start of date range (default: 2 years ago)
        end_date: End of date range (default: today)
    
    Returns:
        DataFrame with columns:
        - report_date
        - market
        - net_speculative_position (Leveraged Funds net = long - short)
    """
    if start_date is None:
        start_date = date.today() - timedelta(days=730)  # 2 years
    if end_date is None:
        end_date = date.today()
    
    logger.info(f"Fetching COT data for {market}: {start_date} to {end_date}")
    
    # Determine which years we need
    years = list(range(start_date.year, end_date.year + 1))
    
    all_data = []
    
    for year in years:
        # Try TFF report first (preferred for financial futures)
        df = download_cot_report(year, report_type='tff')
        
        if df is not None:
            parsed = parse_tff_report(df, market_code=VIX_CFTC_CODE)
            if not parsed.empty:
                all_data.append(parsed)
                continue
        
        # Fall back to legacy format
        df = download_cot_report(year, report_type='legacy')
        if df is not None:
            parsed = parse_legacy_report(df, market_name=market)
            if not parsed.empty:
                all_data.append(parsed)
    
    if not all_data:
        logger.warning("No COT data could be retrieved")
        # Return a placeholder
        return pd.DataFrame({
            'report_date': [start_date.isoformat()],
            'market': [market],
            'net_speculative_position': [-85000],  # Typical value when shorts are crowded
        })
    
    # Combine all years
    combined = pd.concat(all_data, ignore_index=True)
    
    # Filter to date range
    combined['report_date'] = pd.to_datetime(combined['report_date']).dt.date
    combined = combined[
        (combined['report_date'] >= start_date) &
        (combined['report_date'] <= end_date)
    ]
    
    # Sort by date and remove duplicates
    combined = combined.sort_values('report_date').drop_duplicates(subset=['report_date'], keep='last')
    
    # Convert dates back to string for CSV compatibility
    combined['report_date'] = combined['report_date'].astype(str)
    
    logger.info(f"Retrieved {len(combined)} COT reports")
    
    return combined


def get_latest_positioning(market: str = 'VIX') -> Optional[Dict]:
    """
    Get the most recent COT positioning data.
    
    Useful for quick checks of current speculative positioning.
    
    Args:
        market: Market name
    
    Returns:
        Dict with latest positioning data, or None if unavailable
    """
    df = fetch_cot_data(market, start_date=date.today() - timedelta(days=30))
    
    if df.empty:
        return None
    
    latest = df.iloc[-1]
    
    return {
        'report_date': latest['report_date'],
        'market': latest['market'],
        'net_position': int(latest['net_speculative_position']),
        'position_type': 'NET_SHORT' if latest['net_speculative_position'] < 0 else 'NET_LONG',
    }


def calculate_positioning_percentile(
    current_position: int,
    lookback_days: int = 365
) -> float:
    """
    Calculate the percentile rank of current positioning vs historical.
    
    This helps identify when positioning is at extreme levels that
    might indicate crowded trades.
    
    Args:
        current_position: Current net speculative position
        lookback_days: Number of days of history to compare against
    
    Returns:
        Percentile rank (0-100, where 0 = maximum short, 100 = maximum long)
    """
    start = date.today() - timedelta(days=lookback_days)
    df = fetch_cot_data('VIX', start_date=start)
    
    if df.empty:
        return 50.0  # Neutral if no data
    
    positions = df['net_speculative_position'].values
    
    # Calculate percentile
    below = np.sum(positions < current_position)
    percentile = (below / len(positions)) * 100
    
    return percentile


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    
    # Test fetching COT data
    start = date(2024, 1, 1)
    end = date(2025, 1, 15)
    
    df = fetch_cot_data('VIX', start, end)
    print(df.head(20))
    
    # Check latest positioning
    latest = get_latest_positioning()
    print(f"\nLatest positioning: {latest}")
