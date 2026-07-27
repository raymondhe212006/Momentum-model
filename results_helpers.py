import numpy as np
import pandas as pd

def max_drawdown_from_aum(aum):
    running_peak = aum.cummax()
    drawdown = aum / running_peak - 1
    return drawdown.min()


def report_leg(aum_0, name, df, spy_rets, aum_col="AUM", ret_col="ret"):
    rets = df[ret_col].dropna()

    aligned = pd.concat([rets, spy_rets], axis=1).dropna()
    aligned.columns = ["leg", "spy"]

    final_aum = df[aum_col].iloc[-1]
    total_return = final_aum / aum_0 - 1

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

def analyze_short_overlay(
    strat,
    strat_short,
    overlay_ratios,
    initial_aum,
    max_drawdown_func,
    print_results=True,
):
    """
    Analyze SPY combined with different short-overlay ratios.

    Returns
    -------
    overlay_results : pd.DataFrame
        Raw numeric results.

    overlay_display : pd.DataFrame
        Formatted results for display.
    """

    # Build aligned SPY and short-leg return data
    overlay = pd.concat(
        [
            strat["ret_spy"],
            strat_short["ret"],
        ],
        axis=1,
    ).dropna()

    overlay.columns = ["SPY", "Short Overlay"]

    # Worst 10 SPY days
    worst_days = overlay["SPY"].nsmallest(10).index
    spy_worst_avg = overlay.loc[worst_days, "SPY"].mean()

    # Calm days: middle 80% of SPY daily returns
    low = overlay["SPY"].quantile(0.10)
    high = overlay["SPY"].quantile(0.90)
    calm_mask = overlay["SPY"].between(low, high)

    def report_return_stream(name, rets, spy_rets):
        aligned = pd.concat([rets, spy_rets], axis=1).dropna()
        aligned.columns = ["portfolio", "spy"]

        portfolio = aligned["portfolio"]
        spy = aligned["spy"]

        aum = initial_aum * (1 + portfolio).cumprod()

        portfolio_std = portfolio.std()
        spy_var = spy.var()

        return {
            "Portfolio": name,
            "Total Return": aum.iloc[-1] / initial_aum - 1,
            "Sharpe": (
                portfolio.mean() / portfolio_std * np.sqrt(252)
                if portfolio_std != 0
                else np.nan
            ),
            "Beta": (
                portfolio.cov(spy) / spy_var
                if spy_var != 0
                else np.nan
            ),
            "Skew": portfolio.skew(),
            "Max Drawdown": max_drawdown_func(aum),
        }

    rows = []

    for overlay_ratio in overlay_ratios:
        combo_rets = (
            overlay["SPY"]
            + overlay_ratio * overlay["Short Overlay"]
        )

        metrics = report_return_stream(
            name=f"SPY + {overlay_ratio}x Short Overlay",
            rets=combo_rets,
            spy_rets=overlay["SPY"],
        )

        combo_worst_avg = combo_rets.loc[worst_days].mean()

        calm_drag = (
            overlay_ratio
            * overlay.loc[calm_mask, "Short Overlay"].mean()
        )

        rows.append({
            **metrics,
            "Overlay Ratio": overlay_ratio,
            "Gross Exposure": 1 + overlay_ratio,
            "Worst 10 Avg Return": combo_worst_avg,
            "Worst 10 Improvement": combo_worst_avg - spy_worst_avg,
            "Calm Period Drag": calm_drag,
        })

    overlay_results = pd.DataFrame(rows)

    # Use the 0.0x overlay row as the baseline
    baseline_rows = overlay_results[
        overlay_results["Overlay Ratio"] == 0
    ]

    if baseline_rows.empty:
        raise ValueError(
            "overlay_ratios must include 0 so baseline metrics can be calculated."
        )

    baseline_beta = baseline_rows["Beta"].iloc[0]
    baseline_dd = baseline_rows["Max Drawdown"].iloc[0]

    overlay_results["Beta Reduction"] = (
        baseline_beta - overlay_results["Beta"]
    )

    overlay_results["Drawdown Relief"] = (
        overlay_results["Max Drawdown"] - baseline_dd
    )

    overlay_results["Beta Reduction per 1.0x"] = np.where(
        overlay_results["Overlay Ratio"] > 0,
        overlay_results["Beta Reduction"]
        / overlay_results["Overlay Ratio"],
        np.nan,
    )

    overlay_results["DD Relief per 1.0x"] = np.where(
        overlay_results["Overlay Ratio"] > 0,
        overlay_results["Drawdown Relief"]
        / overlay_results["Overlay Ratio"],
        np.nan,
    )

    # Format output
    overlay_display = overlay_results.copy()

    percent_cols = [
        "Total Return",
        "Max Drawdown",
        "Worst 10 Avg Return",
        "Worst 10 Improvement",
        "Calm Period Drag",
        "Drawdown Relief",
        "DD Relief per 1.0x",
    ]

    for col in percent_cols:
        overlay_display[col] = overlay_display[col].map(
            lambda x: "" if pd.isna(x) else f"{x:.2%}"
        )

    decimal_cols = [
        "Sharpe",
        "Beta",
        "Skew",
        "Gross Exposure",
        "Beta Reduction",
        "Beta Reduction per 1.0x",
    ]

    for col in decimal_cols:
        overlay_display[col] = overlay_display[col].map(
            lambda x: "" if pd.isna(x) else f"{x:.3f}"
        )

    overlay_display = overlay_display.drop(
        columns=["Overlay Ratio", "Gross Exposure"]
    )

    overlay_display = overlay_display.rename(columns={
        "Total Return": "Return",
        "Max Drawdown": "Max DD",
        "Worst 10 Avg Return": "Worst 10 Avg",
        "Worst 10 Improvement": "Worst 10 Help",
        "Calm Period Drag": "Calm Drag",
        "Beta Reduction": "Beta Red.",
        "Drawdown Relief": "DD Relief",
        "Beta Reduction per 1.0x": "Beta Red./x",
        "DD Relief per 1.0x": "DD Relief/x",
    })

    if print_results:
        print(overlay_display.to_string(index=False))

    return overlay_results, overlay_display