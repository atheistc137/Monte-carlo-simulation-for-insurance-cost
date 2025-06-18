Run btc_iv.py to get options data

Use the result to run iv_surface_svi.py, to get smoothened options data using svi

Use that result in liquidation_insurance_mc.py

python liquidation_insurance_mc.py --surface btc_iv_surface_svi.csv --price BTCUSDT_1h.csv --s0 100000 --hedge_ratio 0.8 --debug