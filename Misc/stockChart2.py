import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import datetime as dt
import mplfinance as mpf

ticker = "SPY"

years = 2
end_date = dt.datetime.now()
start_date = end_date - dt.timedelta(days = 365 * years)

data = yf.download(ticker, start = start_date, end = end_date, auto_adjust=False)
data.columns = data.columns.droplevel(1)

ma_50 = data['Adj Close'].rolling(window=50, min_periods=0).mean()
ma_200 = data['Adj Close'].rolling(window=200, min_periods=0).mean()

'''Below does not use mplfinance to create candlestick
fig, (ax1, ax2) = plt.subplots(2, 1, figsize = (12,8), gridspec_kw= {'height_ratios': [4,1]})

ax1.plot(data.index, data['Adj Close'], label = 'Adjusted Close Price', linewidth = 1)
ax1.plot(data.index, ma_50, label = "50 Day MA", color = 'orange', linewidth = 0.5)
ax1.plot(data.index, ma_20, label = "20 Day MA", color = 'red', linewidth = 0.5)
ax1.set_ylabel('Price', fontsize = 12)
ax1.set_title('SPY Ajusted Close', fontsize = 12, fontweight = 'bold')

color = ['green' if data['Close'].values[i] >= data['Open'].values[i] else 'red' for i in range(len(data))]
ax2.bar(data.index,data['Volume', 'SPY'], color = color)
ax2.set_xlabel('Date', fontsize = 12)

plt.grid(True, alpha = 0.3)
plt.tight_layout()
plt.show()
'''

apds = [
    mpf.make_addplot(ma_50, color='orange', width=0.7, label='50 Day MA'),
    mpf.make_addplot(ma_200, color='red', width=0.7, label='20 Day MA')
]

mpf.plot(data, type='candle', style='charles', volume=True, 
         mav= (50, 200), title=f'{ticker} Candlestick Chart',
         ylabel='Price', ylabel_lower='Volume',
         figsize=(12, 8))