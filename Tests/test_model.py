from IPython.core import display_functions
from matplotlib import ticker
import pandas as pd
import numpy as np
import math
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from   matplotlib.ticker import FuncFormatter
import statsmodels.api as sm
import pickle


def model(model_type):
    with open("Data_Import/data_cache/SPY_2024-06-24_2026-06-19_minute.pkl", "rb") as f:
        spy_intra_data = pickle.load(f)

    #print(spy_intra_data)
    
    with open("Data_Import/data_cache/SPY_dividends.pkl", "rb") as f:
        dividends = pickle.load(f)
    
    #print(dividends)

    df = pd.DataFrame(spy_intra_data)
    df['day'] = pd.to_datetime(df['caldt']).dt.date  # Extract the date part from the datetime for daily analysis.
    df.set_index('caldt', inplace=True)  # Setting the datetime as the index for easier time series manipulation.
    

    # Group the DataFrame by the 'day' column to facilitate operations that need daily aggregation.
    daily_groups = df.groupby('day') #database of databases now

    # Each day in dataset
    all_days = df['day'].unique()
    

    # Initialize new columns to store calculated metrics, starting with NaN for absence of initial values.
    df['move_open'] = np.nan  # To record the absolute daily change from the open price
    df['vwap'] = np.nan       # To calculate the Volume Weighted Average Price.
    df['spy_dvol'] = np.nan   # To record SPY's daily volatility.

    # Create a series to hold computed daily returns for SPY, initialized with NaN.
    spy_ret = pd.Series(index=all_days, dtype=float)

    # Iterate through each day to calculate metrics.
    for d in range(1, len(all_days)):
        current_day = all_days[d]
        prev_day = all_days[d - 1]

        # Access the data for the current and previous days using their groups.
        current_day_data = daily_groups.get_group(current_day)
        prev_day_data = daily_groups.get_group(prev_day)

        # Calculate the average of high, low, and close prices.
        hlc = (current_day_data['high'] + current_day_data['low'] + current_day_data['close']) / 3

        # Compute volume-weighted metrics for VWAP calculation.
        vol_x_hlc = current_day_data['volume'] * hlc
        cum_vol_x_hlc = vol_x_hlc.cumsum()  # Cumulative sum for VWAP calculation.
        cum_volume = current_day_data['volume'].cumsum() 

        # Assign the calculated VWAP to the new column 'vwap' in the DataFrame.
        # That minute's typical price × that minute's volume, then sum it up, then divide by total volume until current minute.
        df.loc[current_day_data.index, 'vwap'] = cum_vol_x_hlc / cum_volume

        # Calculate the absolute percentage change from the day's opening price.
        open_price = current_day_data['open'].iloc[0]
        df.loc[current_day_data.index, 'move_open'] = (current_day_data['close'] / open_price - 1).abs()

        # Compute the daily return for SPY (no strategy) using the closing prices from the current and previous day.
        spy_ret.loc[current_day] = current_day_data['close'].iloc[-1] / prev_day_data['close'].iloc[-1] - 1

        # Calculate the 15-day rolling volatility, starting calculation after accumulating 15 days of data
        if d > 14:
            df.loc[current_day_data.index, 'spy_dvol'] = spy_ret.iloc[d-15:d-1].std(skipna=False)

    df2=df.copy()

    # Calculate the minutes from market open and determine the minute of the day for each timestamp
    #----------------------------------------- NOTE -----------------------------------------
    # This +1 matters as original backtest uses it to orient its trade indicies
    df['min_from_open'] = ((df.index - df.index.normalize()) / pd.Timedelta(minutes=1)) - (9 * 60 + 30)+1
    df['minute_of_day'] = df['min_from_open'].round().astype(int)

    # Group data by 'minute_of_day' for minute-level calculations.
    minute_groups = df.groupby('minute_of_day')


    # Calculate the mean of the last 14 trading days (today included) of the absolute move from their respective day opens.
    df['move_open_rolling_mean'] = minute_groups['move_open'].transform(lambda x: x.rolling(window=14, min_periods=13).mean())
    print(df['move_open_rolling_mean'])

    # Shift down so becomes last 14 days (today excluded)
    df['sigma_open'] = minute_groups['move_open_rolling_mean'].transform(lambda x: x.shift(1))



    #Org 
    # Calculate the minutes from market open and determine the minute of the day for each timestamp.
    df2['min_from_open'] = ((df2.index - df.index.normalize()) / pd.Timedelta(minutes=1)) - (9 * 60 + 30) + 1 # DIFFERENCE
    df2['minute_of_day'] = df2['min_from_open'].round().astype(int)

    # Group data by 'minute_of_day' for minute-level calculations.
    minute_groups2 = df2.groupby('minute_of_day')

    # Calculate the mean of the last 14 trading days (today included) of the absolute move from their respective day opens.
    df2['move_open_rolling_mean'] = minute_groups2['move_open'].transform(lambda x: x.rolling(window=14, min_periods=13).mean())
    print(df2['move_open_rolling_mean'])

    same = df2["move_open_rolling_mean"].equals(df["move_open_rolling_mean"])
    print(same)
    

    # Shift down so becomes last 14 days (today excluded)
    df2['sigma_open'] = minute_groups2['move_open_rolling_mean'].transform(lambda x: x.shift(1))

    same = df2["sigma_open"].equals(df["sigma_open"])
    print(same)


def main():
    model()
    return 0


if __name__ == "__main__":
    exit(main())


