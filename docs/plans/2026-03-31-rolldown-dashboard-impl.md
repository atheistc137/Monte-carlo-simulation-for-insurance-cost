# PUT Roll-Down Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a single-file HTML dashboard visualizing three-tier rolldown simulation results with Plotly.js.

**Architecture:** Single HTML file with inline CSS and JS. Three CSV datasets embedded as JS string literals, parsed at load time. Plotly.js loaded from CDN. Tab toggle switches between tiers, re-rendering charts and stats.

**Tech Stack:** HTML5, vanilla JS, Plotly.js (CDN), inline CSS.

**Design doc:** `docs/plans/2026-03-31-rolldown-dashboard-design.md`

---

### Task 1: HTML Scaffold with CSS and Tab Toggle

**Files:**
- Create: `rolldown_dashboard.html`

**Step 1: Create the HTML file with structure and styling**

Write the full HTML skeleton: `<head>` with Plotly CDN, inline `<style>`, page header,
tab buttons, content containers, methodology `<details>`, and the tab-switching JS.

Key elements:
```html
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
```

CSS requirements:
- `max-width: 1200px; margin: 0 auto;` container
- Font: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
- Tab buttons: inline row, active tab has bottom border accent, inactive muted
- Stats card: CSS grid/flexbox row, each stat in a bordered box
- Chart containers: `width: 100%; height: 500px;`
- Color palette: `#1a1a2e` text, `#f8f9fa` background, `#0066cc` accent
- Responsive: stats card wraps on narrow screens

Tab toggle JS:
```javascript
function switchTier(tier) {
  document.querySelectorAll('.tier-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tier-' + tier).style.display = 'block';
  document.querySelector('[data-tier="' + tier + '"]').classList.add('active');
}
```

Page header text:
- Title: "PUT Roll-Down Strategy: Simulation Results"
- Subtitle: "Three tiers of analysis testing whether rolling PUT options recovers the upfront premium cost."

Three tab labels:
- "Historical Backtest" (data-tier="1")
- "Recent Loans" (data-tier="2")
- "Forward Simulation" (data-tier="3")

Each tier content div contains:
- `<p class="tier-desc">` — tier description text (from design doc)
- `<div class="stats-card" id="stats-N">` — stats container
- `<div id="chart-N-1">` — primary chart
- `<div id="chart-N-2">` — secondary chart (Tier 3 only)

**Step 2: Verify scaffold**

Open `rolldown_dashboard.html` in browser. Tabs should toggle visibility.
Charts will be empty. Stats will be empty. Layout should be clean.

**Step 3: Commit**

```bash
git add rolldown_dashboard.html
git commit -m "feat: add rolldown dashboard HTML scaffold with tab toggle"
```

---

### Task 2: Embed CSV Data and Parse

**Files:**
- Modify: `rolldown_dashboard.html`

**Step 1: Read the three CSV files and embed them**

Read these files:
- `result/rolldown_tier1_daily_20260331.csv`
- `result/rolldown_tier2_daily_20260331.csv`
- `result/rolldown_tier3_1000paths_20260331.csv`

Embed each as a JS template literal:
```javascript
const TIER1_CSV = `start_date,spot,initial_premium,...
2023-03-31,28465.36,2505.14,...
...`;
```

**Step 2: Write the CSV parser**

```javascript
function parseCSV(csvText) {
  const lines = csvText.trim().split('\n');
  const headers = lines[0].split(',');
  return lines.slice(1).map(line => {
    const vals = line.split(',');
    const row = {};
    headers.forEach((h, i) => {
      row[h] = h === 'start_date' ? vals[i] : parseFloat(vals[i]);
    });
    return row;
  });
}

const tier1 = parseCSV(TIER1_CSV);
const tier2 = parseCSV(TIER2_CSV);
const tier3 = parseCSV(TIER3_CSV);
```

**Step 3: Verify**

Add `console.log(tier1.length, tier2.length, tier3.length)` temporarily.
Open in browser, check console: should print `731 366 1000`.

**Step 4: Commit**

```bash
git add rolldown_dashboard.html
git commit -m "feat: embed CSV data and add parser"
```

---

### Task 3: Summary Stats Computation and Rendering

**Files:**
- Modify: `rolldown_dashboard.html`

**Step 1: Write stats computation function**

```javascript
function computeStats(data) {
  const n = data.length;
  const sorted_delta = data.map(r => r.full_economic_delta).sort((a, b) => a - b);
  const sorted_pct = data.map(r => r.full_economic_delta / r.initial_premium * 100)
                         .sort((a, b) => a - b);
  const percentile = (arr, p) => arr[Math.floor(arr.length * p / 100)];

  return {
    count: n,
    avgPremium: data.reduce((s, r) => s + r.initial_premium, 0) / n,
    medianRecoveryPct: percentile(sorted_pct, 50),
    medianDelta: percentile(sorted_delta, 50),
    pctPositive: data.filter(r => r.full_economic_delta > 0).length / n * 100,
    avgRolls: data.reduce((s, r) => s + r.num_rolls, 0) / n,
    p5: percentile(sorted_delta, 5),
    p95: percentile(sorted_delta, 95),
  };
}
```

**Step 2: Write stats rendering function**

```javascript
function renderStats(containerId, stats, isTier3) {
  const fmt = (v, dec=0) => v.toLocaleString('en-US', {
    minimumFractionDigits: dec, maximumFractionDigits: dec
  });

  let html = `
    <div class="stat"><span class="stat-label">${isTier3 ? 'Paths' : 'Loans'}</span>
      <span class="stat-value">${stats.count}</span></div>
    <div class="stat"><span class="stat-label">Avg Premium</span>
      <span class="stat-value">$${fmt(stats.avgPremium)}</span></div>
    <div class="stat"><span class="stat-label">Median Recovery</span>
      <span class="stat-value">${fmt(stats.medianRecoveryPct, 1)}%</span></div>
    <div class="stat"><span class="stat-label">Median Delta</span>
      <span class="stat-value">$${fmt(stats.medianDelta)}</span></div>
    <div class="stat"><span class="stat-label">Delta > 0</span>
      <span class="stat-value">${fmt(stats.pctPositive, 1)}%</span></div>
    <div class="stat"><span class="stat-label">Avg Rolls</span>
      <span class="stat-value">${fmt(stats.avgRolls, 1)}</span></div>
  `;
  if (isTier3) {
    html += `
      <div class="stat"><span class="stat-label">P5 / P95</span>
        <span class="stat-value">$${fmt(stats.p5)} / $${fmt(stats.p95)}</span></div>
    `;
  }
  document.getElementById(containerId).innerHTML = html;
}
```

**Step 3: Call renderStats for all three tiers on page load**

```javascript
const stats1 = computeStats(tier1);
const stats2 = computeStats(tier2);
const stats3 = computeStats(tier3);
renderStats('stats-1', stats1, false);
renderStats('stats-2', stats2, false);
renderStats('stats-3', stats3, true);
```

**Step 4: Verify**

Open in browser. Each tier tab should show a row of stat boxes with real numbers.
Check Tier 1 median recovery is in the 40-60% range. Tier 3 should show P5/P95.

**Step 5: Commit**

```bash
git add rolldown_dashboard.html
git commit -m "feat: add summary stats cards for all tiers"
```

---

### Task 4: Tier 1 & 2 Time-Series Charts

**Files:**
- Modify: `rolldown_dashboard.html`

**Step 1: Write the time-series chart function**

```javascript
function renderTimeSeries(divId, data, title) {
  const dates = data.map(r => r.start_date);
  const recoveryPct = data.map(r => r.full_economic_delta / r.initial_premium * 100);
  const spots = data.map(r => r.spot);
  const hoverText = data.map(r =>
    `Date: ${r.start_date}<br>` +
    `Entry Spot: $${r.spot.toLocaleString()}<br>` +
    `Premium: $${r.initial_premium.toLocaleString()}<br>` +
    `Roll Savings: $${r.roll_savings.toLocaleString()}<br>` +
    `Terminal Delta: $${r.terminal_delta.toLocaleString()}<br>` +
    `Full Econ Delta: $${r.full_economic_delta.toLocaleString()}<br>` +
    `Recovery: ${(r.full_economic_delta / r.initial_premium * 100).toFixed(1)}%`
  );

  const trace1 = {
    x: dates, y: recoveryPct,
    type: 'scatter', mode: 'markers',
    name: '% of Premium Recovered',
    marker: { size: 5, color: '#0066cc', opacity: 0.6 },
    text: hoverText, hoverinfo: 'text',
    yaxis: 'y1',
  };

  const trace2 = {
    x: dates, y: spots,
    type: 'scatter', mode: 'lines',
    name: 'BTC Spot Price',
    line: { color: '#cccccc', width: 1.5 },
    yaxis: 'y2',
    hoverinfo: 'skip',
  };

  // Breakeven reference line
  const trace3 = {
    x: [dates[0], dates[dates.length - 1]], y: [0, 0],
    type: 'scatter', mode: 'lines',
    line: { color: '#999', width: 1, dash: 'dash' },
    showlegend: false, hoverinfo: 'skip',
    yaxis: 'y1',
  };

  const layout = {
    title: { text: title, font: { size: 16 } },
    xaxis: { title: 'Loan Start Date' },
    yaxis: {
      title: '% of Premium Recovered',
      zeroline: false,
    },
    yaxis2: {
      title: 'BTC Spot ($)',
      overlaying: 'y', side: 'right',
      showgrid: false,
      tickformat: '$,.0f',
    },
    legend: { x: 0, y: 1.12, orientation: 'h' },
    margin: { t: 60, b: 50, l: 60, r: 60 },
    hovermode: 'closest',
    plot_bgcolor: '#fafafa',
    paper_bgcolor: '#ffffff',
  };

  Plotly.newPlot(divId, [trace2, trace3, trace1], layout,
    { responsive: true, displayModeBar: false });
}
```

**Step 2: Call for Tier 1 and Tier 2**

```javascript
renderTimeSeries('chart-1-1', tier1, 'Historical Backtest — Premium Recovery by Start Date');
renderTimeSeries('chart-2-1', tier2, 'Recent Loans — Premium Recovery by Start Date');
```

**Step 3: Verify**

Open in browser. Tier 1 tab: scatter of recovery % from 2023-2025, light BTC price
line rising from ~$28k to ~$87k. Tier 2: scatter from 2025-2026, BTC declining.
Hover over points shows tooltip with all fields.

**Step 4: Commit**

```bash
git add rolldown_dashboard.html
git commit -m "feat: add time-series charts for Tier 1 and Tier 2"
```

---

### Task 5: Tier 3 Histogram with Percentile Markers

**Files:**
- Modify: `rolldown_dashboard.html`

**Step 1: Write the histogram function**

```javascript
function renderHistogram(divId, data) {
  const deltas = data.map(r => r.full_economic_delta);
  const positive = deltas.filter(d => d >= 0);
  const negative = deltas.filter(d => d < 0);

  const tracePos = {
    x: positive, type: 'histogram',
    xbins: { size: 500 },
    marker: { color: 'rgba(0, 153, 76, 0.7)' },
    name: 'Positive (strategy helped)',
  };
  const traceNeg = {
    x: negative, type: 'histogram',
    xbins: { size: 500 },
    marker: { color: 'rgba(204, 51, 51, 0.7)' },
    name: 'Negative (strategy hurt)',
  };

  // Percentile lines
  const sorted = [...deltas].sort((a, b) => a - b);
  const pctl = (p) => sorted[Math.floor(sorted.length * p / 100)];
  const pctiles = [
    { p: 5,  v: pctl(5) },
    { p: 25, v: pctl(25) },
    { p: 50, v: pctl(50) },
    { p: 75, v: pctl(75) },
    { p: 95, v: pctl(95) },
  ];

  const shapes = pctiles.map(({ v }) => ({
    type: 'line', x0: v, x1: v, y0: 0, y1: 1, yref: 'paper',
    line: { color: '#333', width: 1.5, dash: 'dash' },
  }));

  const annotations = pctiles.map(({ p, v }) => ({
    x: v, y: 1.02, yref: 'paper', xanchor: 'center',
    text: `P${p}: $${v.toLocaleString('en-US', { maximumFractionDigits: 0 })}`,
    showarrow: false, font: { size: 10, color: '#333' },
  }));

  const layout = {
    title: { text: 'Distribution of Full Economic Delta', font: { size: 16 } },
    xaxis: { title: 'Full Economic Delta ($)', tickformat: '$,.0f' },
    yaxis: { title: 'Count' },
    barmode: 'stack',
    shapes, annotations,
    margin: { t: 80, b: 50, l: 60, r: 40 },
    plot_bgcolor: '#fafafa',
    paper_bgcolor: '#ffffff',
    legend: { x: 0, y: 1.12, orientation: 'h' },
  };

  Plotly.newPlot(divId, [traceNeg, tracePos], layout,
    { responsive: true, displayModeBar: false });
}
```

**Step 2: Call it**

```javascript
renderHistogram('chart-3-1', tier3);
```

**Step 3: Verify**

Open browser, Tier 3 tab. Histogram shows distribution with green/red split.
Five percentile markers with labels. Mass should be concentrated in the
$1k-$4k range with a left tail into negative territory.

**Step 4: Commit**

```bash
git add rolldown_dashboard.html
git commit -m "feat: add Tier 3 histogram with percentile markers"
```

---

### Task 6: Tier 3 Scatter (final_spot vs full_economic_delta)

**Files:**
- Modify: `rolldown_dashboard.html`

**Step 1: Write the scatter function**

```javascript
function renderScatter(divId, data) {
  const hoverText = data.map(r =>
    `Final Spot: $${r.final_spot.toLocaleString()}<br>` +
    `Full Econ Delta: $${r.full_economic_delta.toLocaleString()}<br>` +
    `Roll Savings: $${r.roll_savings.toLocaleString()}<br>` +
    `Terminal Delta: $${r.terminal_delta.toLocaleString()}<br>` +
    `Rolls: ${r.num_rolls}`
  );

  const trace = {
    x: data.map(r => r.final_spot),
    y: data.map(r => r.full_economic_delta),
    type: 'scatter', mode: 'markers',
    marker: {
      size: 5, opacity: 0.5,
      color: data.map(r => r.full_economic_delta),
      colorscale: [[0, 'rgba(204,51,51,0.7)'], [0.5, '#eee'], [1, 'rgba(0,153,76,0.7)']],
      cmin: -5000, cmax: 5000,
      showscale: true,
      colorbar: { title: 'Delta ($)', tickformat: '$,.0f' },
    },
    text: hoverText, hoverinfo: 'text',
  };

  // Breakeven line
  const refLine = {
    x: [Math.min(...data.map(r => r.final_spot)),
        Math.max(...data.map(r => r.final_spot))],
    y: [0, 0],
    type: 'scatter', mode: 'lines',
    line: { color: '#999', width: 1, dash: 'dash' },
    showlegend: false, hoverinfo: 'skip',
  };

  const layout = {
    title: { text: 'Final BTC Price vs Economic Delta', font: { size: 16 } },
    xaxis: { title: 'Final BTC Spot Price ($)', tickformat: '$,.0f' },
    yaxis: { title: 'Full Economic Delta ($)', tickformat: '$,.0f' },
    margin: { t: 60, b: 50, l: 70, r: 40 },
    hovermode: 'closest',
    plot_bgcolor: '#fafafa',
    paper_bgcolor: '#ffffff',
    showlegend: false,
  };

  Plotly.newPlot(divId, [refLine, trace], layout,
    { responsive: true, displayModeBar: false });
}
```

**Step 2: Call it**

```javascript
renderScatter('chart-3-2', tier3);
```

**Step 3: Verify**

Open browser, Tier 3 tab, scroll to second chart. Scatter should show:
- High final_spot (>$80k) → positive delta (green, clustered $1k-$5k)
- Low final_spot (<$40k) → negative delta (red, down to -$20k)
- Clear visual: strategy breaks even around ~$45-50k final spot

**Step 4: Commit**

```bash
git add rolldown_dashboard.html
git commit -m "feat: add Tier 3 scatter chart (final spot vs economic delta)"
```

---

### Task 7: Methodology Note and Final Polish

**Files:**
- Modify: `rolldown_dashboard.html`

**Step 1: Write methodology content**

Add to the `<details>` at page bottom:

```html
<details>
  <summary>Methodology</summary>
  <div class="methodology">
    <h4>Strategy</h4>
    <p>Each BTC-collateralized loan is hedged with a 12-month PUT option struck at
    the initial debt level. As monthly payments reduce the outstanding debt, the
    existing PUT (with a now-too-high strike) can be sold and replaced with a cheaper
    PUT at the lower strike. The difference is captured as roll savings. A roll is
    only executed when the profit exceeds $200.</p>

    <h4>Full Economic Delta</h4>
    <p>Roll savings alone overstate the benefit. Rolling to a lower strike means less
    protection if BTC crashes. The <em>full economic delta</em> accounts for this:
    it equals cumulative roll savings plus the terminal payoff difference between
    rolling and static strategies. It can be negative — meaning the strategy cost
    more than holding the original PUT.</p>

    <h4>Simulation Tiers</h4>
    <p><strong>Tier 1</strong> uses only actual historical BTC prices and IV surface
    data — no simulation whatsoever. <strong>Tier 2</strong> uses real data up to
    today, then extends each loan with 1,000 GBM-simulated price paths (calibrated
    from historical returns). Each start date shows the average across paths.
    <strong>Tier 3</strong> generates 1,000 independent GBM paths from today's spot
    price — each is a complete 12-month simulation.</p>

    <h4>Parameters</h4>
    <p>LTV: 70% · Loan tenor: 12 months · Rate: 10% · Monthly amortisation ·
    Option tenors: 3/6/9/12 months · Min roll profit: $200 ·
    IV source: SVI-calibrated surface from Deribit options</p>
  </div>
</details>
```

**Step 2: Final CSS polish**

- Ensure methodology text is styled: `max-width: 700px`, comfortable line height
- Check tab descriptions match design doc text exactly
- Verify Tier 1 loads by default on page open
- Check all charts render without JS errors in console

**Step 3: Commit**

```bash
git add rolldown_dashboard.html
git commit -m "feat: add methodology note and final polish to rolldown dashboard"
```

---

### Task 8: Deferred Chart Rendering for Hidden Tabs

**Files:**
- Modify: `rolldown_dashboard.html`

**Step 1: Fix Plotly hidden-tab rendering issue**

Plotly charts rendered in `display: none` divs have zero dimensions. Fix by
deferring chart rendering until a tab is first shown:

```javascript
const rendered = { 1: false, 2: false, 3: false };

function switchTier(tier) {
  document.querySelectorAll('.tier-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tier-' + tier).style.display = 'block';
  document.querySelector('[data-tier="' + tier + '"]').classList.add('active');

  if (!rendered[tier]) {
    renderTier(tier);
    rendered[tier] = true;
  }
}

function renderTier(tier) {
  if (tier === 1) {
    renderStats('stats-1', computeStats(tier1), false);
    renderTimeSeries('chart-1-1', tier1, 'Historical Backtest — Premium Recovery by Start Date');
  } else if (tier === 2) {
    renderStats('stats-2', computeStats(tier2), false);
    renderTimeSeries('chart-2-1', tier2, 'Recent Loans — Premium Recovery by Start Date');
  } else {
    renderStats('stats-3', computeStats(tier3), true);
    renderHistogram('chart-3-1', tier3);
    renderScatter('chart-3-2', tier3);
  }
}

// Render Tier 1 on page load
switchTier(1);
```

**Step 2: Verify**

Open browser. Switch between all three tabs. Each should render correctly
on first visit and stay rendered. No blank charts, no console errors.

**Step 3: Commit**

```bash
git add rolldown_dashboard.html
git commit -m "fix: defer chart rendering to fix hidden-tab sizing"
```
