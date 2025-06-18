# Monte Carlo Simulation for Insurance Cost

This project implements a Monte Carlo simulation for calculating insurance costs using Bitcoin options data.

## Setup and Usage

1. First, run `btc_iv.py` to fetch options data
2. Use the result to run `iv_surface_svi.py` to get smoothened options data using SVI (Stochastic Volatility Inspired) model
3. Finally, run the Monte Carlo simulation using `liquidation_insurance_mc.py`

### Example Command

```bash
python liquidation_insurance_mc.py --surface btc_iv_surface_svi.csv --price BTCUSDT_1h.csv --s0 100000 --hedge_ratio 0.8 --debug
```

## Files Description

- `btc_iv.py`: Fetches Bitcoin options data
- `iv_surface_svi.py`: Implements SVI model for volatility surface smoothing
- `liquidation_insurance_mc.py`: Main Monte Carlo simulation for insurance cost calculation
- `BTCUSDT_1h.csv`: Historical price data
- `btc_iv_surface_svi.csv`: Processed volatility surface data 