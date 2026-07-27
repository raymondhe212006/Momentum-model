from backtest import backtest, AUM_0, slippage_rate
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from results_helpers import report_leg, max_drawdown_from_aum, analyze_short_overlay


def main():
    (strat, strat_long, strat_short) = backtest(AUM_0, slippage_rate, display=True)

    # Results
    spy_rets = strat["ret_spy"].dropna()
    results = pd.DataFrame([
        report_leg(AUM_0, "Combined", strat, spy_rets),
        report_leg(AUM_0, "Long Leg", strat_long, spy_rets),
        report_leg(AUM_0, "Short Leg", strat_short, spy_rets),
    ])

    print(results.to_string(index=False))

    long_leg_aum=results.loc[results["Leg"] == "Long Leg", "Final AUM"].iloc[0]
    short_leg_aum=results.loc[results["Leg"] == "Short Leg", "Final AUM"].iloc[0]
    combined_aum=results.loc[results["Leg"] == "Combined", "Final AUM"].iloc[0]

    if np.isclose(long_leg_aum+short_leg_aum-AUM_0, combined_aum):
        print("Pass")

    # Worse ten days
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


    overlay_ratios = [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]
    overlay_results, overlay_display = analyze_short_overlay(
        strat=strat,
        strat_short=strat_short,
        overlay_ratios=overlay_ratios,
        initial_aum=AUM_0,
        max_drawdown_func=max_drawdown_from_aum,
    )

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
