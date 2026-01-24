"""
sources/tastytrade_client.py - TastyTrade API Integration

This module provides a comprehensive interface to TastyTrade's API for:
1. Fetching live options chains and quotes
2. Streaming real-time market data via DXLink
3. Account management and position tracking
4. Order submission and management

The TastyTrade API serves two distinct purposes in the Raidillon framework:

For Backtesting:
- Use the Backtester API to simulate historical trades
- Access historical options data for specific strategies
- Validate strategy parameters against historical performance

For Live Trading:
- Stream real-time options quotes
- Submit multi-leg spread orders
- Monitor positions and P&L
- Implement automated entry/exit rules

Authentication:
---------------
Set environment variables:
    TASTYTRADE_USERNAME - Your TastyTrade username
    TASTYTRADE_PASSWORD - Your TastyTrade password

Or pass credentials directly:
    client = TastyTradeClient(username='...', password='...')

Usage Examples:
---------------
    # Initialize client
    from src.data_loaders.sources.tastytrade_client import TastyTradeClient
    client = TastyTradeClient()
    
    # Get options chain
    chain = client.get_option_chain('VLO', expiration='2026-02-21')
    
    # Get specific quote
    quote = client.get_option_quote('VLO', strike=180, right='C', expiration='2026-02-21')
    
    # Stream real-time quotes
    async for quote in client.stream_quotes(['VLO', 'SPY']):
        print(quote)
    
    # Submit a debit spread order
    order_id = client.submit_vertical_spread(
        underlying='VLO',
        expiration='2026-02-21',
        long_strike=180,
        short_strike=195,
        right='C',
        quantity=1,
        limit_price=4.00
    )
"""

import os
import asyncio
import logging
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List, Any, AsyncGenerator
from decimal import Decimal
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger('raidillon.tastytrade')


class OrderSide(Enum):
    """Order side for options trades."""
    BUY_TO_OPEN = "Buy to Open"
    SELL_TO_OPEN = "Sell to Open"
    BUY_TO_CLOSE = "Buy to Close"
    SELL_TO_CLOSE = "Sell to Close"


class OrderType(Enum):
    """Order type."""
    LIMIT = "Limit"
    MARKET = "Market"
    STOP = "Stop"
    STOP_LIMIT = "Stop Limit"


class TimeInForce(Enum):
    """Time in force for orders."""
    DAY = "Day"
    GTC = "GTC"  # Good til canceled
    GTD = "GTD"  # Good til date
    IOC = "IOC"  # Immediate or cancel


@dataclass
class OptionQuote:
    """Represents a single option quote."""
    symbol: str
    underlying: str
    expiration: date
    strike: float
    right: str  # 'C' or 'P'
    bid: float
    ask: float
    last: Optional[float] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    implied_vol: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2
    
    @property
    def spread(self) -> float:
        return self.ask - self.bid
    
    @property
    def spread_pct(self) -> float:
        if self.mid == 0:
            return 0
        return (self.spread / self.mid) * 100


@dataclass
class AccountBalance:
    """Represents account balance information."""
    account_number: str
    cash_balance: float
    buying_power: float
    net_liquidating_value: float
    day_trading_buying_power: float
    maintenance_requirement: float


@dataclass
class Position:
    """Represents an open position."""
    symbol: str
    underlying: str
    quantity: int
    average_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float


class TastyTradeClient:
    """
    High-level client for TastyTrade API integration.
    
    This client wraps the tastytrade SDK and provides methods specifically
    designed for the Raidillon options trading workflow.
    """
    
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        sandbox: bool = False
    ):
        """
        Initialize the TastyTrade client.
        
        Args:
            username: TastyTrade username (or set TASTYTRADE_USERNAME env var)
            password: TastyTrade password (or set TASTYTRADE_PASSWORD env var)
            sandbox: If True, use the sandbox/paper trading environment
        """
        self.username = username or os.environ.get('TASTYTRADE_USERNAME')
        self.password = password or os.environ.get('TASTYTRADE_PASSWORD')
        self.sandbox = sandbox
        
        self._session = None
        self._account = None
        self._streamer = None
        
        # Validate credentials
        if not self.username or not self.password:
            logger.warning(
                "TastyTrade credentials not provided. "
                "Set TASTYTRADE_USERNAME and TASTYTRADE_PASSWORD environment variables, "
                "or pass username/password to constructor."
            )
    
    def _ensure_session(self):
        """Ensure we have an authenticated session."""
        if self._session is not None:
            return
        
        if not self.username or not self.password:
            raise ValueError(
                "TastyTrade credentials required. "
                "Set TASTYTRADE_USERNAME and TASTYTRADE_PASSWORD env vars."
            )
        
        try:
            from tastytrade import Session
            
            self._session = Session(
                self.username,
                self.password,
                is_test=self.sandbox
            )
            logger.info(f"Authenticated with TastyTrade (sandbox={self.sandbox})")
            
        except ImportError:
            raise ImportError(
                "tastytrade package required: pip install tastytrade"
            )
        except Exception as e:
            raise ConnectionError(f"Failed to authenticate with TastyTrade: {e}")
    
    def _get_account(self):
        """Get the primary trading account."""
        if self._account is not None:
            return self._account
        
        self._ensure_session()
        
        from tastytrade import Account
        accounts = Account.get(self._session)
        
        if not accounts:
            raise ValueError("No accounts found for this TastyTrade login")
        
        # Use first account (typically the main account)
        self._account = accounts[0]
        logger.info(f"Using account: {self._account.account_number}")
        
        return self._account
    
    # =========================================================================
    # OPTIONS CHAIN DATA
    # =========================================================================
    
    def get_option_chain(
        self,
        underlying: str,
        expiration: Optional[date] = None,
        min_dte: int = 0,
        max_dte: int = 90
    ) -> List[OptionQuote]:
        """
        Fetch the complete options chain for an underlying.
        
        Args:
            underlying: Ticker symbol (e.g., 'VLO')
            expiration: Specific expiration date (optional)
            min_dte: Minimum days to expiration (default 0)
            max_dte: Maximum days to expiration (default 90)
        
        Returns:
            List of OptionQuote objects
        """
        self._ensure_session()
        
        from tastytrade.instruments import get_option_chain
        from tastytrade.market_data import get_market_data_by_type
        
        logger.info(f"Fetching option chain for {underlying}")
        
        # Get chain structure
        chain = get_option_chain(self._session, underlying)
        
        quotes = []
        today = date.today()
        
        for exp_date, options in chain.items():
            # Apply DTE filter
            dte = (exp_date - today).days
            if dte < min_dte or dte > max_dte:
                continue
            
            # Apply specific expiration filter
            if expiration and exp_date != expiration:
                continue
            
            # Fetch market data for this expiration
            symbols = [opt.symbol for opt in options]
            
            # Batch fetch (API has limits, so chunk if needed)
            for i in range(0, len(symbols), 50):
                batch_symbols = symbols[i:i+50]
                batch_options = options[i:i+50]
                
                try:
                    market_data = get_market_data_by_type(
                        self._session,
                        options=batch_symbols
                    )
                    
                    for opt, md in zip(batch_options, market_data):
                        quote = OptionQuote(
                            symbol=opt.symbol,
                            underlying=underlying,
                            expiration=opt.expiration_date,
                            strike=float(opt.strike_price),
                            right='C' if opt.option_type.value == 'C' else 'P',
                            bid=float(md.bid) if md.bid else 0.0,
                            ask=float(md.ask) if md.ask else 0.0,
                            last=float(md.last) if md.last else None,
                            volume=None,  # Not always available
                            open_interest=None,
                        )
                        quotes.append(quote)
                        
                except Exception as e:
                    logger.warning(f"Error fetching quotes for {underlying} {exp_date}: {e}")
        
        logger.info(f"Retrieved {len(quotes)} option quotes for {underlying}")
        return quotes
    
    def get_option_quote(
        self,
        underlying: str,
        strike: float,
        right: str,
        expiration: date
    ) -> Optional[OptionQuote]:
        """
        Get a single option quote.
        
        Args:
            underlying: Ticker symbol
            strike: Strike price
            right: 'C' for call, 'P' for put
            expiration: Expiration date
        
        Returns:
            OptionQuote or None if not found
        """
        chain = self.get_option_chain(underlying, expiration=expiration)
        
        right = right.upper()[0]
        
        for quote in chain:
            if (abs(quote.strike - strike) < 0.01 and 
                quote.right == right and
                quote.expiration == expiration):
                return quote
        
        return None
    
    def get_chain_for_spread(
        self,
        underlying: str,
        expiration: date,
        long_strike: float,
        short_strike: float,
        right: str = 'C'
    ) -> Dict[str, OptionQuote]:
        """
        Get quotes specifically needed for a vertical spread.
        
        Args:
            underlying: Ticker symbol
            expiration: Expiration date
            long_strike: Strike for long leg
            short_strike: Strike for short leg
            right: 'C' for call spread, 'P' for put spread
        
        Returns:
            Dict with 'long' and 'short' keys mapping to OptionQuotes
        """
        long_quote = self.get_option_quote(underlying, long_strike, right, expiration)
        short_quote = self.get_option_quote(underlying, short_strike, right, expiration)
        
        return {
            'long': long_quote,
            'short': short_quote,
        }
    
    # =========================================================================
    # STREAMING DATA
    # =========================================================================
    
    async def stream_quotes(
        self,
        underlyings: List[str],
        option_symbols: Optional[List[str]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream real-time quotes for underlyings and/or specific option symbols.
        
        This uses TastyTrade's DXLink websocket connection for low-latency data.
        
        Args:
            underlyings: List of underlying symbols to stream
            option_symbols: Optional list of specific option symbols
        
        Yields:
            Dict with quote data as updates arrive
        """
        self._ensure_session()
        
        try:
            from tastytrade.dxfeed import DXLinkStreamer
            
            async with DXLinkStreamer(self._session) as streamer:
                # Subscribe to equity quotes
                if underlyings:
                    await streamer.subscribe_quote(underlyings)
                
                # Subscribe to option quotes
                if option_symbols:
                    await streamer.subscribe_option_quote(option_symbols)
                
                logger.info(f"Streaming quotes for {len(underlyings)} underlyings")
                
                async for quote in streamer.listen():
                    yield {
                        'symbol': quote.symbol,
                        'bid': quote.bid_price,
                        'ask': quote.ask_price,
                        'last': quote.last_price,
                        'timestamp': quote.event_time,
                    }
                    
        except ImportError:
            raise ImportError("DXLink streaming requires tastytrade[dxfeed]: pip install tastytrade[dxfeed]")
    
    # =========================================================================
    # ACCOUNT DATA
    # =========================================================================
    
    def get_balance(self) -> AccountBalance:
        """Get current account balance and buying power."""
        account = self._get_account()
        balances = account.get_balances(self._session)
        
        return AccountBalance(
            account_number=account.account_number,
            cash_balance=float(balances.cash_balance),
            buying_power=float(balances.derivative_buying_power),
            net_liquidating_value=float(balances.net_liquidating_value),
            day_trading_buying_power=float(balances.day_trading_buying_power) if hasattr(balances, 'day_trading_buying_power') else 0.0,
            maintenance_requirement=float(balances.maintenance_requirement),
        )
    
    def get_positions(self) -> List[Position]:
        """Get all open positions."""
        account = self._get_account()
        positions = account.get_positions(self._session)
        
        result = []
        for pos in positions:
            result.append(Position(
                symbol=pos.symbol,
                underlying=pos.underlying_symbol,
                quantity=int(pos.quantity),
                average_cost=float(pos.average_open_price),
                current_price=float(pos.close_price) if pos.close_price else 0.0,
                market_value=float(pos.quantity) * float(pos.close_price or 0) * 100,
                unrealized_pnl=float(pos.realized_day_gain or 0),
            ))
        
        return result
    
    # =========================================================================
    # ORDER SUBMISSION
    # =========================================================================
    
    def submit_vertical_spread(
        self,
        underlying: str,
        expiration: date,
        long_strike: float,
        short_strike: float,
        right: str,
        quantity: int,
        limit_price: float,
        time_in_force: TimeInForce = TimeInForce.DAY,
        dry_run: bool = True
    ) -> Optional[str]:
        """
        Submit a vertical spread order (debit or credit).
        
        For a DEBIT spread (pay premium):
        - Debit call spread: long_strike < short_strike (bull call)
        - Debit put spread: long_strike > short_strike (bear put)
        
        Args:
            underlying: Ticker symbol
            expiration: Option expiration date
            long_strike: Strike for long leg
            short_strike: Strike for short leg
            right: 'C' for call spread, 'P' for put spread
            quantity: Number of spreads
            limit_price: Net debit (positive) or credit (negative) per spread
            time_in_force: Order duration
            dry_run: If True, validate order but don't submit
        
        Returns:
            Order ID if submitted, None if dry_run or failed
        """
        self._ensure_session()
        account = self._get_account()
        
        from tastytrade.instruments import get_option_chain
        from tastytrade.order import NewOrder, OrderTimeInForce, OrderType, OrderAction
        
        # Get the specific options
        chain = get_option_chain(self._session, underlying)
        
        if expiration not in chain:
            raise ValueError(f"Expiration {expiration} not available for {underlying}")
        
        options = chain[expiration]
        
        # Find the specific strikes
        long_option = None
        short_option = None
        
        for opt in options:
            if (abs(float(opt.strike_price) - long_strike) < 0.01 and 
                opt.option_type.value.upper() == right.upper()):
                long_option = opt
            if (abs(float(opt.strike_price) - short_strike) < 0.01 and 
                opt.option_type.value.upper() == right.upper()):
                short_option = opt
        
        if not long_option or not short_option:
            raise ValueError(f"Could not find options for strikes {long_strike}/{short_strike}")
        
        # Build the order
        order = NewOrder(
            time_in_force=OrderTimeInForce.DAY if time_in_force == TimeInForce.DAY else OrderTimeInForce.GTC,
            order_type=OrderType.LIMIT,
            legs=[
                long_option.build_leg(Decimal(quantity), OrderAction.BUY_TO_OPEN),
                short_option.build_leg(Decimal(quantity), OrderAction.SELL_TO_OPEN),
            ],
            price=Decimal(str(limit_price)),
        )
        
        if dry_run:
            # Validate order
            try:
                result = account.place_order(self._session, order, dry_run=True)
                logger.info(f"Order validation successful: {result}")
                return None
            except Exception as e:
                logger.error(f"Order validation failed: {e}")
                raise
        else:
            # Submit order
            result = account.place_order(self._session, order, dry_run=False)
            order_id = result.order.id if hasattr(result, 'order') else str(result)
            logger.info(f"Order submitted: {order_id}")
            return order_id
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.
        
        Args:
            order_id: The order ID to cancel
        
        Returns:
            True if successfully canceled
        """
        account = self._get_account()
        
        try:
            account.cancel_order(self._session, order_id)
            logger.info(f"Order {order_id} canceled")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    # =========================================================================
    # BACKTESTER API
    # =========================================================================
    
    def get_backtest_available_dates(self, underlying: str) -> Dict[str, Any]:
        """
        Get available date ranges for backtesting a specific underlying.
        
        Uses TastyTrade's Backtester API to check what historical data is available.
        
        Args:
            underlying: Ticker symbol
        
        Returns:
            Dict with start_date, end_date, and available expirations
        """
        import requests
        
        self._ensure_session()
        
        url = "https://backtester.vast.tastyworks.com/available-dates"
        
        headers = {
            'Authorization': f'Bearer {self._session.session_token}',
            'Content-Type': 'application/json',
        }
        
        params = {'symbol': underlying}
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get backtest dates for {underlying}: {e}")
            return {}
    
    def simulate_trade(
        self,
        underlying: str,
        entry_date: date,
        exit_date: date,
        strategy_type: str,
        strikes: List[float],
        quantity: int = 1
    ) -> Dict[str, Any]:
        """
        Simulate a historical trade using TastyTrade's Backtester API.
        
        Args:
            underlying: Ticker symbol
            entry_date: Date to enter the trade
            exit_date: Date to exit the trade
            strategy_type: 'VERTICAL', 'SINGLE', etc.
            strikes: List of strikes (one for single leg, two for spreads)
            quantity: Number of contracts
        
        Returns:
            Dict with simulated P&L, Greeks, etc.
        """
        import requests
        
        self._ensure_session()
        
        url = "https://backtester.vast.tastyworks.com/simulate-trade"
        
        headers = {
            'Authorization': f'Bearer {self._session.session_token}',
            'Content-Type': 'application/json',
        }
        
        payload = {
            'symbol': underlying,
            'entryDate': entry_date.isoformat(),
            'exitDate': exit_date.isoformat(),
            'strategyType': strategy_type,
            'strikes': strikes,
            'quantity': quantity,
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to simulate trade: {e}")
            return {}


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_client(
    username: Optional[str] = None,
    password: Optional[str] = None,
    sandbox: bool = False
) -> TastyTradeClient:
    """
    Get a TastyTrade client instance.
    
    This is a convenience function that creates a properly configured client.
    
    Args:
        username: TastyTrade username (or use env var)
        password: TastyTrade password (or use env var)
        sandbox: Use paper trading environment
    
    Returns:
        Configured TastyTradeClient
    """
    return TastyTradeClient(
        username=username,
        password=password,
        sandbox=sandbox
    )


def quick_quote(underlying: str, strike: float, right: str, expiration: str) -> Optional[OptionQuote]:
    """
    Quick function to get a single option quote.
    
    Args:
        underlying: Ticker symbol
        strike: Strike price
        right: 'C' or 'P'
        expiration: Expiration date as YYYY-MM-DD string
    
    Returns:
        OptionQuote or None
    """
    client = get_client()
    exp_date = datetime.strptime(expiration, '%Y-%m-%d').date()
    return client.get_option_quote(underlying, strike, right, exp_date)


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    # Test client initialization (will fail without credentials)
    try:
        client = TastyTradeClient()
        
        # Test option chain fetch
        chain = client.get_option_chain('SPY', max_dte=30)
        print(f"Retrieved {len(chain)} SPY option quotes")
        
        if chain:
            print(f"Sample quote: {chain[0]}")
            
    except ValueError as e:
        print(f"Credentials required: {e}")
    except Exception as e:
        print(f"Error: {e}")
