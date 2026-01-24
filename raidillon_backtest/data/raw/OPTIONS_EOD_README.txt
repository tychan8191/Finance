
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
# Tickers needed: 
# Date range: 2024-10-01 to 2026-02-28
