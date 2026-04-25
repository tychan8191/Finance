import asyncio
import numpy as np
from client import TradingClient

API_KEY = ""
HOST = "wss://<host>/ws"

client = TradingClient(api_key=API_KEY, host=HOST)

#-------------------setup state-------------------------

books = {}
price_hist = {}
my_orders = {}
my_positions = {}
BALANCE = 10000

#-------------------parameters------------------------

WINDOW              = 15 #calculation window
VOL_THRESHOLD       = 0.003  #volatility check
MOMENTUM_THRESHOLD  = 0.002  #signal limits
REVERSE_THRESHOLD   = 0.002  #signal limits
TRADE_OFFSET        = 1  #midprice trade price for limit order
MAX_RISK            = 0.15 #max percentage to allocate on single signal
MAX_POSITION_PCT    = 0.2 #max percentage of total portfolio allocated to one fx
CHURN_PRICE         = 1 #avoid replacing orders if price moves slightly only

#--------------------signal function--------------------

def get_signal(secid: int):
    if len(price_hist[secid]) < WINDOW:
        return 0, 0.0, None

    calc_window = np.array(price_hist[secid][-WINDOW:], dtype=float)
    returns = np.diff(np.log(calc_window))

    volatility = np.std(returns)
    total_change = np.log(calc_window[-1] / calc_window[0])

    #logic
    if volatility>= VOL_THRESHOLD: 
        if abs(total_change) >= MOMENTUM_THRESHOLD:
            strength = min(abs(total_change) / (MOMENTUM_THRESHOLD * 3), 1.0)
            return int(np.sign(total_change)), strength, "momentum"
    else:
        deviation = np.log(calc_window[-1] / np.mean(calc_window))
        if abs(deviation) >= REVERSE_THRESHOLD:
            strength = min(abs(deviation) / (REVERSE_THRESHOLD * 3), 1.0)
            return int(-1 * np.sign(deviation)), strength, "reversion"
    
    return 0, 0.0, None

#------------help functions--------------

def add_sec(secid: int):
    books[secid] = {"bids": {}, "asks": {}}
    price_hist[secid] = []
    my_orders[secid] = None

def calc_qty(signal: int, strength: float, price: int, secid: int):
    if BALANCE is None:
        return 0
    
    target_dollars  = min(BALANCE * MAX_RISK * strength, BALANCE * MAX_POSITION_PCT)
    current_dollars = my_positions.get(secid, 0) * price
    delta_dollars   = target_dollars - (current_dollars if signal == 1 else -current_dollars)
    return max(int(delta_dollars / price), 0)

def best_bid_ask(secid: int):
    bids = books[secid]["bids"]
    asks = books[secid]["asks"]
    return (max(bids.keys()) if bids else None, min(asks.keys()) if asks else None)
    
#------------callbacks------------------------

@client.on_delta
async def handle_delta(delta):
    secid = delta.security_id
    
    if secid not in books:
        add_sec(secid)

    for price, qty in delta.bids:
        if qty == 0:
            books[secid]["bids"].pop(price, None)
        else:
            books[secid]["bids"][price] = qty
    for price, qty in delta.asks:
        if qty == 0:
            books[secid]["asks"].pop(price, None)
        else:
            books[secid]["asks"][price] = qty

    if delta.midprice:
        price_hist[secid].append(delta.midprice)

    #--------buy/sell logic----

    signal, strength, state = get_signal(secid)
    bid, ask = best_bid_ask(secid)

    if signal == 0 or bid is None or ask is None:
        return

    
    price = ask - TRADE_OFFSET if signal == 1 else bid + TRADE_OFFSET

    qty = calc_qty(signal, strength, price, secid)

    if qty == 0:
        return


    existing = my_orders[secid]
    if existing and existing["signal"] == signal:
        if abs(existing["price"] - price) <= CHURN_PRICE_TOL:
            return
 
    if existing:
        try:
            await client.cancel(existing["order_id"])
        except Exception:
            pass
        my_orders[secid] = None

    

    try:
        if signal == 1:
            order_id = await client.buy(security_id = secid, price = price, quantity = qty)
            print(f"Security {secid}: BUY  {qty} @ ${price}, {state}")
        elif signal == -1:
            order_id = await client.sell(security_id = secid, price = price, quantity = qty)
            print(f"Security {secid}: SELL {qty} @ ${price}, {state}")
 
        my_orders[secid] = {"order_id": order_id, 
                            "signal": signal, 
                            "quantity": qty, 
                            "price": price}
        
    except Exception as e:
        if hasattr(e, 'wait_ms'):                                                    
            await asyncio.sleep(e.wait_ms / 1000)

@client.on_fill
async def handle_fill(state):
    global BALANCE, my_positions
    BALANCE = state.balance
    my_positions = state.positions
    print(f"Balance: {BALANCE}")
    print(f"Positions: {positions}")

client.run()