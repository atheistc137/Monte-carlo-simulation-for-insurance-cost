# Dashboard Rehaul Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reshape `bitmor-dashboard.html` from 4-tab layout to 2-view layout matching `bitmor-dashboard.jsx` design, keeping all real data and calculation logic.

**Architecture:** Surgically modify existing HTML/CSS/JS. Replace nav + CSS theme first, then rebuild View 1 (Cost Calculator) and View 2 (Roll-Down Research) HTML sections, then update JS modules to wire into new DOM structure. All CSV data, DataStore, Deribit engine, and math functions stay untouched.

**Tech Stack:** Vanilla HTML/CSS/JS, Plotly.js, Coinbase/Binance/Deribit APIs

**Reference files:**
- Source of truth for UI/layout: `bitmor-dashboard.jsx` (the "design file")
- Source of truth for data/logic: `bitmor-dashboard.html` (the "production file")

---

## Color Token Mapping (JSX → CSS)

The JSX uses different color tokens than the current HTML. Update CSS `:root` variables:

| CSS Variable | Current Value | New Value (from JSX:3-8) | Notes |
|---|---|---|---|
| `--bg` | `#030916` | `#030916` | Same |
| `--bg2` | `#080f1f` | `#0a1428` | JSX `bgCard` |
| `--bg3` | `#0d1628` | `#0a1428` | Merge with bgCard |
| `--accent` | `#F25E13` | `#F25E13` | Same (persimmon) |
| `--accent2` | `#ff8547` | — | Remove, unused in JSX |
| `--text` | `#e8eaf0` | `#e8ecf4` | Slightly different |
| `--muted` | `#6b7a96` | `#4a5d7a` | JSX `textMuted` |
| `--border` | `#1a2540` | `#1a2a4a` | JSX `border` |
| `--green` | `#22d3a6` | `#22c55e` | Different green |
| `--red` | `#f25e6a` | `#ef4444` | Different red |
| NEW `--yellow` | — | `#eab308` | JSX uses for interest |
| NEW `--text-dim` | — | `#7a8ba8` | JSX `textDim` |
| NEW `--bg-card-hover` | — | `#0f1d38` | JSX `bgCardHover` |
| NEW `--border-light` | — | `#243556` | JSX `borderLight` |
| NEW `--persimmon-dim` | — | `rgba(242,94,19,0.15)` | JSX `persimmonDim` |
| NEW `--persimmon-glow` | — | `rgba(242,94,19,0.4)` | JSX `persimmonGlow` |
| NEW `--green-dim` | — | `rgba(34,197,94,0.15)` | JSX `greenDim` |

---

### Task 1: Update CSS color tokens and add new variables

**Files:**
- Modify: `bitmor-dashboard.html` — `:root` block (lines 12-25)

**Step 1:** Replace the `:root` block with updated tokens:

```css
:root {
  --bg: #030916;
  --bg-card: #0a1428;
  --bg-card-hover: #0f1d38;
  --border: #1a2a4a;
  --border-light: #243556;
  --accent: #F25E13;
  --persimmon-dim: rgba(242,94,19,0.15);
  --persimmon-glow: rgba(242,94,19,0.4);
  --green: #22c55e;
  --green-dim: rgba(34,197,94,0.15);
  --red: #ef4444;
  --yellow: #eab308;
  --text: #e8ecf4;
  --text-dim: #7a8ba8;
  --text-muted: #4a5d7a;
  --white: #ffffff;
  --font: 'Bricolage Grotesque', sans-serif;
  --mono: 'IBM Plex Mono', monospace;
}
```

**Step 2:** Find-and-replace CSS references throughout the `<style>` block:
- `var(--bg2)` → `var(--bg-card)`
- `var(--bg3)` → `var(--bg-card)`
- `var(--muted)` → `var(--text-muted)` (where used for text color)
- `var(--accent2)` → `var(--accent)` (only a couple formula usages)

**Step 3:** Open file in browser, verify no broken colors. Commit.

---

### Task 2: Replace nav bar (4-tab → 2-view)

**Files:**
- Modify: `bitmor-dashboard.html` — `<header>` block (lines 434-444), sticky-tabs block (lines 447-454), CSS for `.sticky-tabs` / `.main-tab-btn` (lines 173-198)

**Step 1:** Place the new nav bar **before** `<div class="container">` (not inside it), so it spans full viewport width — matching JSX:158 where the nav is at the App level outside V1/V2. Replace the old `<header>` and `.sticky-tabs` blocks (which are inside `.container`) with this, placed directly after `<body>`:

```html
<nav class="top-nav">
  <div class="nav-logo">
    <div class="nav-logo-mark">B</div>
    <span class="nav-logo-text">Bitmor</span>
  </div>
  <div class="nav-tabs">
    <button class="nav-tab active" data-view="calculator" onclick="Nav.switchTab('calculator')">Cost Calculator</button>
    <button class="nav-tab" data-view="research" onclick="Nav.switchTab('research')">Roll-Down Research</button>
  </div>
  <a href="https://bitmor.xyz/loans" target="_blank" rel="noopener" class="nav-cta">Join Waitlist</a>
</nav>
```

**Step 2:** Add CSS for nav (from JSX:159 inline styles):

```css
.top-nav {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(3,9,22,0.93);
  backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border);
  padding: 0 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.nav-logo { display: flex; align-items: center; gap: 10px; }
.nav-logo-mark {
  width: 28px; height: 28px; border-radius: 6px;
  background: var(--accent); display: flex; align-items: center;
  justify-content: center; font-size: 14px; font-weight: 800; color: var(--white);
}
.nav-logo-text { font-size: 15px; font-weight: 600; color: var(--text); }
.nav-tabs { display: flex; }
.nav-tab {
  padding: 16px 20px; background: none; border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-dim); font-size: 13px; font-weight: 500;
  cursor: pointer; font-family: var(--font);
}
.nav-tab:hover { color: var(--text); }
.nav-tab.active { border-bottom-color: var(--accent); color: var(--text); }
.nav-cta {
  padding: 7px 18px; border-radius: 6px; background: var(--accent);
  color: var(--white); font-size: 12px; font-weight: 600; text-decoration: none;
}
```

**Step 3:** Remove old CSS for `.sticky-tabs`, `.tabs`, `.main-tab-btn`, old `.logo` classes, old `header` styles.

**Step 4:** Remove the old `<header>` block entirely (lines 434-444: logo, h1, subtitle — the intro text moves into View 1 body).

---

### Task 3: Restructure HTML — two view containers

**Files:**
- Modify: `bitmor-dashboard.html` — the 4 `tab-content` divs

**Step 1:** Replace the 4 tab-content divs with 2 view containers:

```html
<!-- VIEW 1: COST CALCULATOR -->
<div class="view-content" id="view-calculator" style="display:block;">
  <!-- Content from Task 4-8 goes here -->
</div>

<!-- VIEW 2: ROLL-DOWN RESEARCH -->
<div class="view-content" id="view-research" style="display:none;">
  <!-- Content from Task 9-13 goes here -->
</div>
```

**Step 2:** Add CSS:
```css
.view-content { display: none; }
```

**Step 3:** Delete Tab 3 (`#tab-math`) HTML entirely (lines 773-970 — all the Bitmor Math method sections, IRM SVG, liquidation flows, etc.).

**Step 4:** Delete Tab 4 (`#tab-methodology`) HTML entirely (lines 975-1046 — methodology sections). The 4 key items will be recreated as a collapsible in View 2.

---

### Task 4: Build View 1 — Intro block + Loan origination flow

**Files:**
- Modify: `bitmor-dashboard.html` — inside `#view-calculator`

**Step 1:** Add intro block (from JSX:185-187):

```html
<div style="margin-bottom:48px;">
  <h1 style="font-size:32px;font-weight:700;color:var(--text);margin:0 0 8px;">Bitcoin mortgages, on-chain</h1>
  <p style="font-size:15px;color:var(--text-dim);margin:0 0 28px;line-height:1.7;max-width:680px;">Bitmor lets you buy BTC with a down payment and repay in fixed monthly installments. A PUT option replaces traditional liquidation, so your position is never force-sold on a price drop.</p>
```

**Step 2:** Add loan origination card (from JSX:189-206). Note: JSX uses Card component (background: `--bg-card`, border: `1px solid --border`, borderRadius: 12, padding: 28). This specific instance overrides padding to `20px 24px`:

```html
  <div class="card" style="padding:20px 24px;">
    <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.1em;margin-bottom:16px;">How a loan is created</div>
    <div style="display:flex;align-items:flex-start;gap:6px;overflow-x:auto;padding-bottom:4px;">
      <!-- Step 1 -->
      <div style="display:flex;align-items:center;gap:6px;flex-shrink:0;">
        <div style="padding:12px 18px;border-radius:8px;background:var(--bg);border:1px solid rgba(242,94,19,0.2);min-width:120px;text-align:center;">
          <div style="font-size:12px;font-weight:600;color:var(--text);line-height:1.4;">USDC<br>Down Payment</div>
          <div style="font-size:9px;color:var(--text-muted);margin-top:5px;">30% of BTC value</div>
        </div>
        <span style="color:var(--text-muted);font-size:14px;">→</span>
      </div>
      <!-- Step 2 -->
      <div style="display:flex;align-items:center;gap:6px;flex-shrink:0;">
        <div style="padding:12px 18px;border-radius:8px;background:var(--bg);border:1px solid rgba(242,94,19,0.2);min-width:120px;text-align:center;">
          <div style="font-size:12px;font-weight:600;color:var(--text);line-height:1.4;">Pool Funds<br>Remaining</div>
          <div style="font-size:9px;color:var(--text-muted);margin-top:5px;">70% from lenders</div>
        </div>
        <span style="color:var(--text-muted);font-size:14px;">→</span>
      </div>
      <!-- Step 3 -->
      <div style="display:flex;align-items:center;gap:6px;flex-shrink:0;">
        <div style="padding:12px 18px;border-radius:8px;background:var(--bg);border:1px solid rgba(45,212,191,0.2);min-width:120px;text-align:center;">
          <div style="font-size:12px;font-weight:600;color:var(--text);line-height:1.4;">Buy BTC<br>on DEX</div>
          <div style="font-size:9px;color:var(--text-muted);margin-top:5px;">full amount</div>
        </div>
        <span style="color:var(--text-muted);font-size:14px;">→</span>
      </div>
      <!-- Step 4 -->
      <div style="display:flex;align-items:center;gap:6px;flex-shrink:0;">
        <div style="padding:12px 18px;border-radius:8px;background:var(--bg);border:1px solid rgba(45,212,191,0.2);min-width:120px;text-align:center;">
          <div style="font-size:12px;font-weight:600;color:var(--text);line-height:1.4;">Deposit BTC<br>in Vault</div>
          <div style="font-size:9px;color:var(--text-muted);margin-top:5px;">locked as collateral</div>
        </div>
      </div>
    </div>
    <div style="font-size:11px;color:var(--text-dim);margin-top:14px;">Collateral is released only after full repayment.</div>
  </div>
</div>
```

---

### Task 5: Build View 1 — Horizontal parameter bar

**Files:**
- Modify: `bitmor-dashboard.html` — inside `#view-calculator`, after intro block

**Step 1:** Add section label (from JSX:113 SL component + JSX:209):

```html
<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
  <span style="font-size:12px;color:var(--accent);font-weight:600;letter-spacing:0.1em;">01</span>
  <span style="font-size:12px;color:var(--text-muted);letter-spacing:0.06em;text-transform:uppercase;">Loan Configuration</span>
</div>
<h2 style="font-size:28px;font-weight:600;color:var(--text);margin:0 0 6px;">What does it really cost?</h2>
<p style="font-size:14px;color:var(--text-dim);margin:0 0 24px;line-height:1.6;max-width:620px;">See the total cost of a Bitmor loan at today's price, including interest, PUT hedge, and estimated savings from rolling down.</p>
```

**Step 2:** Add horizontal parameter bar card (from JSX:212-239). This is a single card with flex row containing: BTC Spot display, divider, Interest Rate slider, divider, Down Payment pills, divider, fixed Loan Term badge:

```html
<div class="card" style="padding:18px 24px;margin-bottom:24px;">
  <div style="display:flex;align-items:center;gap:28px;flex-wrap:wrap;">
    <!-- BTC Spot (display only) -->
    <div style="flex-shrink:0;">
      <div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:4px;">BTC Spot</div>
      <div id="live-spot-display" style="font-size:22px;font-weight:700;color:var(--green);font-variant-numeric:tabular-nums;">Loading...</div>
    </div>
    <div style="width:1px;height:40px;background:var(--border);flex-shrink:0;"></div>
    <!-- Interest Rate slider -->
    <div style="min-width:180px;flex:1 1 180px;">
      <div style="margin-bottom:16px;">
        <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
          <span style="font-size:12px;color:var(--text-dim);">Annual Interest Rate</span>
          <span id="lbl-apr" style="font-size:13px;color:var(--text);font-weight:600;font-variant-numeric:tabular-nums;">9.0%</span>
        </div>
        <input type="range" id="apr" min="5" max="12" step="0.5" value="9" oninput="calc()">
      </div>
    </div>
    <div style="width:1px;height:40px;background:var(--border);flex-shrink:0;"></div>
    <!-- Down Payment pills -->
    <div style="flex-shrink:0;">
      <div style="font-size:11px;color:var(--text-dim);margin-bottom:6px;">Down Payment</div>
      <div id="dp-pills" style="display:flex;gap:6px;">
        <button class="pill-btn" onclick="selectDP(20,this)">20%</button>
        <button class="pill-btn active" onclick="selectDP(30,this)">30%</button>
        <button class="pill-btn" onclick="selectDP(40,this)">40%</button>
        <button class="pill-btn" onclick="selectDP(50,this)">50%</button>
      </div>
    </div>
    <div style="width:1px;height:40px;background:var(--border);flex-shrink:0;"></div>
    <!-- Loan Term (fixed) -->
    <div style="flex-shrink:0;">
      <div style="font-size:11px;color:var(--text-dim);margin-bottom:6px;">Loan Term</div>
      <div style="padding:5px 12px;border-radius:6px;border:1px solid var(--accent);background:var(--persimmon-dim);color:var(--accent);font-size:12px;font-weight:500;">12 months</div>
    </div>
  </div>
</div>
```

**Step 3:** Add CSS for pill buttons (from JSX:116):

```css
.pill-btn {
  padding: 6px 14px; border-radius: 6px;
  border: 1px solid var(--border); background: transparent;
  color: var(--text-dim); font-size: 13px; font-weight: 500;
  cursor: pointer; font-family: var(--font);
}
.pill-btn:hover { border-color: var(--accent); color: var(--text); }
.pill-btn.active {
  border-color: var(--accent); background: var(--persimmon-dim); color: var(--accent);
}
```

---

### Task 6: Build View 1 — Hero effective price card

**Files:**
- Modify: `bitmor-dashboard.html` — inside `#view-calculator`, after parameter bar

**Step 1:** Add hero card (from JSX:242-280). This card has a gradient background, glow circle, and two-column layout (left = price info, right = stacked bar):

```html
<div id="hero-card" class="card" style="background:linear-gradient(135deg,#0f1d38 0%,#0a1428 100%);border:1px solid var(--border-light);position:relative;overflow:hidden;margin-bottom:20px;padding:32px 36px;">
  <!-- Glow circle -->
  <div style="position:absolute;top:-60px;right:-60px;width:200px;height:200px;border-radius:50%;background:var(--persimmon-glow);filter:blur(100px);opacity:0.25;"></div>
  <div style="position:relative;">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:20px;">
      <!-- Left: price info -->
      <div>
        <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.1em;margin-bottom:12px;">Effective price per BTC</div>
        <div style="display:flex;align-items:baseline;gap:16px;margin-bottom:6px;">
          <span id="hero-eff-price" style="font-size:48px;font-weight:700;color:var(--text);font-variant-numeric:tabular-nums;letter-spacing:-0.02em;">—</span>
          <span id="hero-prem-pct" style="font-size:18px;font-weight:700;font-variant-numeric:tabular-nums;">—</span>
        </div>
        <div id="hero-breakdown" style="font-size:13px;color:var(--text-dim);line-height:1.8;font-variant-numeric:tabular-nums;">—</div>
      </div>
      <!-- Right: stacked bar -->
      <div style="min-width:280px;flex:0 0 280px;">
        <div style="font-size:10px;color:var(--text-muted);margin-bottom:8px;">Cost composition</div>
        <div id="hero-bar" style="display:flex;height:36px;border-radius:8px;overflow:hidden;border:1px solid var(--border);">
          <!-- Filled dynamically by calc() -->
        </div>
        <div id="hero-bar-labels" style="display:flex;justify-content:space-between;margin-top:8px;font-size:10px;color:var(--text-dim);">
          <!-- Filled dynamically by calc() -->
        </div>
      </div>
    </div>
  </div>
</div>
```

---

### Task 7: Build View 1 — Three detail cards + PUT pricing bar

**Files:**
- Modify: `bitmor-dashboard.html` — inside `#view-calculator`, after hero card

**Step 1:** Add three detail cards in a row (from JSX:283-319):

```html
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-bottom:20px;">
  <!-- Upfront Cost -->
  <div class="card" style="padding:20px;">
    <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.1em;margin-bottom:12px;">Upfront Cost</div>
    <div id="detail-upfront-total" style="font-size:24px;font-weight:700;color:var(--text);font-variant-numeric:tabular-nums;margin-bottom:10px;">—</div>
    <div id="detail-upfront-lines" style="font-size:11px;color:var(--text-dim);line-height:1.8;">—</div>
    <div style="border-top:1px solid var(--border);margin-top:10px;padding-top:8px;font-size:10px;color:var(--text-muted);">Paid at origination</div>
  </div>
  <!-- 12-Month Repayment -->
  <div class="card" style="padding:20px;cursor:pointer;" onclick="document.getElementById('amort-section').scrollIntoView({behavior:'smooth',block:'start'})">
    <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.1em;margin-bottom:12px;">12-Month Repayment</div>
    <div id="detail-monthly" style="font-size:24px;font-weight:700;color:var(--accent);font-variant-numeric:tabular-nums;margin-bottom:10px;">—</div>
    <div id="detail-repay-lines" style="font-size:11px;color:var(--text-dim);line-height:1.8;">—</div>
    <div style="border-top:1px solid var(--border);margin-top:10px;padding-top:8px;font-size:10px;color:var(--accent);font-weight:500;">View schedule ↓</div>
  </div>
  <!-- Expected Recovery -->
  <div class="card recovery-card" onclick="Nav.switchTab('research')" style="padding:20px;background:var(--green-dim);border-color:rgba(34,197,94,0.2);cursor:pointer;height:100%;">
    <div style="font-size:10px;color:var(--green);text-transform:uppercase;letter-spacing:0.1em;margin-bottom:12px;font-weight:600;">Expected Recovery</div>
    <div id="detail-recovery-total" style="font-size:24px;font-weight:700;color:var(--green);font-variant-numeric:tabular-nums;margin-bottom:10px;">—</div>
    <div id="detail-recovery-lines" style="font-size:11px;color:var(--text-dim);line-height:1.7;">—</div>
    <div style="border-top:1px solid rgba(34,197,94,0.13);margin-top:10px;padding-top:8px;font-size:10px;color:var(--green);font-weight:500;">How does this work? →</div>
  </div>
</div>
```

**Step 2:** Add PUT pricing bar (from JSX:322-353):

```html
<div class="card" style="padding:16px 20px;border-color:rgba(242,94,19,0.2);background:var(--persimmon-dim);margin-bottom:20px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
    <div style="display:flex;align-items:center;gap:8px;">
      <div style="width:6px;height:6px;border-radius:50%;background:var(--accent);"></div>
      <span style="font-size:10px;color:var(--accent);text-transform:uppercase;letter-spacing:0.1em;font-weight:600;">PUT Option Cost</span>
    </div>
    <span id="put-data-source" style="font-size:9px;color:var(--green);">● Loading...</span>
  </div>
  <div id="put-grid" style="display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);border-radius:8px;overflow:hidden;">
    <!-- 4 cells filled by calc(): Strike, Deribit Mark, IV, Expiry -->
  </div>
  <div id="put-footer" style="border-top:1px solid var(--border);margin-top:12px;padding-top:10px;display:flex;justify-content:space-between;align-items:center;">
    <!-- BS theoretical + upfront % filled by calc() -->
  </div>
  <div id="put-note" style="font-size:10px;color:var(--text-dim);margin-top:8px;line-height:1.5;">Strike = financed principal. Purchased at origination. Eliminates price-based liquidation for the full loan term.</div>
</div>
```

---

### Task 8: Build View 1 — Amortization table

**Files:**
- Modify: `bitmor-dashboard.html` — inside `#view-calculator`, after PUT pricing bar

**Step 1:** Add amortization section (from JSX:354-371):

```html
<div id="amort-section" style="margin-top:40px;">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
    <span style="font-size:12px;color:var(--accent);font-weight:600;letter-spacing:0.1em;">02</span>
    <span style="font-size:12px;color:var(--text-muted);letter-spacing:0.06em;text-transform:uppercase;">Repayment Schedule</span>
  </div>
  <h2 style="font-size:22px;font-weight:600;color:var(--text);margin:0 0 4px;">Month-by-month amortization</h2>
  <p style="font-size:13px;color:var(--text-dim);margin:0 0 20px;">Each payment covers accrued interest first, then reduces principal. Balance reaches zero at month 12.</p>
  <div class="card" style="padding:20px 24px;overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums;">
      <thead><tr>
        <th style="text-align:center;padding:10px 12px;color:var(--text-muted);font-weight:500;border-bottom:1px solid var(--border);font-size:10px;text-transform:uppercase;letter-spacing:0.06em;">Mo.</th>
        <th style="text-align:right;padding:10px 12px;color:var(--text-muted);font-weight:500;border-bottom:1px solid var(--border);font-size:10px;text-transform:uppercase;letter-spacing:0.06em;">Payment</th>
        <th style="text-align:right;padding:10px 12px;color:var(--text-muted);font-weight:500;border-bottom:1px solid var(--border);font-size:10px;text-transform:uppercase;letter-spacing:0.06em;">Principal</th>
        <th style="text-align:right;padding:10px 12px;color:var(--text-muted);font-weight:500;border-bottom:1px solid var(--border);font-size:10px;text-transform:uppercase;letter-spacing:0.06em;">Interest</th>
        <th style="text-align:right;padding:10px 12px;color:var(--text-muted);font-weight:500;border-bottom:1px solid var(--border);font-size:10px;text-transform:uppercase;letter-spacing:0.06em;">Balance</th>
        <th style="text-align:right;padding:10px 12px;color:var(--text-muted);font-weight:500;border-bottom:1px solid var(--border);font-size:10px;text-transform:uppercase;letter-spacing:0.06em;">% Paid</th>
      </tr></thead>
      <tbody id="amort-body"></tbody>
    </table>
  </div>
</div>
```

Table row styling (applied in JS `calc()` function): center-aligned month (color: `--text-dim`), right-aligned values, principal in `--accent`, interest in `--text-dim`, balance in `--text` weight 500, % paid in `--green`. Row border: `1px solid rgba(26,42,74,0.13)`. From JSX:361-368.

---

### Task 9: Build View 2 — Context banner + hero heading

**Files:**
- Modify: `bitmor-dashboard.html` — inside `#view-research`

**Step 1:** Add context banner (from JSX:385-396):

```html
<div class="card" style="padding:14px 20px;background:var(--persimmon-dim);border-color:rgba(242,94,19,0.2);margin-bottom:32px;">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
    <div style="font-size:13px;color:var(--text-dim);">
      Typical PUT cost: <span style="color:var(--accent);font-weight:600;">5-9% of spot</span>
      <span style="color:var(--text-muted);"> → </span>
      After roll-down: <span style="color:var(--green);font-weight:600;">~34% recovered</span>
      <span style="color:var(--text-muted);"> → </span>
      Net hedge cost: <span style="color:var(--text);font-weight:500;">~5-6% of BTC</span>
    </div>
    <div style="font-size:11px;color:var(--text-muted);">70% LTV · 12mo · 10% APR</div>
  </div>
</div>
```

**Step 2:** Add hero heading (from JSX:398-401):

```html
<div style="text-align:center;margin-bottom:40px;">
  <div style="font-size:12px;color:var(--accent);font-weight:600;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:12px;">PUT Roll-Down Research</div>
  <h1 style="font-size:36px;font-weight:700;color:var(--text);margin:0 0 8px;">Rolling down cuts the cost of hedging</h1>
  <p style="font-size:15px;color:var(--text-dim);margin:0 0 32px;max-width:560px;margin-left:auto;margin-right:auto;line-height:1.6;">As monthly payments reduce debt, the PUT strike rolls down with it. The old option is worth more than the new one. You pocket the difference.</p>
</div>
```

---

### Task 10: Build View 2 — Path Explorer section

**Files:**
- Modify: `bitmor-dashboard.html` — inside `#view-research`, after hero heading

**Step 1:** Add section label + path nav header (from JSX:404-415):

```html
<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
  <span style="font-size:12px;color:var(--accent);font-weight:600;letter-spacing:0.1em;">01</span>
  <span style="font-size:12px;color:var(--text-muted);letter-spacing:0.06em;text-transform:uppercase;">Path Explorer</span>
</div>
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
  <div>
    <h2 style="font-size:22px;font-weight:600;color:var(--text);margin:0 0 4px;">Single path deep-dive</h2>
    <p style="font-size:13px;color:var(--text-dim);margin:0;">Explore individual loan outcomes to see roll-down mechanics in action.</p>
  </div>
  <div style="display:flex;align-items:center;gap:8px;">
    <button class="path-nav-btn" onclick="PathExplorer.prev()">←</button>
    <div style="padding:6px 14px;border-radius:6px;background:var(--bg-card);border:1px solid var(--border);font-size:11px;color:var(--text-dim);font-variant-numeric:tabular-nums;">Path <span id="path-num" style="color:var(--text);font-weight:600;">#1</span> of <span id="path-total">2,494</span></div>
    <button class="path-nav-btn" onclick="PathExplorer.next()">→</button>
    <button class="path-random-btn" onclick="PathExplorer.random()"><span style="font-size:13px;">↻</span> Random</button>
  </div>
</div>
```

**Step 2:** Add CSS for path nav buttons (from JSX:411-414):

```css
.path-nav-btn {
  width: 32px; height: 32px; border-radius: 6px;
  border: 1px solid var(--border); background: var(--bg-card);
  color: var(--text-dim); font-size: 14px; cursor: pointer;
  font-family: var(--font); display: flex; align-items: center; justify-content: center;
}
.path-nav-btn:hover { border-color: var(--accent); color: var(--text); }
.path-random-btn {
  padding: 6px 14px; border-radius: 6px;
  border: 1px solid var(--border); background: var(--bg-card-hover);
  color: var(--text); font-size: 11px; font-weight: 500;
  cursor: pointer; font-family: var(--font); display: flex; align-items: center; gap: 5px;
}
.path-random-btn:hover { border-color: var(--accent); }
```

**Step 3:** Add Plotly chart container + two-column layout below (from JSX:419-483):

```html
<!-- Debt vs Strike chart -->
<div class="card" style="margin-bottom:16px;">
  <div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:4px;">Debt Balance vs PUT Strike</div>
  <div style="font-size:11px;color:var(--text-dim);margin-bottom:16px;">The gap between strike (dashed) and debt (solid) is where roll savings come from.</div>
  <div id="rolldown-chart" style="width:100%;height:240px;"></div>
</div>

<!-- Cash flows + summary cards -->
<div style="display:grid;grid-template-columns:1fr 300px;gap:16px;margin-bottom:16px;">
  <!-- Left: cash flow table -->
  <div class="card" style="padding:16px 20px;overflow-x:auto;">
    <div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:12px;">Roll-down cash flows</div>
    <table style="width:100%;border-collapse:collapse;font-size:11px;font-variant-numeric:tabular-nums;">
      <thead><tr>
        <th style="text-align:center;padding:6px 10px;color:var(--text-muted);font-weight:500;border-bottom:1px solid var(--border);font-size:9px;text-transform:uppercase;letter-spacing:0.06em;">Mo.</th>
        <th style="text-align:left;padding:6px 10px;color:var(--text-muted);font-weight:500;border-bottom:1px solid var(--border);font-size:9px;text-transform:uppercase;letter-spacing:0.06em;">Action</th>
        <th style="text-align:right;padding:6px 10px;color:var(--text-muted);font-weight:500;border-bottom:1px solid var(--border);font-size:9px;text-transform:uppercase;letter-spacing:0.06em;">Saving</th>
        <th style="text-align:right;padding:6px 10px;color:var(--text-muted);font-weight:500;border-bottom:1px solid var(--border);font-size:9px;text-transform:uppercase;letter-spacing:0.06em;">Cumulative</th>
      </tr></thead>
      <tbody id="path-cf-table"></tbody>
    </table>
  </div>

  <!-- Right: summary cards stack -->
  <div style="display:flex;flex-direction:column;gap:12px;">
    <!-- Recovery hero -->
    <div id="path-recovery-hero" class="card" style="padding:16px;background:var(--green-dim);border-color:rgba(34,197,94,0.2);text-align:center;">
      <!-- Filled by PathExplorer.render() -->
    </div>
    <!-- Net cost hero -->
    <div id="path-netcost-hero" class="card" style="padding:16px;text-align:center;">
      <!-- Filled by PathExplorer.render() -->
    </div>
    <!-- Secondary 2-col -->
    <div id="path-secondary" style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
      <!-- Filled by PathExplorer.render() -->
    </div>
    <!-- Tertiary -->
    <div id="path-tertiary" class="card" style="padding:10px 12px;">
      <!-- Filled by PathExplorer.render() -->
    </div>
  </div>
</div>
```

---

### Task 11: Build View 2 — Aggregate Results section

**Files:**
- Modify: `bitmor-dashboard.html` — inside `#view-research`, after path explorer

**Step 1:** Add section label + heading + tier sub-tabs (from JSX:487-490, JSX:118):

```html
<div style="margin-top:40px;">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
    <span style="font-size:12px;color:var(--accent);font-weight:600;letter-spacing:0.1em;">02</span>
    <span style="font-size:12px;color:var(--text-muted);letter-spacing:0.06em;text-transform:uppercase;">Aggregate Results</span>
  </div>
  <h2 style="font-size:22px;font-weight:600;color:var(--text);margin:0 0 6px;">Three levels of evidence</h2>
  <p style="font-size:13px;color:var(--text-dim);margin:0 0 20px;">Three tiers of evidence, from pure historical to fully simulated. Tier 1 uses only real market data.</p>

  <!-- Tier sub-tabs (underline style from JSX:118) -->
  <div id="tier-tabs" style="display:flex;border-bottom:1px solid var(--border);margin-bottom:24px;">
    <button class="tier-tab active" data-tier="1" onclick="TierView.switchTier(1)">Historical</button>
    <button class="tier-tab" data-tier="2" onclick="TierView.switchTier(2)">Hist + Simulated</button>
    <button class="tier-tab" data-tier="3" onclick="TierView.switchTier(3)">Forward Sim</button>
  </div>
```

**Step 2:** Add CSS for tier tabs:

```css
.tier-tab {
  padding: 10px 20px; background: none; border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-dim); font-size: 13px; font-weight: 500;
  cursor: pointer; font-family: var(--font);
}
.tier-tab:hover { color: var(--text); }
.tier-tab.active { border-bottom-color: var(--accent); color: var(--text); }
```

**Step 3:** Add tier badge + description (from JSX:493-495), stats card (from JSX:499-513), recovery range bar (from JSX:516-535), one-liner insight (from JSX:538-540):

```html
  <!-- Tier badge + desc -->
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">
    <span id="tier-badge" class="tier-badge"></span>
    <span id="tier-desc" style="font-size:13px;color:var(--text-dim);line-height:1.5;"></span>
  </div>

  <!-- Stats card (gradient bg) -->
  <div class="card" style="padding:20px 24px;margin-bottom:16px;background:linear-gradient(135deg,#0f1d38,#0a1428);border-color:var(--border-light);">
    <div id="tier-stats-grid" style="display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--border);border-radius:10px;overflow:hidden;margin-bottom:20px;">
      <!-- 5 stat cells filled by TierView -->
    </div>

    <!-- Recovery range bar -->
    <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:10px;">Recovery range</div>
    <div id="tier-range-bar" style="display:flex;align-items:center;gap:16px;">
      <!-- Filled by TierView -->
    </div>

    <!-- One-liner -->
    <div id="tier-insight" style="font-size:12px;color:var(--text-dim);margin-top:16px;padding-top:14px;border-top:1px solid var(--border);line-height:1.6;"></div>
  </div>

  <!-- Chart view toggle + chart container -->
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
    <div id="tier-chart-title" style="font-size:13px;font-weight:600;color:var(--text);"></div>
    <div style="display:flex;gap:0;border:1px solid var(--border);border-radius:6px;overflow:hidden;">
      <button class="chart-toggle active" data-mode="scatter" onclick="TierView.setChartMode('scatter')">Scatter</button>
      <button class="chart-toggle" data-mode="dist" onclick="TierView.setChartMode('dist')">Distribution</button>
    </div>
  </div>
  <div class="card" style="margin-bottom:20px;">
    <div id="tier-chart-desc" style="font-size:11px;color:var(--text-dim);margin-bottom:14px;"></div>
    <div id="tier-chart" style="width:100%;height:400px;"></div>
    <!-- Insight callout (scatter only) -->
    <div id="tier-chart-callout" style="margin-top:16px;padding:12px 16px;border-radius:8px;background:var(--bg);border:1px solid var(--border);display:flex;gap:12px;align-items:flex-start;"></div>
  </div>
</div>
```

**Step 4:** Add CSS for chart toggle and tier badge:

```css
.chart-toggle {
  padding: 5px 14px; background: transparent; border: none;
  color: var(--text-dim); font-size: 11px; font-weight: 500;
  cursor: pointer; font-family: var(--font);
}
.chart-toggle:hover { color: var(--text); }
.chart-toggle.active { background: var(--bg-card-hover); color: var(--text); }
.tier-badge {
  display: inline-block; padding: 3px 10px; border-radius: 4px;
  font-size: 10px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
}
```

---

### Task 12: Build View 2 — Collapsible Methodology

**Files:**
- Modify: `bitmor-dashboard.html` — inside `#view-research`, after aggregate results

**Step 1:** Add collapsible methodology (from JSX:626-644):

```html
<div style="margin-top:40px;">
  <div class="card" style="padding:14px 20px;cursor:pointer;" onclick="toggleMethodology()">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <div style="display:flex;align-items:center;gap:10px;">
        <span style="font-size:12px;color:var(--accent);font-weight:600;letter-spacing:0.1em;">03</span>
        <span style="font-size:12px;color:var(--text-muted);letter-spacing:0.06em;text-transform:uppercase;">Methodology</span>
      </div>
      <span id="method-chevron" style="font-size:14px;color:var(--text-muted);transition:transform 0.2s;">▾</span>
    </div>
    <div id="method-collapsed-desc" style="font-size:12px;color:var(--text-dim);margin-top:4px;">Key assumptions, data sources, and limitations behind these numbers.</div>
  </div>
  <div id="method-expanded" style="display:none;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px;">
    <div class="card"><div style="font-size:13px;font-weight:600;color:var(--text);margin-bottom:8px;">Option Pricing</div><div style="font-size:12px;color:var(--text-dim);line-height:1.6;">Black-Scholes, European cash-settled PUTs. Risk-free rate assumed zero (crypto convention). IV from SVI surface.</div></div>
    <div class="card"><div style="font-size:13px;font-weight:600;color:var(--text);margin-bottom:8px;">IV Surface</div><div style="font-size:12px;color:var(--text-dim);line-height:1.6;">Deribit options trades, 700+ days of data. SVI parameterization, 26 moneyness points.</div></div>
    <div class="card"><div style="font-size:13px;font-weight:600;color:var(--text);margin-bottom:8px;">GBM Calibration</div><div style="font-size:12px;color:var(--text-dim);line-height:1.6;">~3yr Binance BTCUSDT hourly candles. Daily log returns for drift and vol estimation.</div></div>
    <div class="card"><div style="font-size:13px;font-weight:600;color:var(--text);margin-bottom:8px;">Assumptions</div><div style="font-size:12px;color:var(--text-dim);line-height:1.6;">IV held constant for forward projections. No transaction fees. Monthly roll checkpoints. Constant GBM parameters.</div></div>
  </div>
</div>
```

---

### Task 13: Update Nav JS module

**Files:**
- Modify: `bitmor-dashboard.html` — `Nav` module (lines 22289-22333)

**Step 1:** Replace the Nav module with simplified 2-view version:

```javascript
const Nav = (() => {
  const viewIds = { calculator: 'view-calculator', research: 'view-research' };
  let currentView = 'calculator';
  const initCallbacks = { calculator: null, research: null };

  function registerInit(viewId, fn) { initCallbacks[viewId] = fn; }

  function switchTab(viewId) {
    document.querySelectorAll('.view-content').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
    document.getElementById(viewIds[viewId]).style.display = 'block';
    document.querySelector(`[data-view="${viewId}"]`).classList.add('active');
    currentView = viewId;
    history.replaceState(null, '', '#' + viewId);
    if (initCallbacks[viewId]) {
      initCallbacks[viewId]();
      initCallbacks[viewId] = null;
    }
  }

  function initFromHash() {
    const hash = location.hash.replace('#', '');
    if (viewIds[hash]) switchTab(hash);
  }

  return { switchTab, registerInit, initFromHash };
})();
```

---

### Task 14: Update calc() function for new DOM structure

**Files:**
- Modify: `bitmor-dashboard.html` — `calc()` function (lines 22361-22546)

**Step 1:** Simplify `calc()` — hardcode `_btcAmt = 1`, `_term = 12`. Remove BTC amount / IV slider reads. Update all `document.getElementById()` calls to target the new DOM element IDs from Tasks 5-8.

Key changes:
- Read spot from stored `_liveSpot` instead of slider
- Read APR from `#apr` slider (kept)
- Read DP from `_dpPct` (set by pill buttons)
- Populate `#hero-eff-price`, `#hero-prem-pct`, `#hero-breakdown`, `#hero-bar`, `#hero-bar-labels`
- Populate `#detail-upfront-total`, `#detail-upfront-lines`, `#detail-monthly`, `#detail-repay-lines`, `#detail-recovery-total`, `#detail-recovery-lines`
- Populate `#put-grid` (4 cells), `#put-footer`
- Populate `#amort-body` (same loop, updated row styling per JSX:361-368)
- Use Deribit engine as before (snapshot + live), but always 1 BTC inverse 12mo

**Step 2:** Simplify `selectDP` (replaces `selectDP2`):

```javascript
function selectDP(pct, btn) {
  _dpPct = pct / 100;
  document.querySelectorAll('.pill-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  calc();
}
```

**Step 3:** Remove `selectBTCAmt()`, `selectTerm()`, `updateTermButtons()` functions entirely.

**Step 4:** Simplify `fetchBTCSpot()` to update `#live-spot-display` and store the price for calc.

---

### Task 15: Create PathExplorer JS module (replaces Tab1)

**Files:**
- Modify: `bitmor-dashboard.html` — `Tab1` module (lines 22775-23013)

**Step 1:** Rename `Tab1` to `PathExplorer`. Keep `computeAmortization()`, `reconstructRollSchedule()`, `reconstructCashFlows()` untouched. Update `renderPath()` to target new DOM IDs:

- Path nav: `#path-num`, `#path-total`
- Chart: `#rolldown-chart` (same Plotly, restyle to JSX aesthetic — persimmon line width 2.5, teal dashed strike)
- Cash flow table: `#path-cf-table` (table rows instead of `.cf-event` divs)
- Summary cards: `#path-recovery-hero`, `#path-netcost-hero`, `#path-secondary`, `#path-tertiary`

**Step 2:** Add `prev()`, `next()`, `random()` navigation methods (from JSX:411-414 behavior):

```javascript
let _pathSeed = 1;
function prev() { _pathSeed = Math.max(1, _pathSeed - 1); renderPath(DataStore.getRandomPath(null, _pathSeed)); }
function next() { _pathSeed++; renderPath(DataStore.getRandomPath(null, _pathSeed)); }
function random() { renderPath(DataStore.getRandomPath()); }
```

---

### Task 16: Create TierView JS module (replaces Tab2)

**Files:**
- Modify: `bitmor-dashboard.html` — `Tab2` module (lines 23018-23238)

**Step 1:** Rename `Tab2` to `TierView`. Keep `renderTimeSeries()`, `renderScatter()`, `renderHistogram()` untouched (same Plotly pipelines). Add:

- `switchTier(n)` — updates `#tier-badge`, `#tier-desc`, `#tier-stats-grid`, `#tier-range-bar`, `#tier-insight`, re-renders chart
- `setChartMode(mode)` — toggles scatter/dist, updates `#tier-chart-title`, `#tier-chart-desc`, renders into `#tier-chart`
- Chart toggle button active state management
- Tier tab active state management

**Step 2:** Populate stats grid cells (from JSX:502-512) — each cell is a div with `background:var(--bg-card)`, padding `14px`, containing label (8px uppercase muted) + value (18px weight 700) + optional sub-text.

**Step 3:** Populate range bar (from JSX:517-534) — 5th percentile left, gradient bar with median marker, 95th percentile right.

**Step 4:** Populate insight callout (from JSX:613-619) — green circle with ↑, explanation text.

---

### Task 17: Add toggleMethodology() and footer, wire startup

**Files:**
- Modify: `bitmor-dashboard.html` — bottom of script section

**Step 1:** Add methodology toggle:

```javascript
function toggleMethodology() {
  const el = document.getElementById('method-expanded');
  const chevron = document.getElementById('method-chevron');
  const desc = document.getElementById('method-collapsed-desc');
  const isOpen = el.style.display === 'grid';
  el.style.display = isOpen ? 'none' : 'grid';
  chevron.style.transform = isOpen ? 'none' : 'rotate(180deg)';
  desc.style.display = isOpen ? 'block' : 'none';
}
```

**Step 2:** Place footer **after** `</div><!-- .container -->`, outside `.container` so it spans full viewport width (matching JSX:655 where the footer is at the App level, not inside V1/V2):

```html
<footer style="border-top:1px solid var(--border);padding:24px 32px;margin-top:48px;display:flex;justify-content:space-between;align-items:center;">
  <div style="font-size:12px;color:var(--text-muted);">bitmor.xyz — Educational tool. Not financial advice.</div>
  <a href="https://bitmor.xyz/loans" target="_blank" rel="noopener" style="font-size:12px;color:var(--accent);text-decoration:none;font-weight:500;">Join the Loan Waitlist →</a>
</footer>
```

**Step 3:** Update startup sequence:

```javascript
Nav.registerInit('research', () => { TierView.init(); PathExplorer.init(); });
priceSource = 'snapshot';
calc();
fetchBTCSpot();
fetchDeribitPrices();
Nav.initFromHash();
window.addEventListener('popstate', Nav.initFromHash);
```

---

### Task 18: Clean up removed CSS and HTML

**Step 1:** Remove CSS classes no longer used:
- `.sticky-tabs`, `.tabs`, `.main-tab-btn` (replaced by `.top-nav`)
- `.logo`, `.logo-mark`, `.logo-text`, `.logo-sub` (replaced by `.nav-logo`)
- `.section-label`, `.section h2`, `.section .desc` (replaced by inline styles matching JSX)
- `.dark-card` (merged into `.card`)
- `.field` (removed — no more slider fields in old format)
- `.formula-block` (removed)
- `.payout-pill` (removed)
- `.scenario-badge` (removed)
- `.dp-btn`, `.btn-group` (replaced by `.pill-btn`)
- `.cf-timeline`, `.cf-event`, `.cf-month`, `.cf-desc`, `.cf-flow`, `.cf-running` (replaced by table)
- `.path-badge`, `.badge-tier`, `.reshuffle-btn` (replaced by path nav)
- `.method-section`, `.flow-diagram`, `.flow-step`, `.flow-box`, `.flow-arrow`, `.flow-sub` (Tab 3 removed)
- `.cascade-grid`, `.cascade-box`, `.cascade-arrow` (Tab 3 removed)
- `.irm-curve` (Tab 3 removed)
- `.cross-link` (not used in new design)
- `.disclaimer-box` (removed)
- `.tab-intro` (replaced by inline styles)
- `.tier-narrative` (replaced by inline description)
- `.highlight-flash` (removed)

**Step 2:** Remove all `#tab-math` and `#tab-methodology` HTML content.

**Step 3:** Update `.card` CSS class to match JSX Card component (JSX:112):
```css
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 28px;
}
```

**Step 4:** Verify in browser — both views render, charts load, Deribit data populates, amortization table fills correctly. Commit.
