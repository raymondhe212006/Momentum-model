# SPY Intraday Momentum Strategy

A single-instrument (SPY) intraday momentum backtest built on minute-bar data from Polygon.io. The strategy enters long or short positions when price breaks out of a volatility band around the day's open and confirms via VWAP.

## Overview

The strategy computes upper and lower bands around each day's open price using a rolling intraday volatility estimate (`sigma_open`). At each 30-minute check interval, it enters long if price is above the upper band and above VWAP, short if price is below the lower band and below VWAP, and otherwise stays flat. Position sizing scales to a daily volatility target. Execution cost is modeled with a square-root market impact function.

## Quick Start

```bash
# Run the backtest and print performance metrics + equity curve
python backtest.py

# Refresh market data from Polygon.io (requires POLYGON_API_KEY in .env)
cd Data_Import && python data_import.py
```

## Environment Variables

Create a `.env` file in the project root:

```
POLYGON_API_KEY=your_key_here
MODEL_MODE=0          # 0 = original vol calc, 1 = revised
MODE=0                # 0 = original signal timing, 1 = revised entry, 2 = revised entry + check on interval
IMPACT=True           # True = square-root market impact, False = flat slippage only
ONLY_SLIPPAGE=False   # True = skip market impact term
NEXT_OPEN=False       # True = execute at next-bar open
```

## Project Structure

```
backtest.py          — Main simulation loop; computes signals, PnL, and AUM
model.py             — Feature engineering (VWAP, sigma_open, spy_dvol, ADV)
results.py           — Reporting: equity curve, Sharpe, beta, drawdown, short overlay sweep
results_helpers.py   — Helper functions for leg reporting and overlay analysis
Data_Import/
  data_import.py     — Fetches minute and daily OHLCV + dividends from Polygon.io
  data_cache/        — Cached pickle files (not committed)
Tests/               — Validation scripts
```

## Architecture

### Data Flow

```
Polygon.io API → data_import.py → data_cache/*.pkl → model.py → backtest.py
```

Pickle files contain lists of dicts with keys `volume`, `open`, `high`, `low`, `close`, `caldt` (naive Eastern-time datetime).

### Feature Engineering (`model.py`)

| Feature | Description |
|---|---|
| `vwap` | Cumulative intraday VWAP per minute (HLC/3 × volume) |
| `move_open` | Absolute % move from the day's open at each minute |
| `sigma_open` | 14-day rolling mean of `move_open` at the same minute of day, shifted to exclude today — used as band half-width |
| `spy_dvol` | 15-day rolling std of daily close-to-close returns — used for position sizing |
| `adv` | 14-day rolling average daily share volume — used in market impact model |
| `impact_sigma` | 14-day rolling daily return std — used in market impact model |

Dividend data is merged so ex-date adjustments correct the prior close used for band calculation.

### Signal Logic (`backtest.py`)

Bands are set around `max(open, prev_close_adj)` for the upper bound and `min(open, prev_close_adj)` for the lower bound:

```
UB = reference_price × (1 + band_mult × sigma_open)
LB = reference_price × (1 - band_mult × sigma_open)
```

At each `trade_freq`-minute interval:
- **Enter long** if price > UB and price > VWAP
- **Enter short** if price < LB and price < VWAP
- **Exit** if price crosses back through the band or VWAP
- Signals are shifted one minute before computing PnL (no look-ahead)

Three signal modes are available via the `MODE` env var, differing in when the interval check falls and what conditions trigger entry.

### Position Sizing

With `sizing_type = "vol_target"`, position size targets a daily vol of `target_vol`:

```
shares = (AUM × target_vol) / (spy_dvol × price)
```

Leverage is capped at `max_leverage`.

### Execution Cost Model

When `IMPACT=True`, each trade incurs:

```
cost_rate = slippage_rate + 0.7 × (sigma / sqrt(390)) × sqrt(|shares| / ADV)
```

The square-root term is the Almgren-Chriss market impact formula scaled to per-minute volume.

### Key Parameters

| Parameter | Default | Description |
|---|---|---|
| `AUM_0` | 100,000 | Starting capital |
| `band_mult` | 1 | Multiplier on `sigma_open` for band width |
| `trade_freq` | 30 | Minutes between signal evaluations |
| `sizing_type` | `"vol_target"` | `"vol_target"` or `"full_notional"` |
| `target_vol` | 0.02 | Daily vol target |
| `max_leverage` | 4 | Leverage cap |
| `commission` | 0.0035 | Per-share commission |
| `slippage_rate` | 0.0001 | Flat slippage rate (bps floor for impact model) |

## Output

Running `python results.py` prints a performance table for the combined strategy, long leg, and short leg (Total Return, Sharpe, Beta, Skew, Max Drawdown), plus a short overlay sweep showing how adding the short leg at various ratios (0–1×) affects a SPY buy-and-hold portfolio. An equity curve is saved to `equity_curve.png`.

## Dependencies

```
pandas  numpy  matplotlib  statsmodels  requests  pytz  python-dotenv
```

No `requirements.txt` exists yet. Install via pip or conda.
