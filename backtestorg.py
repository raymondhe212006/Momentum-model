import math
import pandas as pd
import numpy as np
import pickle
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from model import model

def main():
    # Constants and settings
    AUM_0 = 100000.0
    commission = 0.0035
    min_comm_per_order = 0.35
    band_mult = 0.7
    band_simplified = 0
    trade_freq = 30
    sizing_type = "vol_target"
    target_vol = 0.02
    max_leverage = 4
    day=20

    # Group data by day for faster access
    df = model()
    all_days = df['day'].unique()

    # Group data by day for faster access
    daily_groups = df.groupby('day')

    # Initialize strategy DataFrame using unique days
    strat = pd.DataFrame(index=all_days)
    strat['ret'] = np.nan
    strat['AUM'] = AUM_0
    strat['ret_spy'] = np.nan

    # Calculate daily returns for SPY using the closing prices
    with open("Data_Import/data_cache/SPY_2024-06-24_2026-06-19_day.pkl", "rb") as f:
        spy_daily_data = pickle.load(f) 
    df_daily = pd.DataFrame(spy_daily_data)
    df_daily['caldt'] = pd.to_datetime(df_daily['caldt']).dt.date
    df_daily.set_index('caldt', inplace=True)  # Set the datetime column as the DataFrame index for easy time series manipulation.

    df_daily['ret'] = df_daily['close'].diff() / df_daily['close'].shift()


    tradelog = pd.DataFrame()
    # Loop through all days, starting from the second day
    for d in range(1, len(all_days)):
        current_day = all_days[d]
        prev_day = all_days[d-1]
        
        prev_day_data = daily_groups.get_group(prev_day)
        current_day_data = daily_groups.get_group(current_day)

        if 'sigma_open' in current_day_data.columns and current_day_data['sigma_open'].isna().all():
            continue

        prev_close_adjusted = prev_day_data['close'].iloc[-1] - df.loc[current_day_data.index, 'dividend'].iloc[-1]

        open_price = current_day_data['open'].iloc[0]
        current_close_prices = current_day_data['close']
        spx_vol = current_day_data['spy_dvol'].iloc[0]
        vwap = current_day_data['vwap']

        sigma_open = current_day_data['sigma_open']
        UB = max(open_price, prev_close_adjusted) * (1 + band_mult * sigma_open)
        LB = min(open_price, prev_close_adjusted) * (1 - band_mult * sigma_open)

        # Determine trading signals
        signals = np.zeros_like(current_close_prices)
        signals[(current_close_prices > UB) & (current_close_prices > vwap)] = 1
        signals[(current_close_prices < LB) & (current_close_prices < vwap)] = -1

        # Position sizing
        previous_aum = strat.loc[prev_day, 'AUM']

        if sizing_type == "vol_target":
            if math.isnan(spx_vol):
                shares = round(previous_aum / open_price * max_leverage)
            else:
                shares = round(previous_aum / open_price * min(target_vol / spx_vol, max_leverage))

        elif sizing_type == "full_notional":
            shares = round(previous_aum / open_price)

        # Apply trading signals at trade frequencies
        trade_indices = np.where(current_day_data["min_from_open"] % trade_freq == 0)[0]
        exposure = np.full(len(current_day_data), np.nan)  # Start with NaNs
        exposure[trade_indices] = signals[trade_indices]  # Apply signals at trade times


        # Custom forward-fill that stops at zeros
        last_valid = np.nan  # Initialize last valid value as NaN
        filled_values = []  # List to hold the forward-filled values
        for value in exposure:
            if not np.isnan(value):  # If current value is not NaN, update last valid value
                last_valid = value
            if last_valid == 0:  # Reset if last valid value is zero
                last_valid = np.nan
            filled_values.append(last_valid)

        exposure = pd.Series(filled_values, index=current_day_data.index).shift(1).fillna(0).values  # Apply shift and fill NaNs

        # Calculate trades count based on changes in exposure
        trades_count = np.sum(np.abs(np.diff(np.append(exposure, 0))))

        # Calculate PnL
        change_1m = current_close_prices.diff()
        gross_pnl = np.sum(exposure * change_1m) * shares
        commission_paid = trades_count * max(min_comm_per_order, commission * shares)
        net_pnl = gross_pnl - commission_paid

        # Update the daily return and new AUM
        strat.loc[current_day, 'AUM'] = previous_aum + net_pnl
        strat.loc[current_day, 'ret'] = net_pnl / previous_aum

        # Save the passive Buy&Hold daily return for SPY
        strat.loc[current_day, 'ret_spy'] = df_daily.loc[df_daily.index == current_day, 'ret'].values[0]
        

    # Results
    final_aum=strat['AUM'].iloc[-1]
    total_ret=(final_aum/AUM_0-1)

    print("Final AUM (Strategy): ", final_aum)
    print("Total Return (Strategy): ", total_ret)

    total_spy_return = (1 + strat['ret_spy'].dropna()).prod() - 1
    total_spy_aum= AUM_0*(1+total_spy_return)

    print("Final AUM (Spy): ", total_spy_aum)
    print("Total Return (Spy): ", total_spy_return)

    # Active trading days only (exclude warmup NaNs)
    strat_rets = strat['ret'].dropna()
    spy_rets   = strat['ret_spy'].dropna()
    aligned    = pd.concat([strat_rets, spy_rets], axis=1).dropna()
    aligned.columns = ['strat', 'spy']

    # Sharpe (annualized, risk-free = 0)
    sharpe = strat_rets.mean() / strat_rets.std() * np.sqrt(252)
    print(f"Sharpe Ratio:  {sharpe:.3f}")

    # Beta vs SPY
    beta = aligned['strat'].cov(aligned['spy']) / aligned['spy'].var()
    print(f"Beta:          {beta:.3f}")

    # Skewness of daily returns
    skew = strat_rets.skew()
    print(f"Skew:          {skew:.3f}")

    # # Tradelog
    # with pd.option_context('display.max_rows', None, 'display.max_columns', None, 'display.width', None):
    #     print(f"day {day} tradelog:\n", tradelog)

    # # Equity curve
    # strat_aum   = strat['AUM']
    # spy_aum     = AUM_0 * (1 + strat['ret_spy'].fillna(0)).cumprod()
    # days        = strat.index

    # fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8),
    #                                gridspec_kw={'height_ratios': [3, 1]})

    # ax1.plot(days, strat_aum.values, label='Strategy', color='steelblue', linewidth=1.5)
    # ax1.plot(days, spy_aum.values,   label='SPY Buy & Hold', color='darkorange',
    #          linestyle='--', linewidth=1.5)
    # ax1.set_title('Equity Curve', fontsize=13)
    # ax1.set_ylabel('AUM ($)')
    # ax1.legend()
    # ax1.grid(True, alpha=0.3)
    # ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    # ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=3))

    # colors = ['steelblue' if r >= 0 else 'tomato' for r in strat_rets.values]
    # ax2.bar(strat_rets.index, strat_rets.values, color=colors, width=1)
    # ax2.axhline(0, color='black', linewidth=0.7)
    # ax2.set_title('Daily Returns', fontsize=11)
    # ax2.set_ylabel('Return')
    # ax2.grid(True, alpha=0.3)
    # ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    # ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))

    # plt.tight_layout()
    # plt.savefig('equity_curve.png', dpi=150, bbox_inches='tight')
    # plt.show()


if __name__ == "__main__":
    exit(main())
