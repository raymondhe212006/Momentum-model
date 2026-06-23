# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the model

```bash
# Run the backtest
python backtest.py

# Refresh market data from Polygon.io (requires valid API key in .env)
cd Data_Import && python data_import.py
```

## Architecture

This is a single-instrument (SPY) intraday momentum strategy with three layers:

**`Data_Import/data_import.py`** — Data acquisition  
Fetches minute-bar and daily OHLCV data plus dividends from Polygon.io, caches everything as pickle files in `Data_Import/data_cache/`. Uses `POLYGON_API_KEY` from `.env`. Note: `BASE_URL` is currently set to `api.massive.com` — the real endpoint is `api.polygon.io`.

**`model.py`** — Feature engineering  
Loads the cached pickle files and computes derived features on the minute DataFrame:
- `vwap`: cumulative intraday VWAP per minute
- `move_open`: absolute % move from the day's open at each minute
- `sigma_open`: 14-trading-day rolling mean of `move_open` at the same minute of day (shifted so today is excluded) — used as the volatility band width
- `spy_dvol`: 15-day rolling std of daily returns — used for position sizing
- Merges dividend data so dividend ex-dates can adjust the prior close

**`backtest.py`** — Simulation  
Iterates day by day, applies the band-breakout strategy, and tracks AUM. Key parameters at the top of `main()`:

| Parameter | Default | Meaning |
|---|---|---|
| `band_mult` | 1 | Multiplier on `sigma_open` for UB/LB width |
| `trade_freq` | 30 | Minutes between signal evaluations |
| `sizing_type` | `"vol_target"` | `"vol_target"` or `"full_notional"` |
| `target_vol` | 0.02 | Daily vol target for position sizing |
| `max_leverage` | 4 | Cap on leverage multiple |
| `commission` | 0.0035 | Per-share commission rate |

Signal logic: at each `trade_freq`-minute interval, go long if price > UB **and** price > VWAP; go short if price < LB **and** price < VWAP; otherwise flat. Positions are forward-filled between check intervals and shifted by one minute (no look-ahead). PnL is computed per minute against the exposure array.

## Data flow

```
Polygon.io API
    → data_import.py
    → Data_Import/data_cache/*.pkl
    → model.py (feature engineering)
    → backtest.py (simulation + PnL)
```

The `.pkl` files contain raw lists of dicts with keys: `volume`, `open`, `high`, `low`, `close`, `caldt`. The `caldt` field is a naive Eastern-time datetime.

## Dependencies

Standard scientific Python stack: `pandas`, `numpy`, `matplotlib`, `statsmodels`, `requests`, `pytz`, `python-dotenv`. No `requirements.txt` exists yet; install manually or via conda/pip.
