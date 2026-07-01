import math
import pandas as pd
import numpy as np
import pickle
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model import model
from dotenv import load_dotenv
load_dotenv()
# 0 for original, 1 for impl
MODE = int(os.getenv("MODE"))
# MODE = 0 to match original with impl logic
# MODE = 1 for different enter strategy and potential look ahead fix
# MODE = 2 for different enter strategy and potential look ahead fix, and different checking strategy (check every 30 days, buy after 1 min, allow 1st min check/trade)
# MODE 0 and 1 check min before every 30 min interval to trade on the interval 
MODEL_MODE = int(os.getenv("MODEL_MODE"))
# Verify Enter and Exit Logic: TEST_MODE = 0
# Verify trade count same as org: TEST_MODE = 1
# Verify Pnl Calculation same as Org (ONLY THE SAME IF WE DO NOT SHIFT): TEST_MODE = 2
TEST_MODE = int(os.getenv("TEST_MODE"))


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
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(project_root, 'Data_Import', 'data_cache')
    with open(f"{data_dir}/SPY_2024-06-24_2026-06-19_day.pkl", "rb") as f:
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



        if TEST_MODE == 0:
            # ORIGINAL VERSION Determine trading signals
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



            #IMPLEMENTATION VERSION Determine trading signals
            signals_impl = np.zeros_like(current_close_prices) #empty array
            prev_signal=0
            for i, idx in enumerate(current_close_prices.index):
                price = current_close_prices.loc[idx]
                ub_val = UB.loc[idx]
                lb_val = LB.loc[idx]
                vwap_val = vwap.loc[idx]
                if (i+1) % trade_freq == 0:
                    if prev_signal == 0:
                        if price > ub_val and price > vwap_val:
                            signals_impl[i] = 1
                            prev_signal = 1
                        elif price < lb_val and price < vwap_val:
                            signals_impl[i] = -1
                            prev_signal = -1
                        else:
                            signals_impl[i]=0
                    elif prev_signal == 1 and (price < ub_val or price < vwap_val):
                        signals_impl[i] = 0
                        prev_signal = 0
                        if price < lb_val:
                            signals_impl[i] = -1
                            prev_signal = -1
                    elif prev_signal == -1 and (price > lb_val or price > vwap_val):
                        signals_impl[i] = 0
                        prev_signal = 0
                        if price > ub_val:
                            signals_impl[i] = 1
                            prev_signal = 1
                    else:
                        signals_impl[i] = prev_signal
                else:
                    signals_impl[i] = prev_signal



            # CHECK Exposure equal?
            exposure_org = pd.Series(filled_values, index=current_day_data.index).shift(1).fillna(0).values 
            exposure_impl = pd.Series(signals_impl, index=current_day_data.index).shift(1).fillna(0).values
            if not np.array_equal(exposure_org, exposure_impl):
                print(d)
                print(exposure_org)
                print(exposure_impl)



            # USE IMPLEMENTATION FOR RESULTS
            exposure = exposure_impl
        else:
            # ORIGINAL VERSION Determine trading signals
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

            
            exposure = pd.Series(filled_values, index=current_day_data.index).shift(1).fillna(0).values 



        
        if TEST_MODE == 1:
            # ORIGINAL Calculate trades count based on changes in exposure
            trades_count_org = np.sum(np.abs(np.diff(np.append(exposure, 0))))



            # IMPLEMENTATION Calculate trades count based on changes in exposure
            exposure_impl = pd.Series(filled_values, index=current_day_data.index).shift(1).fillna(0).values
            exposure_impl[-1]=0
            trades_count_impl=0
            for i in range(1,len(exposure_impl)):
                if exposure_impl[i-1] != exposure_impl[i]:
                    if exposure_impl[i-1] != 0 and exposure_impl[i] !=0: # need two trades for selling a long then buying a short on same minute
                        trades_count_impl+=1
                    trades_count_impl += 1



            # CHECK trade count same?
            if(trades_count_impl != trades_count_org):
                print(d)
                print(exposure)
                print(trades_count_impl)
                print(trades_count_org)
            

            # USE implementation for results
            trades_count = trades_count_impl
        else:
            # Calculate trades count based on changes in exposure
            trades_count = np.sum(np.abs(np.diff(np.append(exposure, 0))))

        

        if TEST_MODE ==3:
            # ORIGINAL Calculate PnL
            change_1m = current_close_prices.diff()
            gross_pnl_org = np.sum(exposure * change_1m) * shares



            # IMPLEMENTATION Calculate PnL
            # ----------------------------------------------------------NOTICE NO SHIFT----------------------------------------------------------
            exposure_impl = pd.Series(filled_values, index=current_day_data.index).shift(0).fillna(0).values  # NO SHIFT
            prev_hold=0
            enter=0
            gross_pnl_impl=0.0
            for i in range(len(exposure_impl)):
                if exposure_impl[i] != prev_hold or i == len(exposure_impl)-1: # for setting change purposes namely commenting exposure[-1]=0
                    if prev_hold != 0:
                        #sigma open involves the close price of current min so we must take action next minute
                        gross_pnl_impl += (current_close_prices.iloc[i] - enter) * shares * prev_hold
                    if exposure_impl[i]!=0:
                        enter=current_close_prices.iloc[i]
                    else:
                        enter=0
                    prev_hold = exposure_impl[i]
            


            # CHECK same as org? floats so very small difference
            if not(np.isclose(gross_pnl_impl, gross_pnl_org)):
                print(d)
                print(gross_pnl_impl)
                print(gross_pnl_org)
            
            

            # USE implementation for res
            gross_pnl = gross_pnl_impl
        else:
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
    total_ret_test = total_ret

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


if __name__ == "__main__":
    exit(main())
