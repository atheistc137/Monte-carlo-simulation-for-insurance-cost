# Bitmor Combined Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `bitmor-dashboard.html` — a single self-contained HTML file combining the math explainer and rolldown dashboard into 3 tabs.

**Architecture:** Component-oriented single HTML file with 4 JS modules (DataStore, Nav, Tab1Controller, Tab2Controller/Tab3Controller). Plotly.js for all charts. CSV data embedded inline. Lazy tab rendering.

**Tech Stack:** HTML/CSS/JS, Plotly.js 2.35.2, Deribit/Coinbase/Binance REST APIs, embedded CSV data

**Design doc:** `docs/plans/2026-03-31-bitmor-combined-dashboard-design.md`

**Source files to reference:**
- `bitmor-math-explainer.html` (1,125 lines) — Sections 1-2 HTML + all JS
- `rolldown_dashboard.html` (2,775 lines) — CSV data, chart rendering, methodology HTML, CSS

---

### Task 1: HTML Shell + CSS + Tab Navigation

**Files:**
- Create: `bitmor-dashboard.html`

**Step 1: Create the file with full CSS and tab skeleton**

Build the HTML document with:
- `<head>`: charset, viewport, title "Bitmor — Dashboard", Google Fonts link (Bricolage Grotesque + IBM Plex Mono), Plotly.js CDN script
- CSS: Merge styles from both source files into one `<style>` block. Use the shared `:root` variables (both files already use identical values). Include:
  - All CSS from `bitmor-math-explainer.html` lines 8-172 (sections, cards, fields, metrics, formulas, pills, badges, amort table, roll-down section, cash flow timeline, compare grid, footer)
  - Tab CSS from `rolldown_dashboard.html` lines 88-110 (`.tabs`, `.tab-btn`, `.tier-content`)
  - Stats/chart CSS from `rolldown_dashboard.html` lines 122-203 (`.stats-card`, `.stat`, `.chart-container`, `.methodology`, `details`)
  - New CSS for: `.tab-content` (same as `.tier-content`), `.path-badge` (clickable tier label), `.disclaimer-box` (subtle info box), `.highlight-flash` (1s orange border animation), `.sticky-tabs` (sticky tab bar)
- Header: Bitmor logo + "The math behind Bitcoin mortgages" (from math explainer header, lines 177-187)
- Tab bar: Three buttons — "General Explainer" (active), "Backtest & Simulations", "Methodology"
- Three `<div class="tab-content">` containers (ids: `tab-explainer`, `tab-backtests`, `tab-methodology`), only first visible
- Footer from math explainer (lines 413-416)

New CSS additions needed:

```css
/* Sticky tab bar */
.sticky-tabs {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--bg);
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
  margin-bottom: 24px;
}

/* Path info badge */
.path-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--bg3);
  cursor: pointer;
  transition: all 0.18s;
  font-size: 13px;
  margin-bottom: 20px;
}
.path-badge:hover { border-color: var(--accent); }
.path-badge .badge-tier {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 1px;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 4px;
  font-weight: 700;
}
.path-badge .badge-tier.tier-1 { color: var(--green); background: rgba(34,211,166,0.1); }
.path-badge .badge-tier.tier-2 { color: var(--accent); background: rgba(242,94,19,0.1); }
.path-badge .badge-tier.tier-3 { color: #7c8cf5; background: rgba(124,140,245,0.1); }

/* Disclaimer */
.disclaimer-box {
  background: rgba(107,122,150,0.06);
  border: 1px solid var(--border);
  border-left: 3px solid var(--muted);
  border-radius: 0 10px 10px 0;
  padding: 14px 18px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.6;
  margin: 32px 0;
  font-family: var(--mono);
}

/* Highlight flash for cross-links */
@keyframes highlightFlash {
  0% { border-color: var(--accent); box-shadow: 0 0 12px rgba(242,94,19,0.3); }
  100% { border-color: var(--border); box-shadow: none; }
}
.highlight-flash {
  animation: highlightFlash 1s ease-out;
}

/* Reshuffle button */
.reshuffle-btn {
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid var(--accent);
  background: rgba(242,94,19,0.08);
  color: var(--accent);
  font-family: var(--mono);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.18s;
  letter-spacing: 0.5px;
}
.reshuffle-btn:hover { background: var(--accent); color: #fff; }

/* Cross-link inline */
.cross-link {
  color: var(--accent);
  cursor: pointer;
  text-decoration: none;
  border-bottom: 1px dashed var(--accent);
}
.cross-link:hover { border-bottom-style: solid; }

/* Tier narrative */
.tier-narrative {
  font-size: 14px;
  color: var(--muted);
  line-height: 1.7;
  margin-bottom: 24px;
  max-width: 800px;
}
.tier-narrative strong { color: var(--text); }

/* Methodology anchored sections */
.method-section {
  margin-bottom: 32px;
  padding: 24px;
  background: var(--bg3);
  border: 1px solid var(--border);
  border-radius: 12px;
  transition: border-color 0.3s, box-shadow 0.3s;
}
.method-section h4 {
  color: var(--accent);
  font-family: var(--mono);
  font-size: 12px;
  letter-spacing: 1px;
  text-transform: uppercase;
  margin-bottom: 12px;
}
.method-section p { font-size: 14px; color: var(--muted); line-height: 1.7; margin-bottom: 8px; }
.method-section ul { padding-left: 20px; margin-bottom: 8px; }
.method-section li { font-size: 14px; color: var(--muted); margin-bottom: 4px; line-height: 1.6; }
.method-section strong { color: var(--text); }
```

**Step 2: Verify the shell opens in a browser**

Open `bitmor-dashboard.html` in a browser. Verify:
- Dark theme renders correctly
- Three tab buttons visible, first active (orange)
- Tab switching shows/hides content areas
- Footer visible at bottom

**Step 3: Commit**

```bash
git add bitmor-dashboard.html
git commit -m "feat: scaffold combined dashboard with tab navigation and merged CSS"
```

---

### Task 2: Embed CSV Data + DataStore Module

**Files:**
- Modify: `bitmor-dashboard.html`

**Step 1: Copy CSV data from rolldown dashboard**

Add a `<script>` block at the end of `<body>` (before any other scripts). Copy these three template literal blocks verbatim from `rolldown_dashboard.html`:
- `const TIER1_CSV = \`...\`;` (lines 385-1143 approx — 731 rows)
- `const TIER2_CSV = \`...\`;` (366 rows)
- `const TIER3_CSV = \`...\`;` (1000 rows)

Use the exact same variable names so references stay consistent.

**Step 2: Build DataStore module**

Add immediately after the CSV data:

```javascript
const DataStore = (() => {
  function parseCSV(raw) {
    const lines = raw.trim().split('\n');
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

  const tiers = {
    1: parseCSV(TIER1_CSV),
    2: parseCSV(TIER2_CSV),
    3: parseCSV(TIER3_CSV),
  };

  function getTierRows(tier) { return tiers[tier]; }

  function getTierStats(tier) {
    const data = tiers[tier];
    const n = data.length;
    const sorted = arr => [...arr].sort((a, b) => a - b);
    const percentile = (arr, p) => arr[Math.floor(arr.length * p / 100)];

    const recoveryPcts = data.map(r => r.roll_savings / r.initial_premium * 100);
    const sortedPct = sorted(recoveryPcts);
    const putCostPcts = sorted(data.map(r => r.initial_premium / r.spot * 100));
    const rollingNetPcts = sorted(data.map(r => (r.initial_premium - r.roll_savings) / r.spot * 100));

    return {
      count: n,
      avgPremium: data.reduce((s, r) => s + r.initial_premium, 0) / n,
      avgRecoveryPct: recoveryPcts.reduce((s, v) => s + v, 0) / n,
      medianRecoveryPct: percentile(sortedPct, 50),
      avgRollSavings: data.reduce((s, r) => s + r.roll_savings, 0) / n,
      medianRollSavings: percentile(sorted(data.map(r => r.roll_savings)), 50),
      avgRolls: data.reduce((s, r) => s + r.num_rolls, 0) / n,
      p25Pct: percentile(sortedPct, 25),
      p75Pct: percentile(sortedPct, 75),
      avgPutCostPct: data.reduce((s, r) => s + r.initial_premium / r.spot * 100, 0) / n,
      medianPutCostPct: percentile(putCostPcts, 50),
      avgRollingNetCostPct: data.reduce((s, r) => s + (r.initial_premium - r.roll_savings) / r.spot * 100, 0) / n,
      medianRollingNetCostPct: percentile(rollingNetPcts, 50),
      pathsWithPayoff: data.filter(r => r.terminal_payoff_rolling > 0).length,
      payoffPct: (data.filter(r => r.terminal_payoff_rolling > 0).length / n * 100),
    };
  }

  function getRandomPath(forceTier) {
    const tier = forceTier || [1, 2, 3][Math.floor(Math.random() * 3)];
    const rows = tiers[tier];
    const row = rows[Math.floor(Math.random() * rows.length)];
    return { tier, ...row };
  }

  return { getTierRows, getTierStats, getRandomPath };
})();
```

**Step 3: Verify DataStore parses correctly**

Open browser console, run:
- `DataStore.getTierRows(1).length` → should be ~731
- `DataStore.getTierRows(3).length` → should be ~1000
- `DataStore.getRandomPath()` → should return object with tier + CSV fields
- `DataStore.getTierStats(1).avgRecoveryPct` → should be a reasonable number (~50-60)

**Step 4: Commit**

```bash
git add bitmor-dashboard.html
git commit -m "feat: embed CSV data and build DataStore module"
```

---

### Task 3: Nav Module

**Files:**
- Modify: `bitmor-dashboard.html`

**Step 1: Add Nav module after DataStore**

```javascript
const Nav = (() => {
  const tabs = { explainer: 1, backtests: 2, methodology: 3 };
  const tabIds = { 1: 'tab-explainer', 2: 'tab-backtests', 3: 'tab-methodology' };
  const hashMap = { 1: '#explainer', 2: '#backtests', 3: '#methodology' };
  let currentTab = 1;
  const initCallbacks = { 1: null, 2: null, 3: null };

  function registerInit(tabNum, fn) { initCallbacks[tabNum] = fn; }

  function switchTab(tabNum) {
    document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.main-tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(tabIds[tabNum]).style.display = 'block';
    document.querySelector(`[data-tab="${tabNum}"]`).classList.add('active');
    currentTab = tabNum;
    history.replaceState(null, '', hashMap[tabNum]);

    // Lazy init
    if (initCallbacks[tabNum]) {
      initCallbacks[tabNum]();
      initCallbacks[tabNum] = null; // only once
    }
  }

  function goTo(tabNum, anchorId) {
    switchTab(tabNum);
    if (anchorId) {
      setTimeout(() => {
        const el = document.getElementById(anchorId);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' });
          el.classList.add('highlight-flash');
          setTimeout(() => el.classList.remove('highlight-flash'), 1200);
        }
      }, 100);
    }
  }

  // Handle browser back/forward
  function initFromHash() {
    const hash = location.hash.replace('#', '');
    if (tabs[hash]) switchTab(tabs[hash]);
  }

  return { switchTab, goTo, registerInit, initFromHash };
})();
```

**Step 2: Wire tab buttons to Nav**

Update the tab button HTML to use `data-tab` attributes and call `Nav.switchTab()`:

```html
<div class="sticky-tabs">
  <div class="tabs">
    <button class="main-tab-btn active" data-tab="1" onclick="Nav.switchTab(1)">General Explainer</button>
    <button class="main-tab-btn" data-tab="2" onclick="Nav.switchTab(2)">Backtest & Simulations</button>
    <button class="main-tab-btn" data-tab="3" onclick="Nav.switchTab(3)">Methodology</button>
  </div>
</div>
```

Use the existing `.tab-btn` class (rename to `.main-tab-btn` in both CSS and HTML to avoid collision with any sub-tabs).

**Step 3: Verify tab switching works**

- Click each tab → correct content area shows
- URL hash updates (#explainer, #backtests, #methodology)
- Reload with #methodology in URL → Tab 3 shows

**Step 4: Commit**

```bash
git add bitmor-dashboard.html
git commit -m "feat: add Nav module with tab switching, URL hash, and lazy init"
```

---

### Task 4: Tab 1 — Sections 1-2 (Loan Config + Amortization)

**Files:**
- Modify: `bitmor-dashboard.html`

**Step 1: Port Section 1 HTML from math explainer**

Copy the Section 1 HTML from `bitmor-math-explainer.html` lines 189-344 into the `#tab-explainer` container. This includes:
- Section label "01 — Loan Configuration"
- Two-column layout: Parameters card (sliders/buttons) + formula block + metric grid
- PUT Option Cost dark card with BS model and Deribit live sections
- All `id` attributes stay the same

Copy Section 2 HTML from lines 346-368:
- Section label "02 — Repayment Schedule"
- Amortization table wrapper with `<tbody id="amort-body">`

Add a `<hr class="divider">` between sections.

**Step 2: Port all Section 1-2 JavaScript**

Copy from `bitmor-math-explainer.html` into the main `<script>` block (after Nav module):
- Utility functions: `usd()`, `normCDF()`, `bsPut()` (lines 420-442)
- State variables: `_btcAmt`, `_dpPct`, `_term` (lines 423-425)
- `calc()` function (lines 444-574) — handles all loan math, BS pricing, Deribit display
- Deribit snapshot data `DERIBIT_SNAPSHOT` (lines 596-625)
- `livePrices`, `priceSource` variables (lines 628-629)
- `interpolateMark()`, `scaleByTime()`, `getPutPrice()` (lines 632-675)
- `fetchDeribitPrices()` (lines 678-756)
- Button selectors: `selectBTCAmt()`, `selectDP2()`, `selectTerm()`, `updateTermButtons()` (lines 992-1069)
- `fetchBTCSpot()` (lines 1072-1110)
- `EXPIRY_MAP`, `getContractType()`, `getExpiry()` (lines 996-1005)

**Step 3: Initialize on page load**

At the bottom of the script, call:
```javascript
// Initialize Tab 1 immediately (it's the default tab)
calc();
fetchBTCSpot();
fetchDeribitPrices();
```

Do NOT load Chart.js — we're using Plotly now. The `renderRollDown()` call will be handled in Task 5.

**Step 4: Verify Sections 1-2 work**

- Sliders update metrics in real-time
- Amortization table populates
- Deribit live fetch attempts (falls back to snapshot)
- BTC spot price fetches from Coinbase/Binance
- BTC Amount buttons toggle correctly
- Down Payment buttons work
- Term buttons work

**Step 5: Commit**

```bash
git add bitmor-dashboard.html
git commit -m "feat: port loan configuration and amortization (Tab 1 Sections 1-2)"
```

---

### Task 5: Tab 1 — Section 3 (PUT Roll-Down with Real Data)

**Files:**
- Modify: `bitmor-dashboard.html`

**Step 1: Add Section 3 HTML skeleton**

After the amortization section in `#tab-explainer`, add:

```html
<hr class="divider">

<div class="disclaimer-box">
  Sections 1-2 above are interactive and illustrative — configure any loan to see its amortization.
  Section 3 below uses actual backtest and simulation data with fixed parameters (70% LTV, 12-month term, 10% APR).
  The path shown is randomly selected from 2,000+ historical and simulated loan outcomes.
</div>

<div class="section" id="section-rolldown">
  <div class="section-label">03 — PUT Roll-Down Strategy</div>
  <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:20px;">
    <div id="path-badge" class="path-badge" onclick="Tab1.onBadgeClick()">
      <span class="badge-tier tier-1">TIER 1</span>
      <span id="path-badge-text">Loading...</span>
    </div>
    <button class="reshuffle-btn" onclick="Tab1.reshuffle()">Reshuffle Path</button>
  </div>

  <div class="chart-wrap" style="margin-bottom:16px;">
    <h4>Debt balance vs PUT strike over loan term</h4>
    <div id="rolldown-chart" style="width:100%;height:300px;"></div>
  </div>

  <div class="two-col" style="margin-bottom:16px;align-items:start;">
    <div class="card" style="padding:20px;">
      <h3 style="margin-bottom:16px;">Roll-down cash flows</h3>
      <div class="cf-timeline" id="path-cf-timeline"></div>
    </div>
    <div style="display:flex;flex-direction:column;gap:12px;">
      <div id="path-metrics"></div>
    </div>
  </div>
</div>
```

**Step 2: Build Tab1Controller**

```javascript
const Tab1 = (() => {
  let currentPath = null;

  // Loan params matching simulation: 70% LTV, 12mo, 10% APR
  const LTV = 0.70, TERM = 12, APR = 0.10;

  function computeAmortization(spot) {
    const total = spot;  // 1 BTC
    const principal = total * LTV;
    const r = APR / 12;
    const n = TERM;
    const M = principal * (r * Math.pow(1 + r, n)) / (Math.pow(1 + r, n) - 1);
    const balances = [principal];
    let bal = principal;
    for (let t = 1; t <= n; t++) {
      const interest = bal * r;
      bal -= (M - interest);
      balances.push(Math.max(0, bal));
    }
    return { principal, M, balances, totalInterest: M * n - principal };
  }

  function reconstructRollSchedule(numRolls, balances) {
    // Place rolls at roughly even intervals across 12 months
    const n = TERM;
    const rollMonths = [];
    if (numRolls >= 1) {
      const spacing = Math.floor(n / (numRolls + 1));
      for (let i = 1; i <= numRolls; i++) {
        const m = Math.min(i * spacing, n - 1);
        if (m > 0 && m < n) rollMonths.push(m);
      }
    }
    // Build strike array
    const strikes = new Array(n + 1).fill(null);
    let prevMonth = 0;
    let currentStrike = balances[0]; // principal
    for (const rm of rollMonths) {
      for (let m = prevMonth; m < rm; m++) strikes[m] = currentStrike;
      currentStrike = balances[rm];
      prevMonth = rm;
    }
    for (let m = prevMonth; m <= n; m++) strikes[m] = currentStrike;
    return { rollMonths, strikes };
  }

  function reconstructCashFlows(path, amort, rollSchedule) {
    const { initial_premium, roll_savings, num_rolls } = path;
    const { principal, totalInterest } = amort;
    const { rollMonths, strikes } = rollSchedule;
    const n = TERM;

    // We know total initial premium and total roll savings.
    // Distribute savings roughly evenly across rolls.
    const savingsPerRoll = num_rolls > 0 ? roll_savings / num_rolls : 0;

    const flows = [];
    let running = -initial_premium;
    flows.push({ month: 0, label: `Buy $${fmtK(principal)} PUT (12mo)`, flow: -initial_premium, running });

    let currentStrike = principal;
    for (let i = 0; i < rollMonths.length; i++) {
      const rm = rollMonths[i];
      const moLeft = n - rm;
      const newStrike = amort.balances[rm];

      // Sell old PUT — get back some value
      const sellVal = savingsPerRoll + (initial_premium - roll_savings) * 0.1; // approximate
      // Actually, let's use a simpler model:
      // total premium recovered = roll_savings, split across num_rolls
      const sellValue = savingsPerRoll;
      running += sellValue;
      flows.push({ month: rm, label: `Sell ${fmtK(currentStrike)} PUT (${moLeft}mo left)`, flow: +sellValue, running });

      // Buy new PUT at lower strike — cost embedded in the net savings
      // We don't show a separate buy cost since we only have net savings data
      // Instead, show as a single "Roll" event with net gain
      currentStrike = newStrike;
    }

    flows.push({ month: n, label: `${fmtK(currentStrike)} PUT expires`, flow: 0, running });

    return flows;
  }

  function fmtK(v) { return '$' + Math.round(v / 1000) + 'K'; }
  function fmtUSD(v) { return '$' + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

  function renderPath(path) {
    currentPath = path;
    const spot = path.spot;
    const amort = computeAmortization(spot);
    const rollSchedule = reconstructRollSchedule(path.num_rolls, amort.balances);

    // Badge
    const tierLabels = {
      1: 'Full Historical Backtest',
      2: 'Historical Entry + Simulated Forward',
      3: 'Full Monte Carlo Simulation',
    };
    const tierEl = document.querySelector('#path-badge .badge-tier');
    tierEl.className = `badge-tier tier-${path.tier}`;
    tierEl.textContent = `TIER ${path.tier}`;
    const dateStr = path.start_date || 'Today';
    document.getElementById('path-badge-text').textContent =
      `${tierLabels[path.tier]} — ${path.tier === 3 ? "Starting from today's" : 'Loan started ' + dateStr + ','} BTC at $${Math.round(spot).toLocaleString()}`;

    // Debt vs Strike chart (Plotly)
    const months = Array.from({ length: TERM + 1 }, (_, i) => i === 0 ? 'Start' : `Mo.${i}`);
    const debtTrace = {
      x: months, y: amort.balances,
      type: 'scatter', mode: 'lines+markers',
      name: 'Debt Balance',
      line: { color: '#F25E13', width: 2.5 },
      marker: { size: 5, color: '#F25E13' },
      fill: 'tozeroy',
      fillcolor: 'rgba(242,94,19,0.08)',
    };
    const strikeTrace = {
      x: months, y: rollSchedule.strikes,
      type: 'scatter', mode: 'lines+markers',
      name: 'PUT Strike',
      line: { color: '#22d3a6', width: 2, dash: 'dash' },
      marker: { size: 6, color: '#22d3a6' },
    };
    const chartLayout = {
      margin: { t: 10, b: 40, l: 70, r: 20 },
      xaxis: { tickfont: { color: '#6b7a96', family: 'IBM Plex Mono', size: 10 }, gridcolor: 'rgba(26,37,64,0.6)' },
      yaxis: {
        tickfont: { color: '#6b7a96', family: 'IBM Plex Mono', size: 10 },
        gridcolor: 'rgba(26,37,64,0.6)',
        tickformat: '$,.0f',
      },
      legend: { x: 0, y: 1.15, orientation: 'h', font: { color: '#6b7a96', family: 'IBM Plex Mono', size: 11 } },
      hovermode: 'x unified',
      plot_bgcolor: 'rgba(0,0,0,0)',
      paper_bgcolor: 'rgba(0,0,0,0)',
    };
    Plotly.newPlot('rolldown-chart', [debtTrace, strikeTrace], chartLayout, { responsive: true, displayModeBar: false });

    // Cash flow timeline
    const flows = reconstructCashFlows(path, amort, rollSchedule);
    const timeline = document.getElementById('path-cf-timeline');
    timeline.innerHTML = '';
    flows.forEach(ev => {
      const isPos = ev.flow > 0;
      const isZero = ev.flow === 0;
      const flowStr = isZero ? '—' : (isPos ? '+' : '') + fmtUSD(ev.flow);
      const runStr = '∑ ' + (ev.running >= 0 ? '+' : '−') + fmtUSD(Math.abs(ev.running));
      timeline.innerHTML += `
        <div class="cf-event">
          <div class="cf-month">Mo.${ev.month}</div>
          <div class="cf-desc">${ev.label}</div>
          <div class="cf-flow ${isPos ? 'pos' : isZero ? '' : 'neg'}">${flowStr}</div>
          <div class="cf-running">${runStr}</div>
        </div>`;
    });

    // Summary metrics
    const metricsHtml = `
      <div class="three-col" style="grid-template-columns:1fr 1fr;gap:8px;">
        <div class="metric">
          <div class="metric-label">Initial Premium</div>
          <div class="metric-value red">${fmtUSD(path.initial_premium)}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Roll Savings</div>
          <div class="metric-value green">${fmtUSD(path.roll_savings)}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Recovery</div>
          <div class="metric-value accent">${path.roll_savings_pct.toFixed(1)}%</div>
        </div>
        <div class="metric">
          <div class="metric-label">Num Rolls</div>
          <div class="metric-value">${path.num_rolls}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Final BTC Spot</div>
          <div class="metric-value">${'$' + Math.round(path.final_spot).toLocaleString()}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Terminal Payoff</div>
          <div class="metric-value ${path.terminal_payoff_rolling > 0 ? 'green' : ''}">${fmtUSD(path.terminal_payoff_rolling)}</div>
        </div>
        <div class="metric">
          <div class="metric-label">PUT Cost % of BTC</div>
          <div class="metric-value">${path.effective_put_cost_pct.toFixed(2)}%</div>
        </div>
        <div class="metric">
          <div class="metric-label">Net Cost After Roll</div>
          <div class="metric-value green">${path.rolling_net_cost_pct.toFixed(2)}%</div>
        </div>
      </div>
    `;
    document.getElementById('path-metrics').innerHTML = metricsHtml;
  }

  function reshuffle(forceTier) {
    renderPath(DataStore.getRandomPath(forceTier));
  }

  function reshuffleFromTier(tier) {
    renderPath(DataStore.getRandomPath(tier));
    Nav.switchTab(1);
    setTimeout(() => {
      document.getElementById('section-rolldown').scrollIntoView({ behavior: 'smooth' });
    }, 150);
  }

  function onBadgeClick() {
    if (currentPath) Nav.goTo(2, 'tier-section-' + currentPath.tier);
  }

  function init() {
    reshuffle();
  }

  return { init, reshuffle, reshuffleFromTier, onBadgeClick };
})();
```

**Step 3: Initialize Section 3 on page load**

```javascript
// After calc() and fetch calls:
Tab1.init();
```

**Step 4: Verify Section 3 works**

- Path badge shows tier label + details
- Debt vs Strike Plotly chart renders with declining debt line and stepped strike
- Cash flow timeline shows buy/sell events
- Metrics card shows all 8 values from CSV
- "Reshuffle Path" button picks a new random path
- Clicking path badge... (no Tab 2 yet, so just verify it calls Nav.goTo)

**Step 5: Commit**

```bash
git add bitmor-dashboard.html
git commit -m "feat: add PUT roll-down Section 3 with real data paths and reshuffle"
```

---

### Task 6: Tab 2 — Backtest & Simulations

**Files:**
- Modify: `bitmor-dashboard.html`

**Step 1: Add Tab 2 HTML structure**

Inside `#tab-backtests`:

```html
<!-- Tier 1 -->
<div class="section" id="tier-section-1">
  <div class="section-label">Tier 1 — Historical Backtest</div>
  <div class="tier-narrative" id="narrative-1"></div>
  <div class="stats-card" id="stats-1"></div>
  <div class="chart-container" id="chart-1"></div>
</div>

<hr class="divider">

<!-- Tier 2 -->
<div class="section" id="tier-section-2">
  <div class="section-label">Tier 2 — Historical Entry + Simulated Forward</div>
  <div class="tier-narrative" id="narrative-2"></div>
  <div class="stats-card" id="stats-2"></div>
  <div class="chart-container" id="chart-2"></div>
</div>

<hr class="divider">

<!-- Tier 3 -->
<div class="section" id="tier-section-3">
  <div class="section-label">Tier 3 — Forward Simulation</div>
  <div class="tier-narrative" id="narrative-3"></div>
  <div class="stats-card" id="stats-3"></div>
  <div class="chart-container" id="chart-3-scatter"></div>
  <div class="chart-container" id="chart-3-hist"></div>
</div>
```

**Step 2: Build Tab2Controller**

Port and adapt the rendering functions from `rolldown_dashboard.html` (lines 2510-2769). Wrap in a Tab2 module:

```javascript
const Tab2 = (() => {
  const fmt = (v, dec = 0) => v.toLocaleString('en-US', {
    minimumFractionDigits: dec, maximumFractionDigits: dec
  });

  function renderStats(containerId, stats, isTier3) {
    // Same as rolldown_dashboard.html renderStats (lines 2538-2558)
    // Add extra stats for Tier 3: pathsWithPayoff, payoffPct
    let html = `
      <div class="stat"><span class="stat-label">${isTier3 ? 'Paths' : 'Loans'}</span>
        <span class="stat-value">${stats.count}</span></div>
      <div class="stat"><span class="stat-label">Avg Premium</span>
        <span class="stat-value">$${fmt(stats.avgPremium)}</span></div>
      <div class="stat"><span class="stat-label">Avg Roll Savings</span>
        <span class="stat-value" style="color:#22d3a6">$${fmt(stats.avgRollSavings)}</span></div>
      <div class="stat"><span class="stat-label">Avg Recovery</span>
        <span class="stat-value" style="color:#F25E13">${fmt(stats.avgRecoveryPct, 1)}%</span></div>
      <div class="stat"><span class="stat-label">PUT Cost % of BTC</span>
        <span class="stat-value">${fmt(stats.avgPutCostPct, 2)}%</span></div>
      <div class="stat"><span class="stat-label">Net Cost % of BTC</span>
        <span class="stat-value" style="color:#22d3a6">${fmt(stats.avgRollingNetCostPct, 2)}%</span></div>
    `;
    if (isTier3) {
      html += `
        <div class="stat"><span class="stat-label">Median Recovery</span>
          <span class="stat-value" style="color:#F25E13">${fmt(stats.medianRecoveryPct, 1)}%</span></div>
        <div class="stat"><span class="stat-label">Paths with Payoff</span>
          <span class="stat-value" style="color:#22d3a6">${fmt(stats.payoffPct, 1)}%</span></div>
      `;
    }
    document.getElementById(containerId).innerHTML = html;
  }

  function renderTimeSeries(divId, data, title) {
    // Port directly from rolldown_dashboard.html lines 2560-2631
    // (the renderTimeSeries function — scatter + spot overlay + avg line)
    // Exact same Plotly traces and layout
    const dates = data.map(r => r.start_date);
    const recoveryPct = data.map(r => r.roll_savings / r.initial_premium * 100);
    const spots = data.map(r => r.spot);
    const avgRecovery = recoveryPct.reduce((s, v) => s + v, 0) / recoveryPct.length;
    const hoverText = data.map(r =>
      `Date: ${r.start_date}<br>` +
      `Entry Spot: $${r.spot.toLocaleString()}<br>` +
      `Premium: $${r.initial_premium.toLocaleString()}<br>` +
      `PUT Cost (% of BTC): ${(r.initial_premium / r.spot * 100).toFixed(2)}%<br>` +
      `Roll Savings: $${r.roll_savings.toLocaleString()}<br>` +
      `Recovery: ${(r.roll_savings / r.initial_premium * 100).toFixed(1)}%<br>` +
      `Net Cost After Rolling (% of BTC): ${((r.initial_premium - r.roll_savings) / r.spot * 100).toFixed(2)}%`
    );

    const trace1 = {
      x: dates, y: recoveryPct,
      type: 'scatter', mode: 'markers',
      name: '% of Premium Recovered',
      marker: { size: 5, color: '#F25E13', opacity: 0.7 },
      text: hoverText, hoverinfo: 'text', yaxis: 'y1',
    };
    const trace2 = {
      x: dates, y: spots,
      type: 'scatter', mode: 'lines',
      name: 'BTC Spot Price',
      line: { color: 'rgba(107,122,150,0.5)', width: 1.5 },
      yaxis: 'y2', hoverinfo: 'skip',
    };
    const traceAvg = {
      x: [dates[0], dates[dates.length - 1]],
      y: [avgRecovery, avgRecovery],
      type: 'scatter', mode: 'lines',
      name: `Average (${avgRecovery.toFixed(1)}%)`,
      line: { color: '#22d3a6', width: 2, dash: 'dot' },
      hoverinfo: 'skip', yaxis: 'y1',
    };
    const layout = {
      title: { text: title, font: { size: 14, color: '#6b7a96', family: 'IBM Plex Mono' } },
      xaxis: { title: 'Loan Start Date', color: '#6b7a96', gridcolor: '#1a2540', tickfont: { color: '#6b7a96', family: 'IBM Plex Mono', size: 10 }, titlefont: { color: '#6b7a96', family: 'IBM Plex Mono', size: 11 } },
      yaxis: { title: '% of Premium Recovered', zeroline: false, color: '#6b7a96', gridcolor: '#1a2540', tickfont: { color: '#6b7a96', family: 'IBM Plex Mono', size: 10 }, titlefont: { color: '#6b7a96', family: 'IBM Plex Mono', size: 11 } },
      yaxis2: { title: { text: 'BTC Spot ($)', standoff: 15 }, overlaying: 'y', side: 'right', showgrid: false, tickformat: '$,.0f', color: '#6b7a96', tickfont: { color: '#6b7a96', family: 'IBM Plex Mono', size: 10 }, titlefont: { color: '#6b7a96', family: 'IBM Plex Mono', size: 11 } },
      legend: { x: 0, y: -0.22, orientation: 'h', font: { color: '#6b7a96', family: 'IBM Plex Mono', size: 11 } },
      margin: { t: 50, b: 100, l: 60, r: 100 },
      hovermode: 'closest',
      plot_bgcolor: 'rgba(0,0,0,0)',
      paper_bgcolor: 'rgba(0,0,0,0)',
    };
    Plotly.newPlot(divId, [trace2, traceAvg, trace1], layout, { responsive: true, displayModeBar: false });
  }

  function renderHistogram(divId, data) {
    // Port from rolldown_dashboard.html lines 2633-2690
    // Same histogram with percentile lines and annotations
    // (copy the function body exactly)
  }

  function renderScatter(divId, data) {
    // Port from rolldown_dashboard.html lines 2692-2741
    // Same scatter plot: recovery % vs final spot
    // (copy the function body exactly)
  }

  function renderNarratives(stats1, stats2, stats3) {
    const tier1Data = DataStore.getTierRows(1);
    const tier2Data = DataStore.getTierRows(2);
    const firstSpot1 = tier1Data[0].spot;
    const lastSpot1 = tier1Data[tier1Data.length - 1].final_spot;

    document.getElementById('narrative-1').innerHTML = `
      <p><strong>${stats1.count} loans</strong> starting daily from March 2023 to March 2025. BTC rallied from
      ~$${Math.round(firstSpot1/1000)}k to ~$${Math.round(lastSpot1/1000)}k — a sustained bull market.</p>
      <p>In this environment, the PUT never triggered (all terminal payoffs are zero), so the entire value of the
      strategy comes from <span class="cross-link" onclick="Nav.goTo(3,'roll-mechanics')">roll savings</span>
      recovering the initial premium. Average recovery was <strong>${stats1.avgRecoveryPct.toFixed(1)}%</strong>,
      meaning the hedging cost was substantially offset even though protection was never needed.</p>
      <p><span class="cross-link" onclick="Tab1.reshuffleFromTier(1)">See a random example from this tier →</span></p>
    `;

    const firstSpot2 = tier2Data[0].spot;
    document.getElementById('narrative-2').innerHTML = `
      <p><strong>${stats2.count} loans</strong> starting daily from March 2025 to March 2026. BTC declined from
      ~$${Math.round(firstSpot2/1000)}k to ~$66k — a bearish regime.</p>
      <p>Loans not yet expired are extended with 1,000 simulated price paths each, averaged per start date.
      Some paths show non-zero terminal payoff — the <span class="cross-link" onclick="Nav.goTo(3,'strategy')">hedge actually paid out</span>
      when BTC dropped below the rolled-down strike. This tier tests whether the strategy holds
      when markets move against the borrower.</p>
      <p><span class="cross-link" onclick="Tab1.reshuffleFromTier(2)">See a random example from this tier →</span></p>
    `;

    document.getElementById('narrative-3').innerHTML = `
      <p><strong>${stats3.count} independent Monte Carlo paths</strong> from today's spot (~$66,280). Full 12-month
      <span class="cross-link" onclick="Nav.goTo(3,'gbm-calibration')">GBM simulation</span> with
      <span class="cross-link" onclick="Nav.goTo(3,'assumptions')">frozen IV surface</span>.</p>
      <p>Each path is an individual outcome, not averaged. The distribution spans from BTC crashing to ~$18k
      (hedge pays out $27k+) to rallying past $300k (rolls recover 100%+ of premium).
      <strong>${stats3.payoffPct.toFixed(0)}%</strong> of paths show a positive terminal payoff where the hedge triggered.</p>
      <p><span class="cross-link" onclick="Tab1.reshuffleFromTier(3)">See a random example from this tier →</span></p>
    `;
  }

  function init() {
    const stats1 = DataStore.getTierStats(1);
    const stats2 = DataStore.getTierStats(2);
    const stats3 = DataStore.getTierStats(3);

    renderNarratives(stats1, stats2, stats3);

    renderStats('stats-1', stats1, false);
    renderTimeSeries('chart-1', DataStore.getTierRows(1), 'Historical Backtest — Premium Recovery by Start Date');

    renderStats('stats-2', stats2, false);
    renderTimeSeries('chart-2', DataStore.getTierRows(2), 'Recent Loans — Premium Recovery by Start Date');

    renderStats('stats-3', stats3, true);
    renderScatter('chart-3-scatter', DataStore.getTierRows(3));
    renderHistogram('chart-3-hist', DataStore.getTierRows(3));
  }

  return { init };
})();
```

**Step 3: Register Tab 2 for lazy init**

```javascript
Nav.registerInit(2, Tab2.init);
```

**Step 4: Verify Tab 2**

- Click "Backtest & Simulations" tab
- All three tier sections render with narratives, stats, and charts
- Hover tooltips work on charts
- Cross-links in narratives navigate correctly (Tab 3 links won't work yet)
- "See a random example" links switch to Tab 1 and show a path from that tier

**Step 5: Commit**

```bash
git add bitmor-dashboard.html
git commit -m "feat: add Tab 2 with three tiers, narratives, stats, and Plotly charts"
```

---

### Task 7: Tab 3 — Methodology

**Files:**
- Modify: `bitmor-dashboard.html`

**Step 1: Add Tab 3 HTML**

Inside `#tab-methodology`, add the methodology content from `rolldown_dashboard.html` lines 277-376, restructured into anchored `<div class="method-section">` cards:

```html
<div class="section">
  <div class="section-label">Reference</div>
  <h2>Methodology</h2>
  <p class="desc">How the backtest and simulation work, from strategy mechanics to data sources.</p>

  <div class="method-section" id="strategy">
    <h4>Strategy Overview</h4>
    <p>Each BTC-collateralized loan is hedged with a 12-month PUT option struck at
    the initial debt level. As monthly payments reduce the outstanding debt, the
    existing PUT (with a now-too-high strike) can be sold and replaced with a cheaper
    PUT at the lower strike. The difference is captured as roll savings. A roll is
    only executed when the profit exceeds $200.</p>
    <p><span class="cross-link" onclick="Tab1.reshuffleFromTier(0)">See a live example →</span></p>
  </div>

  <div class="method-section" id="roll-mechanics">
    <h4>Roll Decision Mechanics</h4>
    <p>At each monthly payment checkpoint (months 1–11), the simulation reprices the
    currently held PUT using the IV surface and compares it against a replacement PUT
    struck at the current outstanding debt. The new strike is always lower than the
    previous one because amortisation reduces the loan balance each month. A roll
    executes only when the difference (held PUT value minus replacement cost) exceeds
    $200 — filtering out micro-rolls that would not be economically meaningful after
    real-world transaction costs. On roll, the held PUT is sold, the replacement is
    purchased, and the profit is accumulated as roll savings.</p>
  </div>

  <div class="method-section" id="premium-recovery">
    <h4>Premium Recovery</h4>
    <p>Roll savings represent the portion of the initial PUT premium that can be
    recovered through the rolling strategy. The recovery percentage is calculated as
    cumulative roll savings divided by the initial premium cost. Higher recovery
    means the hedging cost is substantially offset.</p>
  </div>

  <div class="method-section" id="option-pricing">
    <h4>Option Pricing</h4>
    <p>All PUT options are priced using the Black-Scholes model for European
    cash-settled options. This is appropriate because BTC options (e.g. on Deribit)
    are European-style with no early exercise. Inputs are the current spot price,
    strike (outstanding debt), time to expiration, and implied volatility from
    the SVI surface. Risk-free rate is set to zero.</p>
  </div>

  <div class="method-section" id="iv-surface">
    <h4>IV Surface</h4>
    <p>Implied volatility is sourced from Deribit historical option trades spanning
    700+ trading days. For each day, option quotes are grouped into five tenor
    buckets (short/90d/180d/270d/365d) and fitted using the Stochastic Volatility
    Inspired (SVI) parameterisation, which models total variance as a function of
    log-moneyness. The SVI fit is calibrated via L-BFGS-B optimisation with bounds
    to prevent arbitrage violations. The result is a smooth, arbitrage-free IV
    surface across 26 moneyness points and 5 tenors for each trading day. A minimum
    of 6 quotes per day-tenor is required for calibration; sparse tenor buckets are
    forward-filled up to 60 days.</p>
  </div>

  <div class="method-section" id="gbm-calibration">
    <h4>GBM Calibration (Tier 2 & 3)</h4>
    <p>Simulated price paths use Geometric Brownian Motion with constant drift and
    volatility. Both parameters are calibrated from approximately 3 years of hourly
    BTC spot prices (Binance BTCUSDT), resampled to daily log returns. Drift (μ)
    is the annualised mean of daily log returns; volatility (σ) is the annualised
    standard deviation. Paths are generated at daily resolution (dt = 1/365) with
    i.i.d. standard normal shocks. The IV surface is frozen at the latest available
    snapshot for all forward months — it does not evolve with the simulated price
    path.</p>
  </div>

  <div class="method-section" id="simulation-tiers">
    <h4>Simulation Tiers</h4>
    <p><strong>Tier 1 (Historical Backtest)</strong> uses only actual historical BTC
    prices and actual IV surface data — no simulation whatsoever. Every roll decision
    uses real market conditions as they existed on that date.
    <span class="cross-link" onclick="Nav.goTo(2,'tier-section-1')">See Tier 1 results →</span></p>
    <p><strong>Tier 2 (Recent Loans)</strong> uses real prices and IV up to today,
    then extends each loan with 1,000 GBM-simulated price paths for the remaining
    months. Each start date reports the average across all 1,000 paths. This grounds
    the analysis in real entry conditions while incorporating forward uncertainty.
    <span class="cross-link" onclick="Nav.goTo(2,'tier-section-2')">See Tier 2 results →</span></p>
    <p><strong>Tier 3 (Forward Simulation)</strong> generates 1,000 independent
    12-month GBM paths from today's spot price. Each path is reported individually
    (not averaged), showing the full distribution of possible outcomes for a loan
    originated today.
    <span class="cross-link" onclick="Nav.goTo(2,'tier-section-3')">See Tier 3 results →</span></p>
  </div>

  <div class="method-section" id="loan-parameters">
    <h4>Loan Parameters</h4>
    <p><strong>LTV:</strong> 70% · <strong>Loan tenor:</strong> 12 months ·
    <strong>Annual rate:</strong> 10% · <strong>Payment:</strong> Fixed monthly
    (standard amortisation) · <strong>Option tenors:</strong> 3/6/9/12 months
    (smallest tenor ≥ remaining loan life is selected) ·
    <strong>Min roll profit:</strong> $200</p>
  </div>

  <div class="method-section" id="assumptions">
    <h4>Key Assumptions</h4>
    <ul>
      <li><strong>Frozen IV surface:</strong> For Tier 2/3 forward months, the IV
      surface is held constant at today's snapshot rather than evolving with the
      simulated spot. This avoids a circular dependency between realised volatility
      and implied volatility, and is conservative.</li>
      <li><strong>No transaction costs:</strong> Roll profits are not adjusted for
      exchange fees (typically 0.1–0.5% on Deribit). Real-world recovery will be
      modestly lower.</li>
      <li><strong>Monthly checkpoints only:</strong> Roll decisions are evaluated
      11 times per loan, matching the monthly payment schedule.</li>
      <li><strong>Constant GBM parameters:</strong> Drift and volatility do not
      change across the simulation horizon. Real markets exhibit regime shifts,
      so this is a simplification.</li>
    </ul>
  </div>

  <div class="method-section" id="data-sources">
    <h4>Data Sources</h4>
    <p><strong>BTC spot prices:</strong> Binance BTCUSDT hourly candles, ~3 years
    of history (resampled to daily for GBM calibration, used at hourly resolution
    for historical backtest).</p>
    <p><strong>Options data:</strong> Deribit historical option trades API, covering
    month-end and quarterly BTC option contracts across all strikes and expiries.
    ~1.4 million data points spanning 700+ trading days.</p>
  </div>
</div>
```

**Step 2: Register Tab 3 for lazy init (no-op — static content)**

Tab 3 is static HTML, no lazy init needed. But register a no-op so Nav doesn't skip it:

```javascript
Nav.registerInit(3, () => {}); // static content, nothing to render
```

**Step 3: Fix the "See a live example" link in #strategy**

The `reshuffleFromTier(0)` call should use no forced tier (random across all):

```javascript
// In the #strategy section, change onclick to:
onclick="Tab1.reshuffleFromTier(null)"
```

And update `reshuffleFromTier` to handle `null` (pick any tier):

```javascript
function reshuffleFromTier(tier) {
  renderPath(DataStore.getRandomPath(tier || undefined));
  Nav.switchTab(1);
  // ...
}
```

**Step 4: Verify Tab 3**

- Click "Methodology" tab
- All 10 sections render with correct content
- Anchor IDs work: manually navigate to `#methodology` then click browser address bar → add `#iv-surface` → section scrolls into view
- Cross-links to Tab 2 work (click "See Tier 1 results →" → switches to Tab 2, scrolls to Tier 1 section with highlight flash)
- Cross-link from #strategy to Tab 1 works

**Step 5: Commit**

```bash
git add bitmor-dashboard.html
git commit -m "feat: add Tab 3 methodology with anchored sections and cross-links"
```

---

### Task 8: Wire All Cross-Links + Polish

**Files:**
- Modify: `bitmor-dashboard.html`

**Step 1: Verify all cross-links work end-to-end**

Test each link path:
- Tab 1 path badge → Tab 2 correct tier section (highlight flash)
- Tab 2 narrative "roll savings" → Tab 3 #roll-mechanics
- Tab 2 narrative "See a random example" → Tab 1 Section 3 reshuffled to that tier
- Tab 2 "IV surface" → Tab 3 #iv-surface
- Tab 2 "GBM calibration" → Tab 3 #gbm-calibration
- Tab 2 "frozen IV" → Tab 3 #assumptions
- Tab 3 "See Tier 1/2/3 results" → Tab 2 correct section
- Tab 3 "See a live example" → Tab 1 Section 3

Fix any broken links discovered during testing.

**Step 2: Handle URL hash on page load**

At the bottom of the init block:

```javascript
// Handle initial URL hash
Nav.initFromHash();
```

**Step 3: Add `popstate` listener for browser back/forward**

```javascript
window.addEventListener('popstate', Nav.initFromHash);
```

**Step 4: Polish — responsive edge cases**

- Test at mobile width (< 640px): verify grids collapse to 2-col or 1-col
- Verify sticky tab bar doesn't overlap content
- Verify Plotly charts resize on window resize

**Step 5: Commit**

```bash
git add bitmor-dashboard.html
git commit -m "feat: wire cross-links, URL hash handling, and responsive polish"
```

---

### Task 9: Final Review + Cleanup

**Files:**
- Modify: `bitmor-dashboard.html`

**Step 1: Data conflict audit**

Review Section 3 rendering to confirm:
- No hardcoded risk-free rate leaks from Sections 1-2 into Section 3
- All Section 3 metrics come from CSV fields
- No math explainer sensitivity factors appear in Section 3
- Tab 2/3 numbers match rolldown dashboard exactly

**Step 2: Remove any dead code**

- Remove `renderRollDown()` and `computeRollDown()` from the math explainer JS (they're replaced by Tab1 module)
- Remove `activeDP`, `activeSens`, `rollChartInst` state variables
- Remove `selectDP()` and `selectSens()` functions (Section 3 no longer has down payment / sensitivity buttons)
- Remove Chart.js loading script (replaced by Plotly)
- Keep `selectDP2()` (used by Section 1 down payment buttons — different function name)

**Step 3: Verify the complete file works end-to-end**

Full walkthrough:
1. Open file → Tab 1 loads, sliders work, amortization renders, Deribit fetches
2. Section 3 shows a random path with chart, cashflows, metrics
3. Reshuffle works, badge is clickable
4. Tab 2 → all 3 tiers render with narratives, stats, charts
5. Tab 3 → all methodology sections present
6. Cross-links work in all directions
7. Browser back/forward works with URL hash

**Step 4: Final commit**

```bash
git add bitmor-dashboard.html
git commit -m "feat: complete combined Bitmor dashboard with 3 tabs, real data paths, and cross-linking"
```
