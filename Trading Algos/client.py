class TradingClient:
    def __init__(self, api_key, host):
        pass

    def on_delta(self, func):
        return func

    def on_fill(self, func):
        return func

    async def buy(self, security_id, price, quantity):
        print(f"[MOCK] BUY {quantity} of {security_id} @ {price}")
        return 1

    async def sell(self, security_id, price, quantity):
        print(f"[MOCK] SELL {quantity} of {security_id} @ {price}")
        return 2

    async def cancel(self, order_id):
        print(f"[MOCK] CANCEL {order_id}")

    def run(self):
        print("[MOCK] Client running")