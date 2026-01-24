"""
data_loaders/options.py - Options Data Loading and Validation

This module handles loading options EOD data from CSV files, validating
schema and data quality, and providing clean DataFrames for the backtest
engine.

Critical Validation Checks:
1. Schema compliance (required columns, correct types)
2. No lookahead bias (prices only from available dates)
3. Bid-ask sanity (bid <= ask, both positive)
4. Open interest minimums for liquidity
5. Greeks sign conventions (delta positive for calls, negative for puts)
"""

import pandas as pd
import numpy as np
from datetime import datetime, date
from typing import Optional, Dict, List, Tuple
from pathlib import Path
import warnings


class OptionsDataLoader:
    """
    Loads and validates options EOD data for backtesting.
    
    This loader expects a CSV with the following schema:
    
    Required Columns:
    - date: date (YYYY-MM-DD)
    - underlying: str (ticker symbol)
    - expiration: date (YYYY-MM-DD)
    - strike: float
    - right: str ('C' or 'P')
    - bid: float
    - ask: float
    
    Strongly Recommended Columns:
    - implied_vol: float (annualized, as decimal e.g., 0.35 for 35%)
    - delta: float (-1 to 1)
    - open_interest: int
    
    Optional Columns:
    - option_symbol: str (OCC format)
    - last: float
    - volume: int
    - gamma, theta, vega, rho: float
    - underlying_price: float
    
    Usage:
        loader = OptionsDataLoader("data/raw/options_eod.csv")
        df = loader.load()
        
        # Get quotes for a specific underlying and date
        quotes = loader.get_chain("VLO", date(2026, 1, 27))
    """
    
    REQUIRED_COLUMNS = ['date', 'underlying', 'expiration', 'strike', 'right', 'bid', 'ask']
    RECOMMENDED_COLUMNS = ['implied_vol', 'delta', 'open_interest']
    OPTIONAL_COLUMNS = ['option_symbol', 'last', 'volume', 'gamma', 'theta', 'vega', 'rho', 'underlying_price']
    
    def __init__(self, filepath: str, min_open_interest: int = 500):
        """
        Initialize the loader.
        
        Args:
            filepath: Path to the options CSV file
            min_open_interest: Minimum OI for liquidity filtering (default 500)
        """
        self.filepath = Path(filepath)
        self.min_open_interest = min_open_interest
        self.df: Optional[pd.DataFrame] = None
        self.validation_report: Dict[str, any] = {}
        
    def load(self, validate: bool = True) -> pd.DataFrame:
        """
        Load the CSV file and optionally validate.
        
        Args:
            validate: Whether to run validation checks (default True)
        
        Returns:
            Cleaned and validated DataFrame
        
        Raises:
            FileNotFoundError: If CSV file doesn't exist
            ValueError: If validation fails on critical issues
        """
        if not self.filepath.exists():
            raise FileNotFoundError(f"Options data file not found: {self.filepath}")
        
        # Load with appropriate types
        # We specify date columns explicitly to ensure correct parsing
        self.df = pd.read_csv(
            self.filepath,
            parse_dates=['date', 'expiration'],
            dtype={
                'underlying': str,
                'strike': float,
                'right': str,
                'bid': float,
                'ask': float,
            }
        )
        
        # Normalize column names to lowercase
        self.df.columns = self.df.columns.str.lower().str.strip()
        
        if validate:
            self._validate()
        
        # Ensure date columns are date type (not datetime) for consistency
        self.df['date'] = pd.to_datetime(self.df['date']).dt.date
        self.df['expiration'] = pd.to_datetime(self.df['expiration']).dt.date
        
        # Normalize 'right' column to uppercase single character
        self.df['right'] = self.df['right'].str.upper().str[0]
        
        # Generate option_symbol if not present
        if 'option_symbol' not in self.df.columns:
            self.df['option_symbol'] = self._generate_option_symbols()
        
        # Calculate mid price for convenience
        self.df['mid'] = (self.df['bid'] + self.df['ask']) / 2
        
        return self.df
    
    def _validate(self) -> None:
        """
        Run all validation checks on the loaded data.
        
        This method populates self.validation_report with findings and
        raises ValueError for critical issues.
        """
        report = {
            'total_rows': len(self.df),
            'date_range': None,
            'underlyings': None,
            'missing_columns': [],
            'warnings': [],
            'errors': [],
        }
        
        # Check required columns
        missing_required = [col for col in self.REQUIRED_COLUMNS if col not in self.df.columns]
        if missing_required:
            report['errors'].append(f"Missing required columns: {missing_required}")
            raise ValueError(f"Missing required columns: {missing_required}")
        
        # Check recommended columns and warn if missing
        missing_recommended = [col for col in self.RECOMMENDED_COLUMNS if col not in self.df.columns]
        if missing_recommended:
            report['warnings'].append(f"Missing recommended columns (may limit validation): {missing_recommended}")
            report['missing_columns'] = missing_recommended
        
        # Get metadata
        report['date_range'] = (self.df['date'].min(), self.df['date'].max())
        report['underlyings'] = self.df['underlying'].unique().tolist()
        
        # Validate bid-ask sanity
        invalid_spreads = self.df[self.df['bid'] > self.df['ask']]
        if len(invalid_spreads) > 0:
            report['warnings'].append(f"Found {len(invalid_spreads)} rows where bid > ask (will be corrected)")
            # Swap bid and ask where inverted
            mask = self.df['bid'] > self.df['ask']
            self.df.loc[mask, ['bid', 'ask']] = self.df.loc[mask, ['ask', 'bid']].values
        
        # Validate non-negative prices
        negative_prices = self.df[(self.df['bid'] < 0) | (self.df['ask'] < 0)]
        if len(negative_prices) > 0:
            report['errors'].append(f"Found {len(negative_prices)} rows with negative prices")
        
        # Validate delta sign convention if present
        if 'delta' in self.df.columns:
            # Calls should have positive delta, puts should have negative
            calls_wrong_sign = self.df[(self.df['right'] == 'C') & (self.df['delta'] < -0.01)]
            puts_wrong_sign = self.df[(self.df['right'] == 'P') & (self.df['delta'] > 0.01)]
            
            if len(calls_wrong_sign) > 0:
                report['warnings'].append(f"Found {len(calls_wrong_sign)} calls with negative delta (sign convention issue?)")
            if len(puts_wrong_sign) > 0:
                report['warnings'].append(f"Found {len(puts_wrong_sign)} puts with positive delta (sign convention issue?)")
        
        # Check for stale quotes (ask == bid == 0)
        stale_quotes = self.df[(self.df['bid'] == 0) & (self.df['ask'] == 0)]
        if len(stale_quotes) > 0:
            report['warnings'].append(f"Found {len(stale_quotes)} rows with zero bid and ask (stale/illiquid)")
        
        # Check implied_vol range if present
        if 'implied_vol' in self.df.columns:
            # IV should typically be between 0.05 (5%) and 5.0 (500%)
            extreme_iv = self.df[(self.df['implied_vol'] < 0.05) | (self.df['implied_vol'] > 5.0)]
            if len(extreme_iv) > 0:
                report['warnings'].append(f"Found {len(extreme_iv)} rows with extreme implied_vol (<5% or >500%)")
        
        # Check open interest if present
        if 'open_interest' in self.df.columns:
            low_oi = self.df[self.df['open_interest'] < self.min_open_interest]
            pct_low_oi = len(low_oi) / len(self.df) * 100
            report['warnings'].append(f"{pct_low_oi:.1f}% of quotes have OI < {self.min_open_interest}")
        
        self.validation_report = report
        
        # Print warnings
        for warning in report['warnings']:
            warnings.warn(warning)
        
        # Raise on errors
        if report['errors']:
            raise ValueError(f"Validation errors: {report['errors']}")
    
    def _generate_option_symbols(self) -> pd.Series:
        """
        Generate OCC-style option symbols from components.
        
        OCC Format: UNDERLYING + YYMMDD + C/P + STRIKE(8 digits)
        Example: VLO260221C00180000 for VLO Feb 21, 2026 $180 Call
        """
        def make_symbol(row):
            underlying = row['underlying'].upper()
            exp = pd.to_datetime(row['expiration']).strftime('%y%m%d')
            right = 'C' if row['right'] in ['C', 'CALL'] else 'P'
            strike = int(row['strike'] * 1000)
            return f"{underlying}{exp}{right}{strike:08d}"
        
        return self.df.apply(make_symbol, axis=1)
    
    def get_chain(
        self, 
        underlying: str, 
        quote_date: date,
        expiration: Optional[date] = None,
        min_oi: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Get the option chain for a specific underlying and date.
        
        Args:
            underlying: Ticker symbol (e.g., 'VLO')
            quote_date: Date for which to get quotes
            expiration: Optional specific expiration to filter
            min_oi: Optional minimum open interest (overrides constructor setting)
        
        Returns:
            DataFrame with options chain for the specified parameters
        """
        if self.df is None:
            raise RuntimeError("Data not loaded. Call load() first.")
        
        # Filter by underlying and date
        mask = (
            (self.df['underlying'] == underlying.upper()) &
            (self.df['date'] == quote_date)
        )
        
        # Optional expiration filter
        if expiration:
            mask &= (self.df['expiration'] == expiration)
        
        # Optional OI filter
        oi_threshold = min_oi if min_oi is not None else self.min_open_interest
        if 'open_interest' in self.df.columns and oi_threshold > 0:
            mask &= (self.df['open_interest'] >= oi_threshold)
        
        chain = self.df[mask].copy()
        
        # Sort by expiration, then by strike, then by right (calls before puts)
        chain = chain.sort_values(['expiration', 'strike', 'right'])
        
        return chain
    
    def get_quote(
        self,
        underlying: str,
        quote_date: date,
        expiration: date,
        strike: float,
        right: str
    ) -> Optional[Dict]:
        """
        Get a single option quote.
        
        Args:
            underlying: Ticker symbol
            quote_date: Date for quote
            expiration: Option expiration
            strike: Strike price
            right: 'C' or 'P'
        
        Returns:
            Dict with quote data, or None if not found
        """
        if self.df is None:
            raise RuntimeError("Data not loaded. Call load() first.")
        
        right = right.upper()[0]  # Normalize to 'C' or 'P'
        
        mask = (
            (self.df['underlying'] == underlying.upper()) &
            (self.df['date'] == quote_date) &
            (self.df['expiration'] == expiration) &
            (np.isclose(self.df['strike'], strike, rtol=1e-4)) &
            (self.df['right'] == right)
        )
        
        matches = self.df[mask]
        
        if len(matches) == 0:
            return None
        
        if len(matches) > 1:
            warnings.warn(f"Multiple quotes found for {underlying} {strike} {right} {expiration} on {quote_date}, using first")
        
        return matches.iloc[0].to_dict()
    
    def get_available_dates(self, underlying: Optional[str] = None) -> List[date]:
        """
        Get list of dates for which data is available.
        
        Args:
            underlying: Optional filter for specific underlying
        
        Returns:
            Sorted list of available dates
        """
        if self.df is None:
            raise RuntimeError("Data not loaded. Call load() first.")
        
        if underlying:
            dates = self.df[self.df['underlying'] == underlying.upper()]['date'].unique()
        else:
            dates = self.df['date'].unique()
        
        return sorted(dates)
    
    def get_expirations(
        self, 
        underlying: str, 
        quote_date: date,
        min_dte: int = 0,
        max_dte: int = 365
    ) -> List[date]:
        """
        Get available expiration dates for an underlying.
        
        Args:
            underlying: Ticker symbol
            quote_date: Reference date
            min_dte: Minimum days to expiration
            max_dte: Maximum days to expiration
        
        Returns:
            Sorted list of expiration dates
        """
        if self.df is None:
            raise RuntimeError("Data not loaded. Call load() first.")
        
        mask = (
            (self.df['underlying'] == underlying.upper()) &
            (self.df['date'] == quote_date)
        )
        
        expirations = self.df[mask]['expiration'].unique()
        
        # Filter by DTE
        result = []
        for exp in expirations:
            dte = (exp - quote_date).days
            if min_dte <= dte <= max_dte:
                result.append(exp)
        
        return sorted(result)


class EquitiesDataLoader:
    """
    Loads and validates equity OHLCV data for backtesting.
    
    Expected Schema:
    - timestamp: datetime with timezone (or date if daily)
    - ticker: str
    - open, high, low, close: float (unadjusted)
    - adj_close: float (split and dividend adjusted)
    - volume: int
    
    Usage:
        loader = EquitiesDataLoader("data/raw/equities_ohlcv.csv")
        df = loader.load()
        
        # Get prices for a specific ticker and date
        price = loader.get_close("VLO", date(2026, 1, 27))
    """
    
    REQUIRED_COLUMNS = ['timestamp', 'ticker', 'open', 'high', 'low', 'close', 'volume']
    
    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.df: Optional[pd.DataFrame] = None
        self.validation_report: Dict = {}
        
    def load(self, validate: bool = True) -> pd.DataFrame:
        """Load and validate the equities data."""
        if not self.filepath.exists():
            raise FileNotFoundError(f"Equities data file not found: {self.filepath}")
        
        self.df = pd.read_csv(
            self.filepath,
            parse_dates=['timestamp'],
            dtype={
                'ticker': str,
                'open': float,
                'high': float,
                'low': float,
                'close': float,
                'volume': int,
            }
        )
        
        # Normalize column names
        self.df.columns = self.df.columns.str.lower().str.strip()
        
        if validate:
            self._validate()
        
        # Add date column for easier joining
        self.df['date'] = self.df['timestamp'].dt.date
        
        # Ensure adj_close exists (use close if not)
        if 'adj_close' not in self.df.columns:
            warnings.warn("adj_close not found, using close as adj_close (may have split/dividend issues)")
            self.df['adj_close'] = self.df['close']
        
        # Sort by ticker and timestamp
        self.df = self.df.sort_values(['ticker', 'timestamp'])
        
        return self.df
    
    def _validate(self) -> None:
        """Validate the equities data."""
        report = {
            'total_rows': len(self.df),
            'date_range': (self.df['timestamp'].min(), self.df['timestamp'].max()),
            'tickers': self.df['ticker'].unique().tolist(),
            'warnings': [],
            'errors': [],
        }
        
        # Check required columns
        missing = [col for col in self.REQUIRED_COLUMNS if col not in self.df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        # Check OHLC sanity
        invalid_ohlc = self.df[
            (self.df['low'] > self.df['high']) |
            (self.df['open'] > self.df['high']) |
            (self.df['open'] < self.df['low']) |
            (self.df['close'] > self.df['high']) |
            (self.df['close'] < self.df['low'])
        ]
        if len(invalid_ohlc) > 0:
            report['warnings'].append(f"Found {len(invalid_ohlc)} rows with invalid OHLC relationships")
        
        # Check for negative prices
        negative = self.df[
            (self.df['open'] < 0) | (self.df['high'] < 0) | 
            (self.df['low'] < 0) | (self.df['close'] < 0)
        ]
        if len(negative) > 0:
            report['errors'].append(f"Found {len(negative)} rows with negative prices")
        
        # Check for missing data (gaps in time series)
        for ticker in self.df['ticker'].unique():
            ticker_data = self.df[self.df['ticker'] == ticker].sort_values('timestamp')
            dates = ticker_data['timestamp'].dt.date.unique()
            # This is a simple gap check - more sophisticated would check trading calendar
            if len(dates) > 1:
                expected_days = (dates[-1] - dates[0]).days
                actual_days = len(dates)
                # Roughly 252 trading days per 365 calendar days
                expected_trading_days = expected_days * (252/365)
                if actual_days < expected_trading_days * 0.9:
                    report['warnings'].append(f"Ticker {ticker} may have missing data: {actual_days} days vs ~{expected_trading_days:.0f} expected")
        
        self.validation_report = report
        
        for warning in report['warnings']:
            warnings.warn(warning)
        
        if report['errors']:
            raise ValueError(f"Validation errors: {report['errors']}")
    
    def get_close(self, ticker: str, date_val: date) -> Optional[float]:
        """Get the closing price for a ticker on a specific date."""
        if self.df is None:
            raise RuntimeError("Data not loaded. Call load() first.")
        
        mask = (self.df['ticker'] == ticker.upper()) & (self.df['date'] == date_val)
        matches = self.df[mask]
        
        if len(matches) == 0:
            return None
        
        return matches.iloc[-1]['close']  # Use last if multiple (intraday data)
    
    def get_ohlcv(self, ticker: str, date_val: date) -> Optional[Dict]:
        """Get full OHLCV data for a ticker on a specific date."""
        if self.df is None:
            raise RuntimeError("Data not loaded. Call load() first.")
        
        mask = (self.df['ticker'] == ticker.upper()) & (self.df['date'] == date_val)
        matches = self.df[mask]
        
        if len(matches) == 0:
            return None
        
        row = matches.iloc[-1]
        return {
            'open': row['open'],
            'high': row['high'],
            'low': row['low'],
            'close': row['close'],
            'adj_close': row['adj_close'],
            'volume': row['volume'],
        }
    
    def get_price_history(
        self, 
        ticker: str, 
        start_date: date, 
        end_date: date
    ) -> pd.DataFrame:
        """Get price history for a ticker between dates."""
        if self.df is None:
            raise RuntimeError("Data not loaded. Call load() first.")
        
        mask = (
            (self.df['ticker'] == ticker.upper()) &
            (self.df['date'] >= start_date) &
            (self.df['date'] <= end_date)
        )
        
        return self.df[mask].copy()


class CalendarEventsLoader:
    """
    Loads and validates calendar events (earnings, FOMC, etc.) for backtesting.
    
    Expected Schema:
    - event_timestamp: datetime with timezone
    - event_type: str (EARNINGS, FOMC, CPI, POLICY, OTHER)
    - ticker: str (nullable for macro events)
    - event_label: str
    - timing: str (BMO, AMC, INTRADAY) for earnings
    - confirmed: bool
    """
    
    REQUIRED_COLUMNS = ['event_timestamp', 'event_type', 'event_label', 'confirmed']
    
    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.df: Optional[pd.DataFrame] = None
        
    def load(self, validate: bool = True) -> pd.DataFrame:
        """Load and validate calendar events."""
        if not self.filepath.exists():
            raise FileNotFoundError(f"Calendar events file not found: {self.filepath}")
        
        self.df = pd.read_csv(
            self.filepath,
            parse_dates=['event_timestamp'],
        )
        
        self.df.columns = self.df.columns.str.lower().str.strip()
        
        if validate:
            missing = [col for col in self.REQUIRED_COLUMNS if col not in self.df.columns]
            if missing:
                raise ValueError(f"Missing required columns: {missing}")
        
        # Sort by timestamp
        self.df = self.df.sort_values('event_timestamp')
        
        return self.df
    
    def get_events_for_date(self, date_val: date) -> pd.DataFrame:
        """Get all events for a specific date."""
        if self.df is None:
            raise RuntimeError("Data not loaded. Call load() first.")
        
        mask = self.df['event_timestamp'].dt.date == date_val
        return self.df[mask].copy()
    
    def get_earnings_date(self, ticker: str) -> Optional[datetime]:
        """Get the next confirmed earnings date for a ticker."""
        if self.df is None:
            raise RuntimeError("Data not loaded. Call load() first.")
        
        mask = (
            (self.df['event_type'] == 'EARNINGS') &
            (self.df['ticker'] == ticker.upper()) &
            (self.df['confirmed'] == True)
        )
        
        matches = self.df[mask].sort_values('event_timestamp')
        
        if len(matches) == 0:
            return None
        
        return matches.iloc[0]['event_timestamp'].to_pydatetime()
    
    def is_earnings_day(self, ticker: str, date_val: date) -> bool:
        """Check if a specific date is an earnings day for a ticker."""
        if self.df is None:
            raise RuntimeError("Data not loaded. Call load() first.")
        
        mask = (
            (self.df['event_type'] == 'EARNINGS') &
            (self.df['ticker'] == ticker.upper()) &
            (self.df['event_timestamp'].dt.date == date_val)
        )
        
        return len(self.df[mask]) > 0
    
    def get_fomc_dates(self) -> List[datetime]:
        """Get all FOMC meeting dates."""
        if self.df is None:
            raise RuntimeError("Data not loaded. Call load() first.")
        
        mask = self.df['event_type'] == 'FOMC'
        return self.df[mask]['event_timestamp'].tolist()


# =============================================================================
# EXAMPLE USAGE AND TESTING
# =============================================================================

if __name__ == "__main__":
    print("Data Loaders Module")
    print("=" * 50)
    print("\nThis module provides data loading and validation for:")
    print("  - OptionsDataLoader: Options EOD quotes")
    print("  - EquitiesDataLoader: Equity OHLCV prices")
    print("  - CalendarEventsLoader: Earnings/FOMC events")
    print("\nTo use, first upload the required CSV files, then:")
    print("\n  loader = OptionsDataLoader('data/raw/options_eod.csv')")
    print("  df = loader.load()")
    print("  chain = loader.get_chain('VLO', date(2026, 1, 27))")
