import math
import pandas as pd
import numpy as np
import pickle
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from model import model
import os
from dotenv import load_dotenv
load_dotenv()
MODE = int(os.getenv("MODE"))
MODEL_MODE = int(os.getenv("MODEL_MODE"))

def main():
    # Constants and settings
    AUM_0 = 100000.0
    commission = 0.0035
    min_comm_per_order = 0.35
    band_mult = 1
    band_simplified = 0
    trade_freq = 30
    sizing_type = "vol_target"
    target_vol = 0.02
    max_leverage = 4
    day=200

    # Group data by day for faster access
    df = model(MODEL_MODE)
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


    # Loop through all days, starting from the second day
    for d in range(1, len(all_days)):
        current_day = all_days[d]
        prev_day = all_days[d-1]
        prev_day_data = daily_groups.get_group(prev_day)
        current_day_data = daily_groups.get_group(current_day)

        # Added Sanity Check
        if not(prev_day in daily_groups.groups and current_day in daily_groups.groups):
            continue

        #skip 1st 14 days
        if 'sigma_open' in current_day_data.columns and current_day_data['sigma_open'].isna().all():
            continue
        
        # correct dividend
        prev_close_adjusted = prev_day_data['close'].iloc[-1] - df.loc[current_day_data.index, 'dividend'].iloc[-1]

        open_price = current_day_data['open'].iloc[0] # opening price so first entry
        current_close_prices = current_day_data['close']
        spx_vol = current_day_data['spy_dvol'].iloc[0] #same number every minute so pick first
        vwap = current_day_data['vwap']

        sigma_open = current_day_data['sigma_open']
        UB = max(open_price, prev_close_adjusted) * (1 + band_mult * sigma_open)
        LB = min(open_price, prev_close_adjusted) * (1 - band_mult * sigma_open)


        signals = np.zeros_like(current_close_prices) #empty array

        # Determine trading signals ORG VERSION
        if MODE == 0:
            prev_signal=0
            for i, idx in enumerate(current_close_prices.index):
                price = current_close_prices.loc[idx]
                ub_val = UB.loc[idx]
                lb_val = LB.loc[idx]
                vwap_val = vwap.loc[idx]
                if (i+1) % trade_freq == 0: # Trade logic in Original can't trade on very beginning of the day and checks on the day before 30 minute interval to trade on the actual interval
                    if prev_signal == 0:
                        if price > ub_val and price > vwap_val:
                            signals[i] = 1
                            prev_signal = 1
                        elif price < lb_val and price < vwap_val:
                            signals[i] = -1
                            prev_signal = -1
                        else:
                            signals[i]=0
                    elif prev_signal == 1 and (price < ub_val or price < vwap_val):
                        signals[i] = 0
                        prev_signal = 0
                        if price < lb_val:
                            signals[i] = -1
                            prev_signal = -1
                    elif prev_signal == -1 and (price > lb_val or price > vwap_val):
                        signals[i] = 0
                        prev_signal = 0
                        if price > ub_val:
                            signals[i] = 1
                            prev_signal = 1
                    else:
                        signals[i] = prev_signal
                else:
                    signals[i] = prev_signal
        
        # Determine trading signals IMPL version (differ in entering condition)
        if MODE == 1 or MODE == 2: 
            prev_signal=0
            for i, idx in enumerate(current_close_prices.index):
                price = current_close_prices.loc[idx]
                ub_val = UB.loc[idx]
                lb_val = LB.loc[idx]
                vwap_val = vwap.loc[idx]
                # Trade logic in Original can't trade on very beginning of the day and checks on the day before 30 minute interval to trade on the actual interval
                # Mode = 2 for check on 30 min interval and allow 1st day
                if MODE == 1:
                    trade_index= i+1
                if MODE == 2: 
                    trade_index= i

                if trade_index % trade_freq == 0: # for mode=2 only: add "and i != 0" to avoid checking/trading on first minute
                    if prev_signal == 0:
                        if price > ub_val:
                            signals[i] = 1
                            prev_signal = 1
                        elif price < lb_val:
                            signals[i] = -1
                            prev_signal = -1
                        else:
                            signals[i]=0
                    elif prev_signal == 1 and (price < ub_val or price < vwap_val):
                        signals[i] = 0
                        prev_signal = 0
                        if price < lb_val:
                            signals[i] = -1
                            prev_signal = -1
                    elif prev_signal == -1 and (price > lb_val or price > vwap_val):
                        signals[i] = 0
                        prev_signal = 0
                        if price > ub_val:
                            signals[i] = 1
                            prev_signal = 1
                    else:
                        signals[i] = prev_signal
                else:
                    signals[i] = prev_signal
        

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

        # Apply shift to avoid see ahead bias
        exposure = pd.Series(signals, index=current_day_data.index).shift(1).fillna(0).values  
        
        # Always exit position at market close
        exposure[-1]=0

        # Calculate trades count based on changes in exposure
        trades_count=0
        for i in range(1,len(exposure)):
            if exposure[i-1] != exposure[i]:
                if exposure[i-1] != 0 and exposure[i] !=0: # need two trades for selling a long then buying a short on same minute
                    trades_count+=1
                trades_count += 1

        # Calculate PnL
        # --------------------------------------------- NOTICE ---------------------------------------------
        # UNCOMMENT IF YOU WANT TO TRADE STRAIGHT AWAY (NO DELAY) and match ORIGINAL MODEL
        # This induces look ahead bias? since machine takes time to calculate signals so we should only trade minute after
        if MODE == 0:
            exposure = pd.Series(signals, index=current_day_data.index).shift(0).fillna(0).values 

        # --------------------------------------------- NOTICE ---------------------------------------------
        prev_hold=0
        enter=0
        gross_pnl=0.0
        for i in range(len(exposure)):
            if exposure[i] != prev_hold or i == len(exposure)-1: # for setting change purposes namely commenting exposure[-1]=0
                if prev_hold != 0:
                    #sigma open involves the close price of current min so we must take action next minute
                    gross_pnl += (current_close_prices.iloc[i] - enter) * shares * prev_hold
                if exposure[i]!=0:
                    enter=current_close_prices.iloc[i]
                else:
                    enter=0
                prev_hold = exposure[i]

        commission_paid = trades_count * max(min_comm_per_order, commission * shares)
        net_pnl = gross_pnl - commission_paid

        # Update the daily return and new AUM
        strat.loc[current_day, 'AUM'] = previous_aum + net_pnl
        strat.loc[current_day, 'ret'] = net_pnl / previous_aum

        # Save the passive Buy&Hold daily return for SPY
        strat.loc[current_day, 'ret_spy'] = df_daily.loc[df_daily.index == current_day, 'ret'].values[0]

        if d == day:
            # print(exposure)
            mins       = current_day_data["min_from_open"].values
            close_vals = current_close_prices.values
            fig, ax = plt.subplots(figsize=(12, 5))

            # price lines
            ax.plot(mins, close_vals,     label='Close', color='steelblue', linewidth=1.5)
            ax.plot(mins, UB.values,      label='UB',    color='green',  linestyle='--', linewidth=1)
            ax.plot(mins, LB.values,      label='LB',    color='red',    linestyle='--', linewidth=1)
            ax.plot(mins, vwap.values,    label='VWAP',  color='orange', linestyle='-.',  linewidth=0.9)

            # shade long / short holding periods
            y_lo = min(LB.values.min(), close_vals.min()) * 0.999
            y_hi = max(UB.values.max(), close_vals.max()) * 1.001
            ax.fill_between(mins, y_lo, y_hi, where=(exposure == 1),  alpha=0.10, color='green', label='Long')
            ax.fill_between(mins, y_lo, y_hi, where=(exposure == -1), alpha=0.10, color='red',   label='Short')

            # entry / exit markers
            exp_diff      = np.diff(exposure, prepend=0)
            long_entries  = np.where((exp_diff != 0) & (exposure == 1))[0]
            short_entries = np.where((exp_diff != 0) & (exposure == -1))[0]
            exits         = np.where((exp_diff != 0) & (exposure == 0))[0]
            if len(long_entries):
                ax.scatter(mins[long_entries],  current_close_prices.iloc[long_entries],
                            color='green', marker='^', s=100, zorder=5, label='Long entry')
            if len(short_entries):
                ax.scatter(mins[short_entries], current_close_prices.iloc[short_entries],
                            color='red',   marker='v', s=100, zorder=5, label='Short entry')
            if len(exits):
                ax.scatter(mins[exits],         current_close_prices.iloc[exits],
                            color='black', marker='x', s=80,  zorder=5, label='Exit')

            # 30-min checkpoint verticals
            for x in range(30, len(current_day_data), 30):
                ax.axvline(x=x, color='gray', linestyle=':', linewidth=1.2)

            ax.set_title(f'Day {current_day} — Close, UB, LB, VWAP')
            ax.set_xlabel('Minutes from Open')
            ax.set_ylabel('Price ($)')
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            #plt.show()


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

    # Equity curve
    strat_aum   = strat['AUM']
    spy_aum     = AUM_0 * (1 + strat['ret_spy'].fillna(0)).cumprod()
    days        = strat.index

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8),
                                   gridspec_kw={'height_ratios': [3, 1]})

    ax1.plot(days, strat_aum.values, label='Strategy', color='steelblue', linewidth=1.5)
    ax1.plot(days, spy_aum.values,   label='SPY Buy & Hold', color='darkorange',
             linestyle='--', linewidth=1.5)
    ax1.set_title('Equity Curve', fontsize=13)
    ax1.set_ylabel('AUM ($)')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=3))

    colors = ['steelblue' if r >= 0 else 'tomato' for r in strat_rets.values]
    ax2.bar(strat_rets.index, strat_rets.values, color=colors, width=1)
    ax2.axhline(0, color='black', linewidth=0.7)
    ax2.set_title('Daily Returns', fontsize=11)
    ax2.set_ylabel('Return')
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))

    plt.tight_layout()
    plt.savefig('equity_curve.png', dpi=150, bbox_inches='tight')
    #plt.show()


if __name__ == "__main__":
    exit(main())
