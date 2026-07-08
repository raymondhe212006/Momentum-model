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
# 0 for original, 1 for impl
MODE = int(os.getenv("MODE"))
# MODE = 0 to match original with impl logic
# MODE = 1 for different enter strategy and potential look ahead fix
# MODE = 2 for different enter strategy and potential look ahead fix, and different checking strategy (check every 30 days, buy after 1 min, allow 1st min check/trade)
# MODE 0 and 1 check min before every 30 min interval to trade on the interval 
MODEL_MODE = int(os.getenv("MODEL_MODE"))

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


def max_drawdown_from_aum(aum):
    running_peak = aum.cummax()
    drawdown = aum / running_peak - 1
    return drawdown.min()


def report_leg(name, df, spy_rets, aum_col="AUM", ret_col="ret"):
    rets = df[ret_col].dropna()
    
    aligned = pd.concat([rets, spy_rets], axis=1).dropna()
    aligned.columns = ["leg", "spy"]

    final_aum = df[aum_col].iloc[-1]
    total_return = final_aum / AUM_0 - 1

    sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() != 0 else np.nan
    beta = aligned["leg"].cov(aligned["spy"]) / aligned["spy"].var()
    skew = rets.skew()
    max_dd = max_drawdown_from_aum(df[aum_col].dropna())

    return {
        "Leg": name,
        "Final AUM": final_aum,
        "Total Return": total_return,
        "Sharpe": sharpe,
        "Beta": beta,
        "Skew": skew,
        "Max Drawdown": max_dd,
    }


def report_return_stream(name, rets, spy_rets):
    aligned = pd.concat([rets, spy_rets], axis=1).dropna()
    aligned.columns = ["portfolio", "spy"]

    aum = AUM_0 * (1 + rets.fillna(0)).cumprod()

    return {
        "Portfolio": name,
        "Total Return": aum.iloc[-1] / AUM_0 - 1,
        "Sharpe": rets.mean() / rets.std() * np.sqrt(252),
        "Beta": aligned["portfolio"].cov(aligned["spy"]) / aligned["spy"].var(),
        "Skew": rets.skew(),
        "Max Drawdown": max_drawdown_from_aum(aum),
    }

def main():
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

    # Initialize long vs short DataFrames
    strat_long = pd.DataFrame(index=all_days)
    strat_long['ret'] = np.nan
    strat_long['AUM'] = AUM_0

    strat_short= pd.DataFrame(index=all_days)
    strat_short['ret'] = np.nan
    strat_short['AUM'] = AUM_0

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
        # Does not affect shares
        previous_aum_long = strat_long.loc[prev_day, 'AUM']
        previous_aum_short = strat_short.loc[prev_day, 'AUM']
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
        if MODE == 0 or MODE == 1 or MODE == 2:
            exposure = pd.Series(signals, index=current_day_data.index).shift(0).fillna(0).values 

        # --------------------------------------------- NOTICE ---------------------------------------------
        prev_hold=0
        enter=0
        gross_pnl=0.0
        gross_pnl_long=0.0
        trades_count_long = 0
        gross_pnl_short=0.0 
        trades_count_short = 0
        for i in range(len(exposure)):
            if exposure[i] != prev_hold or i == len(exposure)-1: # for setting change purposes namely commenting exposure[-1]=0
                if prev_hold != 0:
                    #sigma open involves the close price of current min so we must take action next minute
                    gross_pnl += (current_close_prices.iloc[i] - enter) * shares * prev_hold
                    if prev_hold == 1:
                        gross_pnl_long += (current_close_prices.iloc[i] - enter) * shares * prev_hold
                        trades_count_long+=2
                    if prev_hold == -1:
                        gross_pnl_short += (current_close_prices.iloc[i] - enter) * shares * prev_hold
                        trades_count_short+=2
                if exposure[i]!=0:
                    enter=current_close_prices.iloc[i]
                else:
                    enter=0
                prev_hold = exposure[i]

        # sanity checks
        if not(np.isclose(gross_pnl_long+gross_pnl_short,gross_pnl)):
            print("uneven gross pnl");
            print(gross_pnl_long+gross_pnl_short)
            print(gross_pnl)
        if trades_count_long+trades_count_short != trades_count:
            print("uneven trade count");
            print(trades_count_long+trades_count_short)
            print(trades_count)

        # Calculate net
        commission_paid = trades_count * max(min_comm_per_order, commission * shares)
        net_pnl = gross_pnl - commission_paid

        commission_paid_long = trades_count_long * max(min_comm_per_order, commission * shares)
        net_pnl_long = gross_pnl_long - commission_paid_long

        commission_paid_short = trades_count_short * max(min_comm_per_order, commission * shares)
        net_pnl_short = gross_pnl_short - commission_paid_short

        # sanity checks
        if not(np.isclose(commission_paid_long + commission_paid_short, commission_paid)):
            print("uneven commission")
            print(commission_paid_long+commission_paid_short)
            print(commission_paid)

        if not(np.isclose(net_pnl_long + net_pnl_short, net_pnl)):
            print("uneven net pnl")
            print(net_pnl_long+net_pnl_short)
            print(net_pnl)

        # Update the daily return and new AUM

        strat.loc[current_day, 'AUM'] = previous_aum + net_pnl
        strat.loc[current_day, 'ret'] = net_pnl / previous_aum

        strat_long.loc[current_day, 'AUM'] = previous_aum_long + net_pnl_long
        strat_long.loc[current_day, 'ret'] = net_pnl_long / previous_aum

        strat_short.loc[current_day, 'AUM'] = previous_aum_short + net_pnl_short
        strat_short.loc[current_day, 'ret'] = net_pnl_short / previous_aum

        if not(np.isclose(strat_long.loc[current_day, 'AUM']+strat_short.loc[current_day, 'AUM']-AUM_0, strat.loc[current_day, 'AUM'])):
            print("uneven aum")
            print(strat_long.loc[current_day, 'AUM']+strat_short.loc[current_day, 'AUM']-AUM_0)
            print(strat.loc[current_day, 'AUM'])

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
    spy_rets = strat["ret_spy"].dropna()

    results = pd.DataFrame([
        report_leg("Combined", strat, spy_rets),
        report_leg("Long Leg", strat_long, spy_rets),
        report_leg("Short Leg", strat_short, spy_rets),
    ])

    print(results.to_string(index=False))

    long_leg_aum=results.loc[results["Leg"] == "Long Leg", "Final AUM"].iloc[0]
    short_leg_aum=results.loc[results["Leg"] == "Short Leg", "Final AUM"].iloc[0]
    combined_aum=results.loc[results["Leg"] == "Combined", "Final AUM"].iloc[0]

    if np.isclose(long_leg_aum+short_leg_aum-AUM_0, combined_aum):
        print("Pass")

    
    # Worse ten days
    print("\nWorse 10 SPY days\n")
    stress = pd.concat([
        strat["ret_spy"],
        strat["ret"],
        strat_long["ret"],
        strat_short["ret"],
    ], axis=1).dropna()

    stress.columns = ["SPY", "Combined", "Long Leg", "Short Leg"]

    worst_10_spy_days = stress.sort_values("SPY").head(10)

    print(worst_10_spy_days)

    print("\nWorst 10 SPY days average:")
    print(worst_10_spy_days.mean())
    print("\nShort leg hit rate during worst 10 SPY days:")
    print((worst_10_spy_days["Short Leg"] > 0).mean())

    
    print("\nShort Overlay\n")
    overlay = pd.concat([
        strat["ret_spy"],
        strat_short["ret"],
    ], axis=1).dropna()

    overlay.columns = ["SPY", "Short Overlay"]
    overlay["SPY + Short Overlay"] = overlay["SPY"] + overlay["Short Overlay"]

    overlay_spy_aum = AUM_0 * (1 + overlay["SPY"]).cumprod()
    overlay_combo_aum = AUM_0 * (1 + overlay["SPY + Short Overlay"]).cumprod()

    overlay_results = pd.DataFrame([
        report_return_stream("SPY Long Book", overlay["SPY"], overlay["SPY"]),
        report_return_stream("SPY + Short Overlay", overlay["SPY + Short Overlay"], overlay["SPY"]),
    ])

    overlay_display = overlay_results.copy()

    overlay_display["Total Return"] = overlay_display["Total Return"].map(lambda x: f"{x:.2%}")
    overlay_display["Sharpe"] = overlay_display["Sharpe"].map(lambda x: f"{x:.3f}")
    overlay_display["Beta"] = overlay_display["Beta"].map(lambda x: f"{x:.3f}")
    overlay_display["Skew"] = overlay_display["Skew"].map(lambda x: f"{x:.3f}")
    overlay_display["Max Drawdown"] = overlay_display["Max Drawdown"].map(lambda x: f"{x:.2%}")

    print(overlay_display.to_string(index=False))


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

    strat_rets = strat['ret'].dropna()
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
