# OI Liquidity Snapshot Tool — Design

## Problem

When Bitmor needs to liquidate loans, it must sell held PUT options on Deribit. The question is: on any given day, how much open interest exists at the relevant strikes for long-dated BTC PUTs, and what fraction would Bitmor consume at various portfolio sizes?

## Approach

A single Python script (`oi_snapshot.py`) that fetches live Deribit OI data, filters for long-dated BTC PUTs at hedge-relevant strikes, and outputs an absorption analysis.

## Data Source

- **Deribit public API** (free, no auth required)
- Endpoint: `GET https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option`
- Returns all active BTC options with `open_interest` (in BTC), instrument name (encodes strike, expiry, type), and `mark_price`

## Pipeline

1. **Fetch** all active BTC option book summaries from Deribit
2. **Parse** instrument names to extract strike, expiry date, and option type (P/C)
   - Deribit naming: `BTC-{DDMMMYY}-{STRIKE}-{P|C}` (e.g., `BTC-27JUN25-60000-P`)
3. **Filter** to PUTs with time-to-expiry >= 90 days
4. **Fetch** current BTC spot from `get_index_price` endpoint
5. **Bucket** by moneyness (strike / spot):
   - 40–50% of spot
   - 50–60% of spot
   - 60–70% of spot (primary hedge zone)
   - 70–80% of spot (primary hedge zone)
   - 80–90% of spot
   - 90–100% of spot
6. **Aggregate** OI per bucket (BTC and USD)
7. **Calculate absorption** at portfolio sizes: 100, 500, 1,000, 5,000 loans (1 BTC notional each)
8. **Print** summary table to console
9. **Save** bar chart of OI by strike bucket to `results/oi_snapshot.png`

## Output

### Console table (example)

```
Deribit BTC PUT Open Interest — Long-Dated (>=90 days)
Spot: $84,500 | Date: 2026-04-06

Strike Range    | OI (BTC)  | OI (USD)      | # Instruments
40-50% of spot  |   1,200   |  $101,400,000  |      8
50-60% of spot  |   3,400   |  $287,300,000  |     12
60-70% of spot  |   5,800   |  $490,100,000  |     15
70-80% of spot  |   4,200   |  $354,900,000  |     11
80-90% of spot  |   2,100   |  $177,450,000  |      9
90-100% of spot |   1,500   |  $126,750,000  |      7
─────────────────────────────────────────────────────────
TOTAL           |  18,200   | $1,537,900,000 |     62

Hedge Zone (60-80%): 10,000 BTC / $845,000,000

Absorption Analysis (1 BTC per loan, hedge zone 60-80%):
  100 loans  →   1.0% of hedge-zone OI
  500 loans  →   5.0% of hedge-zone OI
 1000 loans  →  10.0% of hedge-zone OI
 5000 loans  →  50.0% of hedge-zone OI
```

### Chart

Bar chart with moneyness buckets on x-axis, OI in BTC on y-axis. Hedge zone (60-80%) highlighted.

## Dependencies

- `requests` — HTTP calls to Deribit API
- `matplotlib` — bar chart (already used in project)
- `datetime` — expiry parsing

## Key Assumptions

- 1 BTC notional per loan (matches simulation)
- "Long-dated" = >= 90 days to expiry (matches hedge tenor of 3–12 months)
- Strike relevance defined by moneyness relative to current spot
- OI is a floor on liquidity — actual executable volume is higher due to market makers quoting beyond OI, and Deribit RFQ for block trades
