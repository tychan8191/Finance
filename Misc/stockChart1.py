import datetime as dt
import matplotlib.pyplot as plt
from matplotlib import style
import pandas as pd
import pandas_datareader.data as web
import yfinance as yf
import mplfinance as mpf
import matplotlib.dates as mdates

style.use('ggplot')

#start = dt.datetime(2000, 1, 1)
#end = dt.datetime.now()
#df= yf.download('TSLA', start = start, end = end, auto_adjust=False)
#df.to_csv('c:/Users/Ty/Documents/GitHub/finance/tsla.csv')

savepath = 'c:/Users/Ty/Documents/GitHub/finance/tsla.csv'

df = pd.read_csv(savepath, index_col = 0, parse_dates=True, header = [0,1])

#df['100ma'] = df['Adj Close'].rolling(window = 100, min_periods = 0).mean()
print(type(df['Close']))
#mpf.plot(df, type='candle', style='charles',title='  ', ylabel='  ',ylabel_lower='  ',figratio=(25,10),figscale=1,mav=50, volume=True)

#ax1 = plt.subplot2grid((6,1), (0,0), rowspan = 5, colspan = 1)
#ax2 = plt.subplot2grid((6,1), (5,0), rowspan = 1, colspan = 1, sharex = ax1)

'''
ax1.plot(df.index, df['Adj Close'])
ax1.plot(df.index, df['100ma'])
ax2.bar(df.index, df['Volume', 'TSLA'])
'''

plt.show()