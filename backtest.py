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

        #skip 1st 14 days
        if 'sigma_open' in current_day_data.columns and current_day_data['sigma_open'].isna().all():
            continue
        
        # correct dividend
        prev_close_adjusted = prev_day_data['close'].iloc[-1] - df.loc[current_day_data.index, 'dividend'].iloc[-1]

        open_price = current_day_data['open'].iloc[0] #opening price so first entry
        current_close_prices = current_day_data['close']
        spx_vol = current_day_data['spy_dvol'].iloc[0] #same number every minute so pick first
        vwap = current_day_data['vwap']

        sigma_open = current_day_data['sigma_open']
        UB = max(open_price, prev_close_adjusted) * (1 + band_mult * sigma_open)
        LB = min(open_price, prev_close_adjusted) * (1 - band_mult * sigma_open)

        # Determine trading signals
        signals = np.zeros_like(current_close_prices) #empty array

        prev_signal=0
        for i, idx in enumerate(current_close_prices.index):
            price = current_close_prices.loc[idx]
            ub_val = UB.loc[idx]
            lb_val = LB.loc[idx]
            vwap_val = vwap.loc[idx]
            if i % trade_freq == 0:
                if prev_signal != 0:
                    if prev_signal == 1 and (price < ub_val or price < vwap_val):
                        signals[i] = 0
                        prev_signal = 0
                    elif prev_signal == -1 and (price > lb_val or price > vwap_val):
                        signals[i] = 0
                        prev_signal = 0
                    else:
                        signals[i] = prev_signal
                
                if prev_signal == 0:
                    if price > ub_val:
                        signals[i] = 1
                        prev_signal = 1
                    elif price < lb_val:
                        signals[i] = -1
                        prev_signal = -1
            else:
                signals[i] = prev_signal

        # if d == 200:
        #     print(signals)
        #     mins       = current_day_data['min_from_open'].values
        #     close_vals = current_close_prices.values
        #     ub_vals    = UB.values
        #     lb_vals    = LB.values
        #     vwap_vals  = vwap.values

        #     fig, ax = plt.subplots(figsize=(15, 6))

        #     ax.plot(mins, close_vals, label='Close', color='black',      linewidth=1.2)
        #     ax.plot(mins, ub_vals,    label='UB',    color='green',       linewidth=0.9, linestyle='--')
        #     ax.plot(mins, lb_vals,    label='LB',    color='red',         linewidth=0.9, linestyle='--')
        #     ax.plot(mins, vwap_vals,  label='VWAP',  color='dodgerblue',  linewidth=0.9, linestyle=':')

        #     # Shade held-position regions
        #     ax.fill_between(mins, lb_vals.min() * 0.999, ub_vals.max() * 1.001,
        #                     where=(signals == 1),  alpha=0.12, color='green', label='Long held')
        #     ax.fill_between(mins, lb_vals.min() * 0.999, ub_vals.max() * 1.001,
        #                     where=(signals == -1), alpha=0.12, color='red',   label='Short held')

        #     # Entry / exit markers from transitions in signals
        #     sig_diff = np.diff(signals, prepend=0)
        #     entries_long  = mins[sig_diff == 1]
        #     entries_short = mins[sig_diff == -1]
        #     exits         = mins[(sig_diff != 0) & (signals == 0)]

        #     ax.scatter(entries_long,  close_vals[sig_diff == 1],    marker='^', color='green', s=100, zorder=5, label='Long entry')
        #     ax.scatter(entries_short, close_vals[sig_diff == -1],   marker='v', color='red',   s=100, zorder=5, label='Short entry')
        #     ax.scatter(exits,         close_vals[(sig_diff != 0) & (signals == 0)],
        #                marker='x', color='grey', s=80, zorder=5, label='Exit')

        #     ax.set_title(f'Day {day}  ({current_day})')
        #     ax.set_xlabel('Minutes from open')
        #     ax.set_ylabel('Price ($)')
        #     ax.legend(loc='upper left', fontsize=8)
        #     ax.grid(True, alpha=0.3)
        #     plt.tight_layout()
        #     plt.show()


        # How much money from previous day
        previous_aum = strat.loc[prev_day, 'AUM']
        if sizing_type == "vol_target":
            #first 14 days just use max leverage
            if math.isnan(spx_vol):
                shares = round(previous_aum / open_price * max_leverage)
            else:
                #normal days, more volatile over prev 14 days less shares
                shares = round(previous_aum * min(target_vol / spx_vol, max_leverage) / open_price )
        elif sizing_type == "full_notional":
            #everyday use max leverage
            shares = round(previous_aum / open_price)



        exposure = pd.Series(signals, index=current_day_data.index).shift(1).fillna(0).values  # Apply shift and fill NaNs
        # We can only sell after computation of 30 min interval 

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

        # Trade log
        

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
