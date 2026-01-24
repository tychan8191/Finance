"""
data_loaders/ingest.py - Unified Data Ingestion Orchestrator for Raidillon Backtest

This module coordinates data retrieval from multiple sources to populate the
backtest framework with minimal manual CSV uploads. It leverages free APIs
where possible and integrates with TastyTrade for live/streaming data.

Data Source Matrix:
-------------------
| Dataset              | Source                    | Cost    | Method            |
|---------------------|---------------------------|---------|-------------------|
| equities_ohlcv      | yfinance                  | Free    | API               |
| vix_index           | FRED (VIXCLS)             | Free    | API               |
| rates_curve         | FRED (DGS*)               | Free    | API               |
| vix_futures_curve   | CBOE CFE                  | Free    | HTTP/CSV          |
| options_eod         | TastyTrade API            | Free*   | API + Streaming   |
| calendar_events     | Auto-generated from YAML  | Free    | Local             |
| crack_spreads       | EIA.gov                   | Free    | API               |
| cftc_cot            | CFTC.gov                  | Free    | HTTP/CSV          |

* TastyTrade requires funded account for real-time data

Usage:
------
    from src.data_loaders.ingest import DataIngestor
    
    ingestor = DataIngestor(config_path='config/strategies.yaml')
    ingestor.fetch_all(start_date='2024-10-01', end_date='2026-02-28')
    
    # Or fetch individual datasets
    ingestor.fetch_equities()
    ingestor.fetch_vix_data()
    ingestor.fetch_rates()
"""

import os
import sys
import yaml
import logging
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List, Any, Union
import pandas as pd
import numpy as np
import warnings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('raidillon.ingest')

# Project root detection
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_RAW = PROJECT_ROOT / 'data' / 'raw'
DATA_PROCESSED = PROJECT_ROOT / 'data' / 'processed'
DATA_REFERENCE = PROJECT_ROOT / 'data' / 'reference'
CONFIG_DIR = PROJECT_ROOT / 'config'


class DataIngestor:
    """
    Unified data ingestion orchestrator for the Raidillon backtest framework.
    
    This class coordinates fetching data from multiple sources (yfinance, FRED,
    CBOE, TastyTrade) and transforms it into the standardized CSV formats
    expected by the data loaders.
    
    Attributes:
        config: Parsed strategies.yaml configuration
        tickers: List of tickers required based on strategies
        start_date: Earliest date to fetch data
        end_date: Latest date to fetch data
        tastytrade_session: Optional TastyTrade API session
    """
    
    # Default tickers derived from strategies.yaml analysis
    DEFAULT_TICKERS = [
        'VIX', 'VLO', 'KRE', 'KTOS', 'GS', 'MSFT', 'AMD', 
        'META', 'MPC', 'DHT', 'RTX', 'SPY', 'AAPL', 'TSLA', 'NVDA'
    ]
    
    # FRED series for rates curve
    FRED_RATE_SERIES = {
        '3M': 'DGS3MO',
        '2Y': 'DGS2',
        '5Y': 'DGS5',
        '10Y': 'DGS10',
        '30Y': 'DGS30',
    }
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        start_date: str = '2024-10-01',
        end_date: str = '2026-02-28',
        tastytrade_credentials: Optional[Dict[str, str]] = None
    ):
        """
        Initialize the data ingestor.
        
        Args:
            config_path: Path to strategies.yaml (optional, uses default if None)
            start_date: Start date for historical data (YYYY-MM-DD)
            end_date: End date for historical data (YYYY-MM-DD)
            tastytrade_credentials: Dict with 'username' and 'password' keys
        """
        # Ensure data directories exist
        for dir_path in [DATA_RAW, DATA_PROCESSED, DATA_REFERENCE]:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        # Parse dates
        self.start_date = pd.to_datetime(start_date).date()
        self.end_date = pd.to_datetime(end_date).date()
        
        # Load configuration
        self.config = self._load_config(config_path)
        self.tickers = self._extract_tickers()
        
        # TastyTrade session (lazy initialization)
        self._tastytrade_session = None
        self._tastytrade_credentials = tastytrade_credentials
        
        # Track what has been fetched
        self._fetch_status: Dict[str, bool] = {}
        
        logger.info(f"DataIngestor initialized: {self.start_date} to {self.end_date}")
        logger.info(f"Tracking {len(self.tickers)} tickers: {', '.join(self.tickers)}")
    
    def _load_config(self, config_path: Optional[str]) -> Dict:
        """Load and parse the strategies.yaml configuration file."""
        if config_path is None:
            config_path = CONFIG_DIR / 'strategies.yaml'
        else:
            config_path = Path(config_path)
        
        if not config_path.exists():
            logger.warning(f"Config not found at {config_path}, using defaults")
            return {'strategies': {}, 'global': {}}
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        logger.info(f"Loaded configuration from {config_path}")
        return config
    
    def _extract_tickers(self) -> List[str]:
        """Extract all required tickers from strategy configuration."""
        tickers = set(self.DEFAULT_TICKERS)
        
        # Extract from strategies
        for strategy_name, strategy in self.config.get('strategies', {}).items():
            if 'underlying' in strategy:
                tickers.add(strategy['underlying'].upper())
            
            # Check for read-through tickers in conditions
            for condition in strategy.get('entry_conditions', []):
                if 'tickers' in condition:
                    tickers.update(t.upper() for t in condition['tickers'])
        
        # Extract from catalyst calendar
        for date_str, events in self.config.get('catalyst_calendar', {}).items():
            for event in events:
                if 'ticker' in event:
                    tickers.add(event['ticker'].upper())
                if 'tickers' in event:
                    tickers.update(t.upper() for t in event['tickers'])
        
        return sorted(list(tickers))
    
    # =========================================================================
    # EQUITY OHLCV DATA (yfinance)
    # =========================================================================
    
    def fetch_equities(self, tickers: Optional[List[str]] = None) -> pd.DataFrame:
        """
        Fetch equity OHLCV data from yfinance.
        
        This method retrieves daily OHLCV data for all required tickers and
        saves it in the format expected by EquitiesDataLoader.
        
        Args:
            tickers: Optional list of tickers (uses self.tickers if None)
        
        Returns:
            DataFrame with columns: timestamp, ticker, open, high, low, close, adj_close, volume
        """
        try:
            import yfinance as yf
        except ImportError:
            raise ImportError("yfinance required: pip install yfinance")
        
        tickers = tickers or self.tickers
        
        # Filter out VIX (handled separately as an index)
        equity_tickers = [t for t in tickers if t != 'VIX']
        
        logger.info(f"Fetching equity OHLCV for {len(equity_tickers)} tickers...")
        
        # Download all tickers at once (more efficient)
        raw_data = yf.download(
            equity_tickers,
            start=self.start_date,
            end=self.end_date + timedelta(days=1),  # yfinance end is exclusive
            group_by='ticker',
            auto_adjust=False,
            progress=True
        )
        
        # Transform to long format expected by our loaders
        records = []
        
        for ticker in equity_tickers:
            try:
                if len(equity_tickers) == 1:
                    ticker_data = raw_data
                else:
                    ticker_data = raw_data[ticker]
                
                for idx, row in ticker_data.iterrows():
                    if pd.isna(row['Close']):
                        continue
                    
                    records.append({
                        'timestamp': idx.strftime('%Y-%m-%dT16:00:00-05:00'),
                        'ticker': ticker,
                        'open': round(row['Open'], 4),
                        'high': round(row['High'], 4),
                        'low': round(row['Low'], 4),
                        'close': round(row['Close'], 4),
                        'adj_close': round(row['Adj Close'], 4),
                        'volume': int(row['Volume']) if not pd.isna(row['Volume']) else 0,
                    })
            except Exception as e:
                logger.warning(f"Error processing {ticker}: {e}")
        
        df = pd.DataFrame(records)
        
        # Save to CSV
        output_path = DATA_RAW / 'equities_ohlcv.csv'
        df.to_csv(output_path, index=False)
        logger.info(f"Saved {len(df)} equity records to {output_path}")
        
        self._fetch_status['equities_ohlcv'] = True
        return df
    
    # =========================================================================
    # VIX INDEX DATA (FRED)
    # =========================================================================
    
    def fetch_vix_index(self) -> pd.DataFrame:
        """
        Fetch VIX index data from FRED (Federal Reserve Economic Data).
        
        The VIXCLS series provides daily VIX closing values going back to 1990.
        
        Returns:
            DataFrame with columns: date, vix_open, vix_high, vix_low, vix_close
        """
        try:
            from pandas_datareader import data as pdr
        except ImportError:
            raise ImportError("pandas-datareader required: pip install pandas-datareader")
        
        logger.info("Fetching VIX index from FRED...")
        
        # FRED only provides close, so we'll need CBOE for OHLC
        # But FRED is the most reliable source for the close
        vix_close = pdr.DataReader(
            'VIXCLS',
            'fred',
            start=self.start_date,
            end=self.end_date
        )
        
        # Also try to get OHLC from yfinance (^VIX)
        try:
            import yfinance as yf
            vix_ohlc = yf.download(
                '^VIX',
                start=self.start_date,
                end=self.end_date + timedelta(days=1),
                progress=False
            )
            
            # Merge FRED close with yfinance OHLC
            records = []
            for idx, row in vix_ohlc.iterrows():
                date_val = idx.date()
                fred_val = vix_close.loc[vix_close.index.date == date_val, 'VIXCLS']
                close_val = fred_val.values[0] if len(fred_val) > 0 else row['Close']
                
                records.append({
                    'date': date_val.isoformat(),
                    'vix_open': round(row['Open'], 2),
                    'vix_high': round(row['High'], 2),
                    'vix_low': round(row['Low'], 2),
                    'vix_close': round(close_val, 2),
                })
            
            df = pd.DataFrame(records)
            
        except Exception as e:
            logger.warning(f"Could not fetch VIX OHLC from yfinance: {e}")
            # Fall back to FRED only (close values)
            df = pd.DataFrame({
                'date': vix_close.index.date,
                'vix_open': vix_close['VIXCLS'].values,
                'vix_high': vix_close['VIXCLS'].values,
                'vix_low': vix_close['VIXCLS'].values,
                'vix_close': vix_close['VIXCLS'].values,
            })
        
        # Drop any rows with NaN
        df = df.dropna()
        
        # Save to CSV
        output_path = DATA_RAW / 'vix_index.csv'
        df.to_csv(output_path, index=False)
        logger.info(f"Saved {len(df)} VIX records to {output_path}")
        
        self._fetch_status['vix_index'] = True
        return df
    
    # =========================================================================
    # RATES CURVE DATA (FRED)
    # =========================================================================
    
    def fetch_rates_curve(self) -> pd.DataFrame:
        """
        Fetch Treasury rates curve from FRED for Black-Scholes calculations.
        
        Fetches constant maturity rates for 3M, 2Y, 5Y, 10Y, 30Y tenors.
        
        Returns:
            DataFrame with columns: date, tenor, rate_annualized
        """
        try:
            from pandas_datareader import data as pdr
        except ImportError:
            raise ImportError("pandas-datareader required: pip install pandas-datareader")
        
        logger.info("Fetching rates curve from FRED...")
        
        records = []
        
        for tenor, series_id in self.FRED_RATE_SERIES.items():
            try:
                data = pdr.DataReader(
                    series_id,
                    'fred',
                    start=self.start_date,
                    end=self.end_date
                )
                
                for idx, row in data.iterrows():
                    if pd.isna(row[series_id]):
                        continue
                    
                    # FRED rates are in percentage, convert to decimal
                    rate = row[series_id] / 100.0
                    
                    records.append({
                        'date': idx.date().isoformat(),
                        'tenor': tenor,
                        'rate_annualized': round(rate, 6),
                    })
                    
            except Exception as e:
                logger.warning(f"Could not fetch {tenor} rate ({series_id}): {e}")
        
        df = pd.DataFrame(records)
        
        # Sort by date and tenor
        df = df.sort_values(['date', 'tenor'])
        
        # Save to CSV
        output_path = DATA_RAW / 'rates_curve.csv'
        df.to_csv(output_path, index=False)
        logger.info(f"Saved {len(df)} rate records to {output_path}")
        
        self._fetch_status['rates_curve'] = True
        return df
    
    # =========================================================================
    # VIX FUTURES CURVE (CBOE)
    # =========================================================================
    
    def fetch_vix_futures(self) -> pd.DataFrame:
        """
        Fetch VIX futures term structure from CBOE CFE.
        
        This is critical for VIX option pricing since VIX options settle to
        futures, not spot VIX.
        
        Returns:
            DataFrame with columns: date, vx_m1, vx_m2, vx_m3, vx_m4, vx_m1_expiry, vx_m2_expiry
        """
        logger.info("Fetching VIX futures from CBOE...")
        
        # Try using the vix-utils package first (most convenient)
        try:
            from .sources.cboe_vix import fetch_vix_futures_term_structure
            df = fetch_vix_futures_term_structure(self.start_date, self.end_date)
            
            output_path = DATA_RAW / 'vix_futures_curve.csv'
            df.to_csv(output_path, index=False)
            logger.info(f"Saved {len(df)} VIX futures records to {output_path}")
            
            self._fetch_status['vix_futures_curve'] = True
            return df
            
        except ImportError:
            logger.warning("CBOE VIX source not available, creating placeholder")
            # Create a placeholder with instructions
            return self._create_vix_futures_placeholder()
    
    def _create_vix_futures_placeholder(self) -> pd.DataFrame:
        """Create a placeholder VIX futures file with download instructions."""
        placeholder = pd.DataFrame({
            'date': [self.start_date.isoformat()],
            'vx_m1': [16.50],
            'vx_m2': [17.25],
            'vx_m3': [17.80],
            'vx_m4': [18.10],
            'vx_m1_expiry': ['2026-01-22'],
            'vx_m2_expiry': ['2026-02-19'],
        })
        
        # Save with instructions in a companion file
        output_path = DATA_RAW / 'vix_futures_curve.csv'
        placeholder.to_csv(output_path, index=False)
        
        instructions = """
# VIX Futures Data Instructions
# ==============================
# 
# The VIX futures term structure must be downloaded manually from CBOE:
# https://www.cboe.com/us/futures/market_statistics/historical_data/
#
# Steps:
# 1. Go to the URL above
# 2. Select "VX+VXT" from the symbol dropdown
# 3. Download each contract month needed (VXF26, VXG26, VXH26, etc.)
# 4. Run the CBOE parser to combine into term structure format
#
# Alternatively, install vix-utils: pip install vix-utils
# Then run: vixutil term-structure --start 2024-10-01 --end 2026-02-28
"""
        
        instructions_path = DATA_RAW / 'VIX_FUTURES_README.txt'
        with open(instructions_path, 'w') as f:
            f.write(instructions)
        
        logger.warning(f"Created placeholder VIX futures file. See {instructions_path}")
        return placeholder
    
    # =========================================================================
    # CALENDAR EVENTS (Auto-generated from YAML)
    # =========================================================================
    
    def generate_calendar_events(self) -> pd.DataFrame:
        """
        Generate calendar events CSV from strategies.yaml configuration.
        
        This parses the catalyst_calendar and strategy catalysts sections
        to create a complete event timeline.
        
        Returns:
            DataFrame with columns: event_timestamp, event_type, ticker, event_label, timing, confirmed
        """
        logger.info("Generating calendar events from configuration...")
        
        records = []
        tz = self.config.get('global', {}).get('timezone', 'America/New_York')
        
        # Process catalyst_calendar section
        for date_str, events in self.config.get('catalyst_calendar', {}).items():
            for event in events:
                event_type = event.get('type', 'OTHER')
                
                # Determine timestamp
                timing = event.get('timing', '09:30')
                if timing in ['BMO', 'PRE']:
                    time_str = '07:00:00'
                elif timing in ['AMC', 'POST']:
                    time_str = '16:30:00'
                elif timing in ['DAY_1']:
                    time_str = '09:30:00'
                elif ':' in str(timing):
                    time_str = timing + ':00' if timing.count(':') == 1 else timing
                else:
                    time_str = '09:30:00'
                
                timestamp = f"{date_str}T{time_str}-05:00"
                
                # Handle ticker(s)
                tickers = event.get('tickers', [event.get('ticker')])
                tickers = [t for t in tickers if t is not None]
                
                if tickers:
                    for ticker in tickers:
                        records.append({
                            'event_timestamp': timestamp,
                            'event_type': event_type,
                            'ticker': ticker,
                            'event_label': event.get('label', event.get('note', f'{event_type}')),
                            'timing': event.get('timing', 'UNKNOWN'),
                            'confirmed': True,
                        })
                else:
                    # Macro event without ticker
                    records.append({
                        'event_timestamp': timestamp,
                        'event_type': event_type,
                        'ticker': None,
                        'event_label': event.get('label', event.get('note', f'{event_type}')),
                        'timing': event.get('timing', 'UNKNOWN'),
                        'confirmed': True,
                    })
        
        # Process strategy catalysts
        for strategy_name, strategy in self.config.get('strategies', {}).items():
            for catalyst in strategy.get('catalysts', []):
                date_str = catalyst.get('date')
                if not date_str:
                    continue
                
                event_type = catalyst.get('type', 'OTHER')
                timing = catalyst.get('timing', '09:30')
                
                if timing in ['BMO', 'PRE']:
                    time_str = '07:00:00'
                elif timing in ['AMC', 'POST']:
                    time_str = '16:30:00'
                elif ':' in str(timing):
                    time_str = timing + ':00' if str(timing).count(':') == 1 else timing
                else:
                    time_str = '09:30:00'
                
                timestamp = f"{date_str}T{time_str}-05:00"
                ticker = catalyst.get('ticker', strategy.get('underlying'))
                
                records.append({
                    'event_timestamp': timestamp,
                    'event_type': event_type,
                    'ticker': ticker,
                    'event_label': catalyst.get('label', f"{strategy_name} catalyst"),
                    'timing': timing,
                    'confirmed': catalyst.get('status') != 'tentative',
                })
        
        df = pd.DataFrame(records)
        
        # Remove duplicates (same timestamp + ticker + event_type)
        df = df.drop_duplicates(subset=['event_timestamp', 'ticker', 'event_type'])
        
        # Sort by timestamp
        df = df.sort_values('event_timestamp')
        
        # Save to CSV
        output_path = DATA_RAW / 'calendar_events.csv'
        df.to_csv(output_path, index=False)
        logger.info(f"Saved {len(df)} calendar events to {output_path}")
        
        self._fetch_status['calendar_events'] = True
        return df
    
    # =========================================================================
    # CRACK SPREADS (EIA)
    # =========================================================================
    
    def fetch_crack_spreads(self) -> pd.DataFrame:
        """
        Fetch/calculate crack spread data from EIA petroleum prices.
        
        The 3-2-1 crack spread is calculated as:
        (2 * RBOB Gasoline + 1 * Heating Oil - 3 * WTI Crude) / 3
        
        Returns:
            DataFrame with columns: date, region, spread_3_2_1
        """
        logger.info("Fetching crack spread components from EIA/yfinance...")
        
        try:
            import yfinance as yf
            
            # Fetch crude oil (CL=F), RBOB gasoline (RB=F), heating oil (HO=F)
            symbols = {
                'crude': 'CL=F',
                'rbob': 'RB=F', 
                'heating_oil': 'HO=F'
            }
            
            data = {}
            for name, symbol in symbols.items():
                df = yf.download(
                    symbol,
                    start=self.start_date,
                    end=self.end_date + timedelta(days=1),
                    progress=False
                )
                data[name] = df['Close']
            
            # Combine into single DataFrame
            prices = pd.DataFrame(data)
            prices = prices.dropna()
            
            # Calculate 3-2-1 crack spread
            # Note: Gasoline and heating oil are in $/gallon, crude in $/barrel
            # 1 barrel = 42 gallons
            # Spread = (2 * RBOB * 42 + 1 * HO * 42 - 3 * Crude) / 3
            prices['spread_3_2_1'] = (
                (2 * prices['rbob'] * 42 + prices['heating_oil'] * 42 - 3 * prices['crude']) / 3
            )
            
            records = []
            for idx, row in prices.iterrows():
                records.append({
                    'date': idx.date().isoformat(),
                    'region': 'USGC',  # Gulf Coast reference
                    'spread_3_2_1': round(row['spread_3_2_1'], 2),
                })
            
            df = pd.DataFrame(records)
            
        except Exception as e:
            logger.warning(f"Could not fetch crack spread data: {e}")
            # Return empty placeholder
            df = pd.DataFrame(columns=['date', 'region', 'spread_3_2_1'])
        
        # Save to CSV
        output_path = DATA_RAW / 'crack_spreads.csv'
        df.to_csv(output_path, index=False)
        logger.info(f"Saved {len(df)} crack spread records to {output_path}")
        
        self._fetch_status['crack_spreads'] = True
        return df
    
    # =========================================================================
    # CFTC COT DATA
    # =========================================================================
    
    def fetch_cftc_cot(self) -> pd.DataFrame:
        """
        Fetch CFTC Commitment of Traders data for VIX positioning.
        
        Returns:
            DataFrame with columns: report_date, market, net_speculative_position
        """
        logger.info("Fetching CFTC COT data...")
        
        try:
            from .sources.cftc_cot import fetch_cot_data
            df = fetch_cot_data('VIX', self.start_date, self.end_date)
            
        except ImportError:
            logger.warning("CFTC COT source not available, creating placeholder")
            # Create placeholder
            df = pd.DataFrame({
                'report_date': [self.start_date.isoformat()],
                'market': ['VIX'],
                'net_speculative_position': [-85000],
            })
        
        output_path = DATA_RAW / 'cftc_cot.csv'
        df.to_csv(output_path, index=False)
        logger.info(f"Saved {len(df)} COT records to {output_path}")
        
        self._fetch_status['cftc_cot'] = True
        return df
    
    # =========================================================================
    # TASTYTRADE OPTIONS DATA
    # =========================================================================
    
    def _init_tastytrade(self):
        """Initialize TastyTrade session if credentials are available."""
        if self._tastytrade_session is not None:
            return self._tastytrade_session
        
        if self._tastytrade_credentials is None:
            # Try environment variables
            username = os.environ.get('TASTYTRADE_USERNAME')
            password = os.environ.get('TASTYTRADE_PASSWORD')
            
            if not username or not password:
                logger.warning("TastyTrade credentials not found. Set TASTYTRADE_USERNAME and TASTYTRADE_PASSWORD")
                return None
            
            self._tastytrade_credentials = {
                'username': username,
                'password': password,
            }
        
        try:
            from tastytrade import Session
            self._tastytrade_session = Session(
                self._tastytrade_credentials['username'],
                self._tastytrade_credentials['password']
            )
            logger.info("TastyTrade session initialized successfully")
            return self._tastytrade_session
            
        except ImportError:
            logger.error("tastytrade package not installed: pip install tastytrade")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize TastyTrade session: {e}")
            return None
    
    def fetch_options_chain_live(
        self, 
        underlying: str,
        expiration: Optional[date] = None
    ) -> pd.DataFrame:
        """
        Fetch live options chain from TastyTrade API.
        
        This fetches current quotes, not historical data. For backtesting,
        you would need to accumulate this data daily or use TastyTrade's
        backtester API.
        
        Args:
            underlying: Ticker symbol
            expiration: Optional specific expiration date
        
        Returns:
            DataFrame with options chain data
        """
        session = self._init_tastytrade()
        if session is None:
            logger.error("Cannot fetch options: TastyTrade session not available")
            return pd.DataFrame()
        
        try:
            from tastytrade.instruments import get_option_chain
            from tastytrade.market_data import get_market_data_by_type
            
            logger.info(f"Fetching options chain for {underlying}...")
            
            # Get available option chain
            chain = get_option_chain(session, underlying)
            
            records = []
            
            for exp_date, options in chain.items():
                if expiration and exp_date != expiration:
                    continue
                
                # Get market data for these options
                option_symbols = [opt.symbol for opt in options]
                
                # Batch fetch market data
                market_data = get_market_data_by_type(
                    session,
                    options=option_symbols[:100]  # API limit
                )
                
                for opt, md in zip(options, market_data):
                    records.append({
                        'date': date.today().isoformat(),
                        'underlying': underlying,
                        'expiration': opt.expiration_date.isoformat(),
                        'strike': float(opt.strike_price),
                        'right': 'C' if opt.option_type.value == 'C' else 'P',
                        'bid': float(md.bid) if md.bid else 0.0,
                        'ask': float(md.ask) if md.ask else 0.0,
                        'implied_vol': None,  # Not directly available
                        'delta': None,
                        'open_interest': None,
                    })
            
            df = pd.DataFrame(records)
            return df
            
        except Exception as e:
            logger.error(f"Error fetching options chain: {e}")
            return pd.DataFrame()
    
    def create_options_eod_template(self) -> pd.DataFrame:
        """
        Create a template options_eod.csv file with the expected schema.
        
        This is useful when you need to manually input historical options
        data or use it as a reference for data formatting.
        
        Returns:
            DataFrame with example rows demonstrating the expected format
        """
        logger.info("Creating options_eod.csv template...")
        
        # Generate example rows for each strategy's underlying
        records = []
        example_date = date(2025, 12, 15)
        
        underlyings = list(set(
            strategy.get('underlying', 'SPY')
            for strategy in self.config.get('strategies', {}).values()
        ))
        
        for underlying in underlyings:
            # Example call spread
            records.extend([
                {
                    'date': example_date.isoformat(),
                    'underlying': underlying,
                    'expiration': date(2026, 2, 20).isoformat(),
                    'strike': 100.0,
                    'right': 'C',
                    'bid': 5.50,
                    'ask': 5.80,
                    'implied_vol': 0.35,
                    'delta': 0.55,
                    'open_interest': 1500,
                },
                {
                    'date': example_date.isoformat(),
                    'underlying': underlying,
                    'expiration': date(2026, 2, 20).isoformat(),
                    'strike': 110.0,
                    'right': 'C',
                    'bid': 2.20,
                    'ask': 2.50,
                    'implied_vol': 0.38,
                    'delta': 0.35,
                    'open_interest': 2000,
                },
            ])
        
        df = pd.DataFrame(records)
        
        # Save template
        output_path = DATA_RAW / 'options_eod.csv'
        df.to_csv(output_path, index=False)
        logger.info(f"Created options template at {output_path}")
        
        # Also create a README
        readme = f"""
# Options EOD Data Requirements
# ==============================
#
# This file requires historical options End-of-Day data.
# 
# Recommended sources:
# 1. ORATS ($99/mo) - https://orats.com - Most comprehensive
# 2. Polygon Options ($49/mo) - https://polygon.io
# 3. TastyTrade Backtester API - Use via their platform
#
# Required columns:
# - date: YYYY-MM-DD
# - underlying: ticker symbol
# - expiration: YYYY-MM-DD
# - strike: float
# - right: C or P
# - bid: float
# - ask: float
#
# Strongly recommended:
# - implied_vol: decimal (0.35 = 35%)
# - delta: -1 to 1
# - open_interest: integer
#
# Tickers needed: {', '.join(underlyings)}
# Date range: {self.start_date} to {self.end_date}
"""
        
        readme_path = DATA_RAW / 'OPTIONS_EOD_README.txt'
        with open(readme_path, 'w') as f:
            f.write(readme)
        
        return df
    
    # =========================================================================
    # UNIFIED FETCH ALL
    # =========================================================================
    
    def fetch_all(self, include_options: bool = False) -> Dict[str, pd.DataFrame]:
        """
        Fetch all required datasets.
        
        This is the main entry point for populating the data directory with
        all required historical data.
        
        Args:
            include_options: Whether to attempt fetching live options from TastyTrade
        
        Returns:
            Dict mapping dataset name to DataFrame
        """
        results = {}
        
        logger.info("=" * 60)
        logger.info("STARTING FULL DATA INGESTION")
        logger.info("=" * 60)
        
        # 1. Equities OHLCV (yfinance) - CRITICAL
        try:
            results['equities_ohlcv'] = self.fetch_equities()
        except Exception as e:
            logger.error(f"Failed to fetch equities: {e}")
        
        # 2. VIX Index (FRED) - CRITICAL
        try:
            results['vix_index'] = self.fetch_vix_index()
        except Exception as e:
            logger.error(f"Failed to fetch VIX index: {e}")
        
        # 3. Rates Curve (FRED) - REQUIRED for Greeks
        try:
            results['rates_curve'] = self.fetch_rates_curve()
        except Exception as e:
            logger.error(f"Failed to fetch rates curve: {e}")
        
        # 4. VIX Futures (CBOE) - CRITICAL for VIX strategy
        try:
            results['vix_futures_curve'] = self.fetch_vix_futures()
        except Exception as e:
            logger.error(f"Failed to fetch VIX futures: {e}")
        
        # 5. Calendar Events (auto-generated) - CRITICAL
        try:
            results['calendar_events'] = self.generate_calendar_events()
        except Exception as e:
            logger.error(f"Failed to generate calendar events: {e}")
        
        # 6. Crack Spreads (EIA) - Required for refiner strategies
        try:
            results['crack_spreads'] = self.fetch_crack_spreads()
        except Exception as e:
            logger.error(f"Failed to fetch crack spreads: {e}")
        
        # 7. CFTC COT (optional)
        try:
            results['cftc_cot'] = self.fetch_cftc_cot()
        except Exception as e:
            logger.warning(f"Failed to fetch CFTC COT: {e}")
        
        # 8. Options EOD template
        results['options_eod_template'] = self.create_options_eod_template()
        
        # 9. Live options (if requested and TastyTrade available)
        if include_options:
            for ticker in ['VLO', 'VIX', 'SPY', 'KTOS']:
                try:
                    df = self.fetch_options_chain_live(ticker)
                    if not df.empty:
                        results[f'options_live_{ticker}'] = df
                except Exception as e:
                    logger.warning(f"Could not fetch options for {ticker}: {e}")
        
        # Summary
        logger.info("=" * 60)
        logger.info("DATA INGESTION COMPLETE")
        logger.info("=" * 60)
        
        for name, status in self._fetch_status.items():
            status_str = "✓" if status else "✗"
            logger.info(f"  {status_str} {name}")
        
        logger.info(f"\nData saved to: {DATA_RAW}")
        
        return results
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of data ingestion."""
        return {
            'fetch_status': self._fetch_status.copy(),
            'data_directory': str(DATA_RAW),
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'tickers': self.tickers,
            'tastytrade_connected': self._tastytrade_session is not None,
        }


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """Command-line interface for data ingestion."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Raidillon Backtest Data Ingestion Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fetch all data with default date range
  python -m src.data_loaders.ingest --all

  # Fetch specific datasets
  python -m src.data_loaders.ingest --equities --vix --rates

  # Custom date range
  python -m src.data_loaders.ingest --all --start 2024-01-01 --end 2026-06-30

  # Include live options from TastyTrade
  python -m src.data_loaders.ingest --all --options
        """
    )
    
    parser.add_argument('--all', action='store_true', help='Fetch all datasets')
    parser.add_argument('--equities', action='store_true', help='Fetch equity OHLCV data')
    parser.add_argument('--vix', action='store_true', help='Fetch VIX index data')
    parser.add_argument('--rates', action='store_true', help='Fetch rates curve data')
    parser.add_argument('--vix-futures', action='store_true', help='Fetch VIX futures data')
    parser.add_argument('--calendar', action='store_true', help='Generate calendar events')
    parser.add_argument('--crack-spreads', action='store_true', help='Fetch crack spread data')
    parser.add_argument('--options', action='store_true', help='Fetch live options (requires TastyTrade)')
    
    parser.add_argument('--start', default='2024-10-01', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', default='2026-02-28', help='End date (YYYY-MM-DD)')
    parser.add_argument('--config', default=None, help='Path to strategies.yaml')
    
    args = parser.parse_args()
    
    # Initialize ingestor
    ingestor = DataIngestor(
        config_path=args.config,
        start_date=args.start,
        end_date=args.end
    )
    
    # Execute requested fetches
    if args.all:
        ingestor.fetch_all(include_options=args.options)
    else:
        if args.equities:
            ingestor.fetch_equities()
        if args.vix:
            ingestor.fetch_vix_index()
        if args.rates:
            ingestor.fetch_rates_curve()
        if args.vix_futures:
            ingestor.fetch_vix_futures()
        if args.calendar:
            ingestor.generate_calendar_events()
        if args.crack_spreads:
            ingestor.fetch_crack_spreads()
        if args.options:
            for ticker in ['VLO', 'VIX', 'SPY']:
                ingestor.fetch_options_chain_live(ticker)
    
    # Print status
    status = ingestor.get_status()
    print("\n" + "=" * 50)
    print("INGESTION STATUS")
    print("=" * 50)
    for name, fetched in status['fetch_status'].items():
        print(f"  {'✓' if fetched else '✗'} {name}")


if __name__ == '__main__':
    main()
