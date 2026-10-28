---
title: "Personal Investment Workbench v2 — Design Document"
subtitle: "Thesis tracking, portfolio, position plans, trade review and portfolio journal (version 2.27.0)"
date: "2026-10-13"
---

# 1. Purpose and Design Principles

The workbench is a personal investment research tool built as a course project. It turns "write a report" into "keep tracking a small set of testable investment theses", and keeps your own holdings, price discipline, trade reasons and reviews in the same place.

| Principle | How it is applied |
|---|---|
| The thesis is the unit of work | Each analysis produces a structured thesis state (core assumptions, status, kill criteria). The written report is only the narrative carrier. |
| Code decides what code can decide | Change detection, thesis health, plan status, review checklist and period digest are all computed by code, not by the model. |
| No change, no tokens | When nothing material changed, the system writes a one-line "check" record and makes no model call. |
| Personal records stay private | Decision logs, trade reasons and journal entries are never sent to the model. Only "comment / source / question" notes are passed, labelled as unverified analyst notes. |
| Evidence discipline | The model may cite only the evidence it is given. When evidence is missing it must write EVIDENCE INSUFFICIENT instead of inventing support. |
| English UI, Chinese on demand | The interface is English (course requirement). Analysis text can be translated to Chinese on request. |

# 2. Architecture

```
OpenBB (yfinance) -> Snapshot -> signals.compute_delta / classify
                                   | none -> Review(kind=check)   free, deterministic
                                   | minor / material
                                   v
                   prompts + provider (Gemini) -> Review(baseline | update | rebaseline)
                                                    |
Broker CSV -> Holding / Trade --+                   |
Your input -> Plan / TradeReason / Note / JournalEntry
                                v                   v
                       FastAPI (/api/v1)  <---------+ -> frontend (index.html)
```

| Module | Responsibility |
|---|---|
| `app/adapters/` | OpenBB adapter (openbb pinned to 4.7.2, yfinance provider); multi-route news fallback |
| `app/core/signals.py` | Change detection, fingerprint, evidence basis, data gaps, code-computed derived valuation metrics |
| `app/core/thesis.py` | Thesis health (Intact / Watch / At risk), sector KPI hints |
| `app/core/plan.py` | Position plan status |
| `app/core/translate.py` | Extraction and re-insertion of translatable text fields |
| `app/ai/` | Schemas, prompts (version tracker-1.7), provider with Gemini model chain |
| `app/portfolio.py` | Broker CSV parsing (holdings, trades) and symbol normalisation |
| `app/service.py` | Refresh orchestration: validation, caching, choosing the analysis type, calling the model |
| `app/security.py` | Host / Origin checks, upload limit, response headers |
| `app/core/calendar.py` | Market-local trade dates, quick round-trip detection |
| `app/api/routes.py`, `journal.py`, `calendar.py` | HTTP endpoints |
| `app/static/index.html` | Frontend, one file of plain JavaScript |
| `tests/` | Pure-Python unit tests and a front-end smoke test with a simulated DOM |

Technology: FastAPI, SQLAlchemy 2 on SQLite, pydantic v2, OpenBB 4.7.2, Google Gemini through the google-genai SDK, vanilla JavaScript.

# 3. Data Model

| Table | Purpose |
|---|---|
| `companies` | Symbol, name, group (holding / watching / idea / archived) |
| `snapshots` | Normalised evidence for each refresh, plus price and fingerprint |
| `reviews` | The core table. Each row is a complete, self-contained thesis state: `kind` (baseline / rebaseline / update / check), `level`, `view`, `view_change`, `one_liner`, `state`, `changes`, `narrative`, `delta`, `usage`, and an optional Chinese translation `zh`. |
| `notes` | Per-company notes: decision log, comment, source, question. A note can attach to one assumption, and stores the price at the time and a revisit date. |
| `holdings` | Broker holdings snapshot: quantity, cost, P&L, weight, currency, type (stock / etf / cash) |
| `trades` | Filled orders, de-duplicated by a content hash |
| `plans` | Position plan: strategy, **position logic** (rationale), target and max position, buy zone, target price, stop price, add / trim / exit rules |
| `trade_reasons` | One row per trade: role in the position, what triggered it, a copy of the plan logic, decision date, review date, result and follow-up |
| `journal_entries` | Portfolio journal: type, title, body, related symbols, revisit date, optional event date (for market or world events), and a snapshot of the portfolio when written |

Because every review is self-contained, the timeline is simply the list of reviews, and a version comparison is the difference between two `state` values. Reviews are append-only: an analysis never overwrites an earlier one.

At start-up `ensure_columns()` adds any columns that a newer model has but an old SQLite table lacks, and `normalize_symbols()` rewrites old records such as `BRK.B` to `BRK-B`.

# 4. Thesis Analysis

## 4.1 Thesis state (`reviews.state`)

- **assumptions** (3 to 5): statement, status (holding / strengthened / weakened / broken / unverified), evidence, causal mechanism, materiality, missing evidence, warning trigger, kill criteria, time horizon.
- **profile** (static layer, created only at baseline or rebaseline): classification, business model, moat, drivers, risk mechanisms, bear case, what the price implies.
- **monitor**: indicators to watch and their trigger levels.
- **valuation**: what the price implies and where it differs from consensus.

`view` (constructive / neutral / cautious) is a tracking stance, not a buy or sell recommendation. `view_change` is derived by code from the previous and current `view`; the model's own claim is not trusted.

## 4.2 Thesis health (rule-based, not a model score)

- Any assumption `broken`, or a high-materiality assumption `weakened`: **At risk**.
- Any assumption `weakened`, or a high-materiality assumption still `unverified`: **Watch**.
- Otherwise: **Intact**.

## 4.3 Change detection (`core/signals.py`)

Comparison is against the last analysed anchor, not the previous refresh, so that small drifts cannot stay below the threshold forever.

1. Price effects are stripped first: a valuation multiple change is divided by the price change. If the price rises 20% and P/E rises 20%, nothing new has been learned.
2. Fundamentals and analyst consensus: relative change of 3% or more is minor, 15% or more is material.
3. Valuation (after removing price): 8% minor, 20% material.
4. News: hard keywords (guidance, M&A, earnings beat or miss, management change; English and Chinese) are material. Soft keywords, or three or more new headlines, are minor.
5. All thresholds live in one `Thresholds` object and can be tuned.

If the result is none, a one-line `check` is written (consecutive checks are merged). Otherwise the model is called.

## 4.4 Evidence discipline and code-computed metrics

- **evidence_basis** labels the period of each data group. Statements older than 380 days are treated as stale.
- **data_gaps** lists what is missing.
- **derived** metrics (price-implied valuation figures) are computed in code and passed in, so the model never does arithmetic.
- **Sector KPI hints** are injected by code from industry words. The prompt rules contain no company-specific examples.
- Prompt rules include: period integrity, diagnostic evidence, EVIDENCE INSUFFICIENT when support is missing, and a separate warning trigger versus kill criteria.


## 4.5 Quarterly and annual statements (`core/statements.py`)

Each snapshot stores up to eight reported quarters and five fiscal years of income and cash-flow rows, joined by period end (`snapshot.statements`). Free cash flow is derived from operating cash flow and capex when the source omits it. Margins, growth against the same period a year earlier, and quarter-on-quarter revenue growth are computed in code when read. The Fundamentals tab shows both tables.

For the model, only a compact `derived.quarterly_trend` is sent (last four quarters: growth, gross and operating margin, FCF margin, EPS growth, and the four-quarter change in operating margin); raw statement rows never leave the machine. A newly reported quarter counts as a thesis-relevant change for change detection, but only when the previous analysis already had quarterly data, so upgrading does not trigger a spurious update. Prompt tracker-1.7 tells the model to treat quarters as quarters and to look for direction across several. Snapshots taken before 2.15 have no statements until the company is refreshed once.

# 5. Token and Model Strategy

| Technique | Effect |
|---|---|
| No model call when nothing changed | Most refreshes cost zero |
| Static layer generated once | An update receives only the previous structured thesis plus the delta |
| Cache key = prompt version + model + language + anchor + fundamentals fingerprint + new headlines | Price ticks do not break the cache |
| Compact JSON, separate `system_instruction` | Fewer input tokens, room for context caching |
| Thinking budget `AI_THINKING_BUDGET` (default 1024) | Thinking tokens count against the output limit, so headroom is reserved |
| Output limits: baseline 12000, update 5000; on truncation retry once with the limit x1.5 | A truncated run is not wasted; usage is summed across attempts |
| Model chain `AI_MODEL`, `AI_MODEL_FALLBACKS`, optional `AI_MODEL_BASELINE` | 429 / 503 / 404 move to the next model; any other error stops |
| Only comment / source / question notes go to the model | Decision logs stay private |

The `/usage` endpoint reports today's calls per model, shown at the bottom of the sidebar.

# 6. Portfolio, Plans and Trades

## 6.1 Broker CSV import (Futu layout)

- Both a holdings snapshot and a filled-orders file are supported; GBK and UTF-8 are detected automatically.
- Only filled quantity is counted ("fully filled" and "partly filled then cancelled"); unfilled and cancelled orders are skipped. Trade times are converted from US Eastern or Hong Kong time to UTC.
- Symbols: US codes are unchanged; Hong Kong codes are zero-padded with `.HK`; Singapore shares get `.SI`; US share classes such as `BRK.B` become `BRK-B`, which is what Yahoo and OpenBB expect.
- Re-importing holdings replaces only the currencies present in the file, so a Singapore file never wipes the US or Hong Kong rows.
- Trades are de-duplicated by a content hash, so a repeated import adds zero new rows.
- The import returns a diagnostic report: total rows, unfilled rows, unreadable rows and the number of symbols found. It exists to answer "why does this stock have no trades".
- Type (stock / etf / cash) is guessed from keywords in the name and can be changed in the table. ETFs and cash are not analysed (shown as "Record only").

## 6.1A Where the "why" lives: one logic per position, many actions

A position has one standing logic and many trades. Repeating the logic on every trade was duplicated work, scattered the reasoning and left it disconnected from the plan and notes. The design therefore separates three levels:

| Level | Where | Written | Changes when |
|---|---|---|---|
| Thesis (what is true about the company) | Company: Thesis, Notes | By the model from public data, plus your notes | New evidence |
| Position logic (why you hold it and how you will act) | Plan: strategy, logic, target and max position, price levels, rules | Once per stock, by you | Your logic changes |
| Action (what you did and why now) | Trade: role (open / add / trim / exit / swap), trigger, result, follow-up | Per trade, short | Each trade |

A trade does not retype the position logic. When you add a reason for a trade, the plan's strategy and logic are **copied in as a snapshot** (marked "plan logic") and you only choose the role and note the trigger. The copy is deliberate: if you later change the plan because your logic changed, trades already recorded keep the logic that was true when you acted, so a review judges the decision by what you believed then. The plan card also offers "Use this logic for the N trades without a reason" to fill a whole backlog in one click, and the bulk dialog (6.3) handles trades across symbols. Edit a copied logic on a single trade only when that trade differed from the plan.

Review standards follow the same split: the strategy (Guide) says what to judge a trade by; the plan says what you intended; the trade result says whether it worked.

## 6.2 Position plans (`plans`)

For each symbol you set a holding strategy, the position logic, a **target position** and a **maximum position** as money amounts in the stock's own currency (a personal cap such as 10,000 per stock is easier to reason about than a percentage of a changing total), a buy zone, a target price, a stop price and add / trim / exit rules. The position value is quantity x current price, so no portfolio-value estimate is needed; Portfolio and the plan card still show the broker's percentage weight for context. Plan status is evaluated by code (long positions only):

| Status | Condition |
|---|---|
| Stop breached / Near stop | Price at or below the stop / within 3% of the stop |
| Over max position | Position value above the plan's maximum amount (review concentration) |
| Target reached / Near target | Price at or above the target / within 3% of the target |
| In buy zone | Price at or below the top of the buy zone |
| On plan | None of the above |

The plan card shows position value now, target and max, the room left to the target and to the max, and the portfolio percentage. Priority when several apply: stop, over max position, target, buy zone.

## 6.3 Trade reasons, outcomes and strategies (`trade_reasons`)

Each filled trade can carry: a **role in the position** (opening, adding, trimming, exiting, swapping), **what triggered it**, a copy of the **plan logic** (see 6.1A), a **decision date** (defaults to the trade day, editable), a **holding strategy**, a fundamental reason, a technical/timing reason, a review date, a **result** (Worked / Mixed / Did not work / Too early / not rated), a free-text "what happened versus what you expected", and a **follow-up**. Rating a result is a deliberate, late step: for a buy, were your judgement and assumptions right; for a sell, did it reach the target or exit rule you set.

**One reason for several trades.** Tick several trades (Calendar day view, Calendar list, or a company's trade table) and choose "Add one reason to all". One dialog writes the same reason, result and follow-up to every selected trade (`PUT /trades/reason/bulk`); each keeps its own trade day. "Select the trades without a reason" ticks a whole day or list in one click. This covers split fills of one order and several same-day trades with one cause.

**Quick marker.** Calendar chips and tables show ○ no reason, ● reason, ✓ reviewed, ✔ worked, ◐ mixed, ✗ did not work.

**Outcome statistics.** Portfolio shows counts per strategy: trades, buys/sells, worked, mixed, did not work, too early, not rated, and worked share of rated trades. Deliberately coarse: one result axis and one grouping axis (strategy). No per-sector, per-size or per-holding-period cuts, and no scores, because a personal trade log is a small sample. A notice appears below 10 rated trades.

### Holding strategies

| Strategy | Goal | Buy when | Sell when | Judge it by |
|---|---|---|---|---|
| Long-term hold | Own a business for years; earnings growth compounds | Thesis Intact; growth and margins support the price | Thesis At risk, a core assumption broken, or a far better use of the money | Earnings and thesis, not price; review each earnings report, at least every 6 months |
| Swing | Capture a multi-week move around a catalyst or trend | Named catalyst or setup, stop and target set first | Target or stop hit, or catalyst passed | Did the setup play out as planned; review after 2-8 weeks |
| Short-term trade | Profit from a move over days | Clear trigger, size you can lose, exit rule written down | Stop or target; no averaging down | Rule-following and net result after fees; review within 2 weeks |
| Defensive / hedge | Reduce risk | Portfolio-level reason (concentration, macro, drawdown limit) | The risk has passed | Did it reduce the risk you named |
| Rebalance / swap | Fix weights or replace a weaker idea | Weight drifted or a clearly better alternative | One-off | Did the new position beat the one replaced over about 6 months |

These standards are shown in the in-app Guide and are defined in one place in the front end (`STGD`).

# 6A. The Decision Loop and How Modules Relate

1. **Think** (Company: Brief, Thesis, Fundamentals, Timeline, Notes): state why you own or watch a company, as assumptions with kill criteria. The model reads public data and your unverified notes only.
2. **Decide** (Position and plan): strategy, the position logic written once, target and max position (amounts), price levels. Plan status is computed by code, including over-max position.
3. **Act**: trade at the broker, then import filled orders (Portfolio). The workbench never trades.
4. **Record the action** (Add reason): role in the position and what triggered the trade; the position logic is copied from the plan, not retyped; bulk for related trades.
5. **Review the trade** (Calendar, due items): at the review date rate the result and write what happened and what next.
6. **Review the portfolio** (Overview digest, Journal checklist): a code-built look-back for a period (movers, trades, thesis changes, plan alerts, stale analyses, due reviews). The conclusion is written as a Journal portfolio review.
7. **Calibrate** (Portfolio: Trade outcomes): compare strategies, adjust rules (entry, size, stop, review date) and the thesis, then repeat.

| Module | Holds | Feeds |
|---|---|---|
| Company tabs | Thesis, assumptions, health, history, notes | Overview, Journal checklist |
| Position and plan | Purpose, target, stop, size | Plan alerts, Portfolio |
| Portfolio | Holdings, allocation, backlog, outcome counts | Overview, Calendar |
| Calendar | All trades by day, due reviews, journal events; where reasons and results are entered | Outcome statistics, Journal |
| Journal | Portfolio-level diary, period checklist | Calendar events |
| Overview | Period digest, company table | Where to look first |
| Guide | This loop, module map, strategy standards | (reference) |

# 7. Portfolio Journal and Period Digest

## 7.1 Journal page

- Entry types: decision, portfolio review, macro idea, external source. Each has a title, optional related symbols and an optional revisit date.
- The checklist window can be changed with a date picker; by default it starts at the last saved "portfolio review" entry, or 30 days back if there is none.
- Every entry stores a snapshot of the portfolio when it was written: position count, top-5 weight, weight in Cautious names, unanalysed weight, and the top 15 holdings with weight and view.
- The **review checklist** (`GET /journal/checklist`) is generated by code with no model call: concentration; trades in the period and which lack a reason; view and assumption-status changes; plan alerts; holdings never analysed or older than 30 days; items that are due; and the holdings with the largest weight x move. The default window starts at the last "portfolio review" entry, or 30 days back.
- **Start review** pre-fills the entry from the checklist and leaves three prompts: what changed in my thinking, what I will do next, what would prove me wrong. Every field has a "?" help bubble.
- Journal entries tagged with a symbol, and company notes, are merged into that company's timeline.
- Journal content stays local and is never sent to a model.

## 7.2 Period digest on Overview

The digest is about **your own portfolio**, not a macro view. The model has no live market data, and asking it to comment on "the market this month" invites invention, so that is deliberately not built. The default window is the last 30 days (monthly), with 7 and 90 days available. It uses the same data as the review checklist: counts of trades, thesis changes, plan alerts and due items, followed by the specific names and the largest movers. Everything is computed by code and costs no tokens.

## 7.3 Trade calendar

A calendar page that answers "when did I act, and what is still missing". It is a review tool for behaviour, not a P&L report.

- **Views**: month (default) and week, both starting on Sunday, plus a list view that shows the same filtered trades as a table. Navigation by previous / next / today.
- **Day cells** show up to three chips such as `B MU` or `S NVDA`, then "+N more". The cell shade deepens with the number of trades (a count, not an amount, because USD, HKD and SGD cannot be added). The week view lists every trade of the day.
- **Review state on every chip**: dashed outline and an empty dot mean no reason has been written; a filled dot means a reason exists; a check mark and bold text mean the trade has been reviewed. A clock chip means a trade review, note or journal item is due that day.
- **Day detail**: click a day to see each trade with quantity, price, strategy, reason and review text, the change since the trade (for a sale: how the price moved after you sold), and flags: a possible pre-split price, and "bought and sold within 10 days" for quick round trips (stated as a fact, not a verdict). "Add reason" opens the same dialog used elsewhere.
- **Filters**: symbol, buy or sell, strategy, and "no reason only". **Layers**: due items and journal entries (with market events) can be switched on or off.
- **Journal events**: a journal entry may carry an event date (a war, an outbreak, a rate decision). It appears as a marker on that day, so you can see what you did around it. Entries without an event date appear on the day they were written.
- **Dates follow each market**: a trade is placed on its own market's calendar day (US Eastern, Hong Kong, Singapore), so a Hong Kong morning trade is not shown on the previous day because of UTC.
- **A legend and a help bubble** explain every symbol on the page.
- **From a day to the journal**: the day detail has a "+ Journal note or event" button that opens the Journal form with that date filled in as the event date, so a market event is logged against the right day.
- **List view** covers the last 36 months, which makes it the place to work through trades that still need a reason.
- **Links between pages**: the Portfolio "trades needing a reason" card, the Overview digest and the Journal checklist all link to the calendar (the list view, or the day a review is due), so trade detail lives in one place and the other pages show only summaries.
- Computed entirely by code from existing tables (`trades`, `trade_reasons`, `notes`, `journal_entries`); no new table and no model call. Current prices come from the latest snapshot, or from the imported holdings; where neither exists the change is shown as unavailable.

# 8. Chinese Translation

- Analysis is always generated in English. Chinese is an on-demand translation, not a second analysis.
- A button at the top right of a company page switches the view. When the latest review has no translation, the Brief and Thesis pages show "Translate to Chinese". In the Timeline an older version can be translated individually. The full baseline report belongs to an earlier review and is translated separately.
- Only free-text fields are translated (view, assumption statements, triggers, causal mechanisms, change descriptions, narrative). Numbers, symbols, assumption ids, status labels and enums are never sent to the model.
- A translation is stored per review. Reviews never change after they are written, so a stored translation never goes stale; a new analysis creates a new review that can be translated when needed.
- The model must return items one by one. If fewer than 60% come back, nothing is saved and the user is asked to retry.

# 9. Front-end Information Architecture

Sidebar: Overview, Portfolio, Journal, Calendar, then the company list grouped as Holdings / Watching / Ideas / Archived. Groups collapse (only Holdings is open by default; a group with matches opens while searching), there is a filter box above, and the add-symbol box, theme switch, today's AI usage and version stay fixed at the bottom. For Hong Kong and Singapore codes the sidebar shows the company name under the code, using the name from your broker export.

| Page | Content |
|---|---|
| Overview | Period digest; company table with search, filters (group, market, view, sector), several sort orders, 20 rows per page |
| Portfolio | Collapsible CSV import; summary cards (positions, top 5, weight in Cautious names, unanalysed weight, plan alerts); allocation bar (by sector, investment purpose, type, view); trades needing a reason; holdings table with search, filters, sorting, paging, plan editing, analysis and type change |
| Journal | Review checklist; new entry form (with optional event date); entry list filterable by type |
| Calendar | Month / week / list view of trades by market-local day; review-state chips; day detail with reasons and change since the trade; filters; due and journal-event layers |
| Company: Brief | Stance and thesis health, one-line conclusion, assumption status bar, recent changes, what the price implies, core assumptions, monitor items |
| Company: Position & plan | Position and plan card; trades with reasons |
| Company: Thesis | Profile, assumption status history (one dot per analysis, oldest to latest), full baseline report |
| Company: Fundamentals | Current metric snapshot compared with values at the last analysis; no line charts |
| Company: Timeline | Analyses, checks, trades, journal entries and notes in time order; analysis nodes expand |
| Company: Notes | Personal notes (decision log, comment, source, question) |

Interaction conventions:

- Confirmations use in-page dialogs, never the browser's `prompt()` or `confirm()`, which a browser can suppress.
- Analyse asks for confirmation first (it uses tokens and takes about 20 to 60 seconds), shows progress, and opens the company report when done.
- Help bubbles float above the page so a scrolling table cannot clip them.
- Visual language: one primary colour plus semantic colours (strengthened, neutral, weakened, warning); a coloured bar at the start of a row shows the view; light and dark themes.
- The page is served with `Cache-Control: no-store` and the version is shown at the bottom left, to avoid running a stale page.

# 10. Security

## 10.1 Scope and threat model

The workbench is a **single-user, local application**. It listens on `127.0.0.1` and has no login. The assets worth protecting are the Gemini API key and your financial data (holdings, trades, plans, reasons, journal). The realistic threats are therefore: other web pages you visit that try to reach localhost, accidental exposure of the port to a network, leakage of the key or private data to third parties, hostile content arriving through news or imported files, and loss of data. It is **not** designed for multi-user or internet deployment.

## 10.2 Controls in place

| Risk | Control | How it is enforced |
|---|---|---|
| Port exposed to a network | Default bind to `127.0.0.1`. The README forbids `--host 0.0.0.0`, because there is no login. | Deployment instruction; the Host check below also rejects foreign host names |
| Cross-site request forgery from another tab | Every state-changing request (POST / PUT / PATCH / DELETE) that carries an `Origin` header must have the same host as the server; `Origin: null` is refused | Middleware in `app/main.py`, logic in `app/security.py`, unit-tested |
| DNS rebinding (a hostile site resolving to 127.0.0.1) | The `Host` header must be `127.0.0.1`, `localhost` or `[::1]` (extra names only through the `ALLOWED_HOSTS` variable) | Same middleware |
| Clickjacking, content sniffing, referrer leakage | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` | Response headers on every reply |
| Script injection into the page | A Content Security Policy on the page: scripts, styles and connections only from the same origin, no framing, no base tag. Because the front end is one file with inline script, `unsafe-inline` is allowed for script and style; this is a known residual limit. | `Content-Security-Policy` on `/` |
| Cross-site scripting through data | Every dynamic value (model output, news titles, company names from the broker, notes) is HTML-escaped before it is inserted. The report renderer escapes first and then adds only bold and headings. Links are rendered only for `http` and `https`, with `rel="noopener"`. | `E()`, `md()`, `su()` in the front end; smoke test covers the link rule |
| SQL injection | All database access goes through SQLAlchemy with bound parameters; no string-built SQL except fixed column names in the start-up migration | Code structure |
| Malicious or oversized upload | Uploads are read as text only, limited to 5 MB, never executed and never written to disk; parsing errors return a 400 message | `_read_csv` in `routes.py` |
| Secrets leaking | The API key lives only in the local `.env`, which is git-ignored and excluded from every release zip. No endpoint returns it (`/health` returns only the provider and model name); the front end never sees it. | `.gitignore`, packaging rule, endpoint review |
| Private data sent to third parties | See 10.3: holdings, quantities, costs, weights, plans, trade reasons, journal and decision notes are never part of any model or data-source request | Prompt payload builders contain only market evidence and permitted notes |
| Prompt injection through news or notes | News headlines and notes are untrusted. The model has no tools, no network and no file access, so injected text cannot act. Its output must fit a strict pydantic schema, is shown only as escaped text, and notes are labelled "unverified". Thesis health, view change and plan status are computed by code and cannot be set by the model. | `ai/schemas.py`, `ai/prompts.py`, `core/thesis.py` |
| Data loss or silent overwrite | Reviews are append-only; destructive actions (deleting a company, a note, a journal entry) require an in-page confirmation, and deleting a company requires typing its symbol. SQLite is a single file that you can back up. | Front-end dialogs; data model |
| Vulnerable or unstable dependencies | `openbb` is pinned to 4.7.2 (5.x breaks the adapter); other packages are listed in `requirements.txt` | Dependency file |

## 10.3 What leaves your machine

| Destination | What is sent | What is not sent |
|---|---|---|
| Yahoo Finance (through OpenBB, and an RSS fallback) | Ticker symbols you analyse | Anything about your holdings |
| Google Gemini API | Market data, fundamentals and recent headlines for the symbol being analysed; the previous structured thesis; your comment / source / question notes; for translation, the text of an existing analysis | Holdings, quantities, costs, weights, plans, trade reasons, journal entries, decision-log notes, the API key |

Analysing a company reveals your interest in that ticker to those services, and the terms that apply to free-tier API data may differ from paid terms; review Google's current terms if that matters to you. With `AI_PROVIDER=mock` nothing is sent to any model.

## 10.4 Known limits and recommended practice

- No authentication, authorisation or per-user separation. Anyone who can reach the port or use your computer account can read and change everything. Do not deploy it publicly; if it ever must be shared, put it behind a reverse proxy with login and HTTPS.
- No encryption at rest. `workbench.db` is a plain SQLite file; rely on full-disk encryption (for example FileVault) and keep the file out of cloud-synced or shared folders.
- Traffic to localhost is plain HTTP, which is acceptable on one machine but not across a network.
- The CSP allows inline script because of the single-file front end; splitting out the script would allow a stricter policy.
- Server logs may include ticker symbols and provider error text. They do not include the API key from our code, but keep logs private.
- Back up `workbench.db` yourself before upgrades; never place `.env`, the database or `.venv` in a zip, a repository or a screenshot.
- Rotate the Gemini key if it is ever exposed, and never paste it into a chat.

# 11. API Overview

Prefix `/api/v1`.

| Endpoint | Purpose |
|---|---|
| `GET /companies`, `PATCH /companies/{t}`, `DELETE /companies/{t}` | List, change group, delete |
| `POST /companies/{t}/refresh` | The only analysis entry point: the system decides between baseline, update or a free check. It validates the symbol first; if no data exists nothing is saved and no model call is made. |
| `GET /companies/{t}/brief`, `/thesis`, `/fundamentals`, `/timeline` | Page data; `?lang=zh` returns Chinese when a translation exists |
| `GET /reviews/{id}`, `POST /reviews/{id}/translate` | One review in detail; manual translation |
| `GET /companies/{t}/compare?a=&b=` | Difference between two versions |
| `GET/POST /companies/{t}/notes`, `POST /notes/{id}/done`, `DELETE /notes/{id}` | Notes |
| `POST /portfolio/import/holdings`, `/portfolio/import/trades` | CSV import (trades return the diagnostic report) |
| `GET /portfolio`, `PATCH /portfolio/holdings/{id}` | Holdings with summary; change type |
| `PUT/DELETE /plans/{symbol}`, `POST /plans/{symbol}/apply-logic` | Position plan (incl. logic and position amounts); copy the logic to trades with no reason |
| `GET /companies/{t}/trades`, `GET /trades/pending`, `PUT /trades/{id}/reason`, `PUT /trades/reason/bulk`, `GET /trades/outcomes` | Trades and reasons |
| `GET/POST /journal`, `POST /journal/{id}/done`, `DELETE /journal/{id}` | Journal |
| `GET /journal/checklist?since=` | Review checklist and period digest |
| `GET /calendar?start=&end=` | Trades by market-local day, due items and journal events for a date range (at most 1500 days) |
| `GET /usage`, `GET /health` | Today's AI usage; version |

# 12. Testing

| Category | Content |
|---|---|
| Unit tests (`unittest`) | Change detection, broker CSV parsing and symbol normalisation, thesis health, prompts, model chain, plan status, translation field extraction, security checks, calendar dates |
| Front-end smoke test (`node tests/ui_smoke.js`) | Simulated DOM and mocked API: grouped sidebar, filters and paging, plans and trade reasons, confirmation dialogs, Analyse flow, journal, period digest, Chinese view, link safety |
| `tests/test_service.py` | Needs the installed packages to run |

## Known limitations

- The development sandbox could not install FastAPI and SQLAlchemy, so the HTTP endpoints and database paths were not executed there. The author verified them by running the app locally.
- ETFs have no stock-style data from the data source (for example TLT, ZROZ); they can be recorded with plans and trades but not analysed.
- News availability depends on the data source.
- Weights for multi-currency holdings use the broker's percentages without currency conversion.
- Type detection for options and Singapore shares is coarse; change the type by hand when needed.

# 13. Running and Configuration

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # set AI_PROVIDER, AI_MODEL, GEMINI_API_KEY
uvicorn app.main:app --reload --reload-dir app
```

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | Default `sqlite:///./workbench.db` |
| `OPENBB_PROVIDER` | Data source, default yfinance |
| `AI_PROVIDER` | `mock` or `gemini` |
| `AI_MODEL` | Main model; `AI_MODEL_FALLBACKS` (comma separated) are tried when quota runs out; `AI_MODEL_BASELINE` is optional and tried first for first-time baselines only |
| `AI_THINKING_BUDGET` | Thinking-token budget, 0 to turn off |
| `GEMINI_API_KEY` | Only in the local `.env` |
| `ALLOWED_HOSTS` | Optional extra host names accepted by the Host check |

Notes: never put `.env`, the `.db` file or `.venv` in a zip or repository. Use `--reload-dir app`, otherwise the reloader watches `.venv` and restarts repeatedly. Do not pass `--host 0.0.0.0`.

# 14. Roadmap

| Status | Items |
|---|---|
| Done | Thesis tracking with change detection; four company pages; grouped sidebar and Overview; broker CSV import; position plans; trade reasons and review; portfolio journal and checklist; period digest; on-demand Chinese translation; list filters and paging; allocation bar; request guards and upload limit; trade calendar |
| Optional | An AI draft of the period digest (one call, based only on the digest's facts, labelled as a draft); currency conversion; price and plan tracking for ETFs; export |
| Wrap-up | Git clean-up is left for the author to do at the end of the project |



## 6B. Valuation lab (2.17.0 → 2.18.0)

Separate page `/valuation` and separate `valuation.db` (append-only snapshots: `data` and `analysis`). Nothing here writes to Plan, Thesis or the research DB, and no private holdings data is used.

**Models.** P/E exit-multiple (EPS anchor × (1+g)^t × exit P/E) and EV/EBITDA (revenue × margin × multiple − net debt − claims). Bear/Base/Bull are user-set ranges, not probabilities. Reverse calculations show the EPS/margin/multiple needed for the required return.

**2.18.0 changes.**
- Anchors are labelled by kind and ordered: `ttm` (trailing EPS to latest quarter), `consensus:0y`, `consensus:+1y` (period end derived from `nextFiscalYearEnd`), then reported annual. Revenue anchors likewise. Growth compounds from the anchor's period end, so a TTM anchor no longer adds ~0.7 year of phantom growth.
- `defaults` (status quo): growth from analyst +1y/0y EPS or last revenue growth, current provider multiple, last reported margin. Button "Start from status quo" fills the form; the user still edits.
- `checks` in each result: exit multiple vs current (>1.5x warn), stale annual vs TTM EPS (>25%), price/EPS >60x, base growth far above consensus, margin >1.5x history, long growth gap. Warnings suppress the green/red colouring.
- `earnings_quality_flags` (net margin vs prior-year median) replaces hard-coded per-ticker notes (a small `KNOWN_NOTES` dict remains).
- Analysis snapshots store only `data_id` and join the data snapshot on read (old rows with an embedded copy still load); stored closes are limited to those used.
- `/api/v1/health` returns `valuation_api`; the page warns when server and page versions differ. CSP now also applies to `/valuation`.

**Not done.** P/FCF, dividends in return, a Company-page tab, Futu data. Tests: `tests/test_valuation_ctx.py` (unittest, no network); `requirements-dev.txt` lists pytest/httpx for the pytest files.

## 6C. Valuation lab 2.19.0: forecast → price → compare

**Purpose.** The page answers two questions, not "is my view right": (1) given reported results, analyst expectations and an exit multiple, what annual return does today's price imply; (2) which of several tickers offers more on the same horizon and the same rules.

**P/FCF method (`p_fcf`).** FCF per share anchor (TTM, annual; before and after stock-based compensation) × ((1+FCF growth)/(1+share change))^t × exit P/FCF. FCF = provider FCF or operating cash flow − capex. Shares: reported diluted average, else net income / diluted EPS, else current shares (labelled). Checks: exit multiple vs today, FCF/net income conversion outside 0.5–1.5, SBC share of FCF, price/FCF > 60.

**Compare (`POST /api/v1/valuation/compare`, kind `comparison`).** 2–5 tickers; data snapshots younger than `reuse_hours` (6) are reused. For each ticker every method whose data exists runs from status-quo defaults (analyst or reported growth held flat; exit multiple = today's multiple × (1+shift); EV/EBITDA holds current net debt and shares). Output: Base/Bear/Bull annual price return per method, most conservative Base (ranking key), dispersion across methods (flag above 10 points), earnings-quality flags, and why a method was not run. Methods are not averaged. Saved results store data ids, not copies of the data.

**AI.** Not used on this page: numbers are computed by code. A later optional button may ask the model to explain disagreement between methods, sending only the valuation outputs, never holdings or plans.

**API version 3** (health field `valuation_api`); the page checks it. The consensus × P/E bridge is demoted to a collapsed reference.

## 6D. Valuation lab 2.20.0: same look as the app, growth fade, industry peers

- **Page**: same tokens, cards, tabs and dark mode as the main app. Tabs Compare / Company / Guide; methods are tabs inside Company (each shows what it is, where it fits and where not, with a data-availability dot), live preview while editing, Save writes a snapshot.
- **Growth fade** (`fade_to`, all methods and Compare): yearly growth moves linearly from the starting rate to the fade rate by exit. Blank = flat. Bear/Bull shift both ends by the spread.
- **Exit multiple references** (`core/multiples.py`): today, own annual history, peers, rough sector/industry band (editable data, not market data), growth-implied check (peer median PEG ± 20% when available, else PEG 1–2; hidden below 8% growth). None is chosen for the user; Compare also shows a de-rating case to the peer median or band.
- **Industry peers**: option "use the largest companies in Yahoo's industry" (`yfinance.Industry(key).top_companies`, up to 8) fills the peer set when none is entered; `industry_ref` holds medians (forward P/E, P/FCF, EV/EBITDA, PEG from provider forward ÷ trailing EPS). Slower: about one extra lookup per peer.
- `valuation_api` = 5. Compare accepts `fade_to` and `include_industry`.

## 6E. Valuation lab 2.21.0

- **Exit multiple basis**: the neutral exit P/E is the *trailing* multiple (price over last-twelve-months EPS), because the EPS at exit is the year just ended. Forward P/E is shown separately, not used as the exit multiple.
- **Growth references** (`growth_refs`): analyst EPS growth, analyst revenue growth, last annual revenue / EPS / FCF-per-share growth, each with basis; "Use" buttons fill the growth field. No market forecast exists for free cash flow. Defaults fade to 5%/yr (`DEFAULT_FADE`).
- **Method fit** (`method_fit`): per company, fit / caution / avoid with reasons (cyclical industry, one-off earnings, cash conversion, stock compensation, no net debt, share-count mismatch), plus a recommended method (free cash flow for cyclicals). Shown as coloured dots, a ★ and a callout; Compare marks ★ and notes "(care)".
- **Reference ranges**: P/E, P/FCF and EV/EBITDA sector/industry bands in `core/multiples.py` are hand-set rules of thumb, not data; peers (user list or Yahoo industry) override them.
- **Compare guards**: share count = market cap / price (covers share classes); EV reconciliation (`ev_check`); methods rated "avoid" are not run; a default Base return above +60% or below −50% a year is treated as a data mismatch and not ranked.
- **Year-by-year Base path** (`path`, P/E and P/FCF): metric × multiple (multiple moves linearly to the exit multiple). Year 1 is comparable with analyst 12-month targets; the page states how many years lie beyond the analyst horizon.
- Quarterly consensus rows show an approximate period end. `valuation_api` = 6.

## 6F. Valuation lab 2.23.0: starting point, multiple basis and turnaround cases

**The rule that matters most.** A multiple and the number it multiplies must sit on the same basis. The model takes a *starting value* (EPS, or free cash flow per share), grows it for the holding period, and multiplies by an exit multiple. Today's multiple on that same starting value is `price ÷ starting value`. Holding it flat adds nothing, so the return shown is pure growth. In 2.21.0 the starting value could be an analyst year while the default exit multiple stayed the trailing one (27.8× for DEO on trough earnings of 3.12); that double-counted the recovery (about 35% a year). It is now impossible to do by default and warned about when done by hand.

**Which number is used (defaults).**

| Item | Default | Why |
|---|---|---|
| P/E starting value | Furthest analyst EPS year available (`consensus:+1y`), else trailing twelve months | Analysts' numbers are what the price is paying for; shown with its period end and "analyst consensus" label |
| Exit P/E | Today's price ÷ that starting EPS (DEO: 12.06×), not the trailing 27.8× | Same basis. When the anchor changes, the multiple is moved to today's multiple on the new anchor and the page says so |
| Growth | Analyst EPS growth next year over this year, fading linearly to `DEFAULT_FADE` (5%/yr) by the exit date | The only forward-looking growth available; it is user-editable |
| P/FCF starting value | Trailing FCF per share, before or after stock compensation as `method_fit` recommends; the exit multiple is built from the *same* figure | No free cash flow consensus exists; growth is a stand-in taken from analyst EPS/revenue growth and labelled as such |
| EV/EBITDA | Trailing revenue × trailing EBITDA margin (provider EBITDA ÷ TTM revenue when available), current net debt and shares held constant | Cross-check only |
| Growth years | Exactly the holding period, counted from the starting value | The basis is carried forward by one holding period; no extra years are added for the date gap |

**Earnings dislocation** (`core/valuation_context.earnings_dislocation`; the same fact reaches the thesis through `derived.earnings_dislocation` in `core/signals.py`). Flagged when analyst EPS for the current year is at least 50% above trailing EPS, or at least a third below it. The page shows trailing EPS, the analyst years, the trailing and forward multiples, the highest reported annual EPS, and a plain statement that the price already pays for the recovery. It also states the limit: analyst EPS is usually adjusted, reported EPS includes one-offs, so part of the gap may be accounting basis and not a business turnaround. Prompt version `tracker-1.8` tells the model to describe a dislocation as an assumption to test, not as a fact, and never to call the stock cheap from a trailing multiple.

**What you must believe** (`valuation.belief_grid`). Rows are earnings outcomes at exit (the Base path, 20% short, 40% short, and, when starting from an analyst year, "no recovery: trailing EPS is the base"). Columns are exit multiples (today on this starting point, your own, today on the other basis, own history low/high, peer median). Each cell is an annual price return from today's price. Nothing is picked, ranked or averaged. For DEO this is where the disagreement becomes visible: the answer depends far more on the exit multiple and on whether EPS recovers than on any growth rate.

**Fixes adopted from an external review of 2.21.0** (checked against the code before adopting):

- P/FCF after-stock-compensation anchor no longer pairs with a before-compensation multiple; each anchor has its own today-multiple (`multiple_by_anchor`, `fcf_status_quo`).
- Decomposition of the return into earnings and multiple uses the same-basis start multiple, so "multiple 0%" really means growth only.
- `growth_factor` handles fractional tails (1.01 years is not 1 year).
- The cash-flow statement keeps its own period end; it is no longer overwritten by the earnings date.
- Compare no longer drops an implausible method to improve the ranking: a row with an implausible default result or a share-count mismatch keeps its numbers, is marked for review and is not ranked. Methods that could not run still show the reason.
- Compare growth notes show the real source (analyst EPS, analyst revenue, last reported); P/FCF states that its growth is a stand-in and not independent of P/E.
- The de-rating case uses only a reference built from data: the median of at least 3 peers, else the company's own history. Hand-set sector ranges are displayed but never enter a calculation.
- Share-count and ADR mismatches stop automatic P/FCF comparison; estimated consensus period ends are labelled approximate.
- Analyst price targets are shown as a separate reference (the provider gives no horizon); they are not compared with a model year.
- The ★ now means "rule-based preference for this kind of company", not reliability.

**Not adopted.** (1) *Prefer the trailing anchor for all comparisons*: it is consistent, but it prices a recovery stock like DEO as if 2026 earnings were permanent; the fix is matching the multiple to the anchor, not choosing the anchor that hides the issue. Trailing remains selectable. (2) *Sum-of-the-parts (SOTP) module*: it needs segment filings parsed per company and per year; it answers a different question (a conglomerate's parts) and would add a large unverified-data surface to a course project. Revisit only for companies where segments are the core of the thesis.

**Still true after 2.23.0.** There is no back-test and no prediction track record; Bear/Base/Bull are assumptions, not probabilities; price return excludes dividends; the three methods are not independent evidence. Keep the four layers apart when reading a page: reported facts, analyst consensus, your assumptions, calculated results. `valuation_api` = 7.

**Compare page help.** Every input and column header on Compare carries a "?" with a short explanation of what the number does and what it does not do (definitions in the `HELP` table in `static/valuation.html`).

## 6G. Valuation linked to the company page (2.23.0)

The valuation lab keeps its own append-only store (`valuation.db`). The company page reads it through `GET /api/v1/companies/{ticker}/valuation` (`api/valuation_link.py`, pure logic in `core/valuation_link.py`). It never writes to a Plan, a thesis or a saved valuation, and nothing here is sent to a model.

| Item | Behaviour |
|---|---|
| Valuation tab | Latest saved analysis per method: Base/Bear/Bull annual return, the assumptions behind it, and the default status-quo result when nothing is saved. Shows the earnings-dislocation callout when it applies. |
| Stale flags | A saved valuation is marked out of date when the thesis was materially updated after it was saved, when the price moved 15% or more since its data was fetched, or when its data is older than 100 days. The page says which reason applies. |
| Plan price | If the Plan has a buy-below or target price, the tab shows the return at that entry price and "the most you could pay today for your required return". A **Use as buy-below** button fills the Plan form; the user confirms. The Plan is never changed automatically. |
| Assumption ↔ valuation input | On the Thesis page each assumption can be tied by the user to one valuation input (earnings growth, revenue growth, margins, exit multiple, share count, balance sheet). The program never guesses the link. Stored in `assumption_drivers`. A weakened or broken assumption tied to an input a saved method rests on is flagged on that method. |
| Open question | The tab proposes a question ("what must be true for the price to earn your required return?") that can be saved to Notes as a `question` note (unverified, may go to the model; decision notes never do). |

Table `assumption_drivers` is created on start-up. Deleting a company removes its links.

## 6H. Valuation lab 2.23.1: readability

- The conclusion sentence (which scenarios meet the requirement, and what it would take) is a highlighted block, green when at least one scenario meets the requirement and amber when none does.
- Under the result header the page states which period the exit EPS belongs to. With an analyst-year start the exit EPS is for a period ending after the exit date, so the exit multiple is a forward multiple; with a trailing start it is a trailing multiple. This is why the history and sector references (trailing) are marked "read as somewhat high" against a forward exit multiple.
- **What is written to `valuation.db`:** *Import latest data* writes a `data` record; *Compare* writes `data` records for tickers it loads (reusing one younger than 6 hours) and one `comparison` record; *Save snapshot* writes an `analysis` record. Typing, switching tabs and live preview write nothing (`persist: false`). Nothing is overwritten.
- The company page reads the newest `data` record and the newest `analysis` record of each method (`api/valuation_link.py`); it does not read comparisons or unsaved previews.
- The Saved snapshots list is built by `core/snapshots.history_rows` and labels each record (method and Base return for analyses, price for imported data) and shows local time.

## 6I. Valuation lab 2.24.0: records, language, question card

- **Fewer records.** Importing a ticker again replaces earlier imports that no saved analysis or comparison uses (`core/snapshots.prune_data`); the newest import always stays. A record can be deleted from the Saved snapshots list after an in-page confirmation (`DELETE /api/v1/valuation/snapshots/{id}`); imported data that a saved result still points to is refused with a message (HTTP 409) so a saved result can always be reproduced. "Remove unused imports" does the same clean-up on demand (`POST /api/v1/valuation/{ticker}/cleanup`). Records are never edited.
- **Language.** An English / 中文 switch (remembered in the browser; `?lang=zh` also works, and the company page passes it on). Chinese covers the Guide, every "?" explanation, the intro texts, the conclusion block, the "same basis at the exit" line, the analyst-versus-scenario and guesswork notes, the dislocation explanation and the snapshot list. Table and column labels and the notes the backend writes stay in English, as indicators do in the rest of the app.
- **Question card.** The company page shows "A question to write down" whenever the valuation yields one (before, only when earnings were far from analyst expectations). The text is editable, an optional look-again date is saved as `revisit_on`, and it is stored as a `question` note.
- **Tests.** The lifecycle test now expects a free `check` after an update (the update becomes the new anchor, so identical inputs mean nothing changed); the API tests accept the `peer_symbols` argument.

## 6J. 2.25.0: other currencies, Fundamentals layout, Overview
- **Other currencies.** When a company is quoted in one currency and reports in another (0883.HK: HKD price, CNY accounts), reported figures and analyst EPS/revenue are converted once to the quote currency at the latest daily spot rate (Yahoo pair, inverse if needed; pence/pounds need no rate). The rate is held constant to the exit date, and every converted figure says so. If no rate can be fetched the methods that mix the two currencies stay blocked and the message says why. The valuation is therefore in the currency you see the price in (HKD for 0883.HK), not USD.
- **Fundamentals tab.** Read top to bottom in three sections: what you pay (multiples, analyst consensus, what the price implies), what you get (growth, profitability, balance sheet), then the record (annual and quarterly results, free cash flow). Labels no longer wrap into narrow columns.
- **Overview.** The period digest tiles jump to their sections and use the same titles as the sections below them; the digest is laid out in two columns. The Companies and Holdings tables can be sorted by best or worst P&L and by weight.

## 6K. 2.27.0: back to the same company; two things tried and removed
- **Back to the same company.** "← Workbench" on the Valuation lab opens the company named in its Ticker box, on the Valuation tab (`/?t=TICKER`). With no ticker, or one the workbench does not follow, it opens the Overview as before.
- **Tried and removed: analyst forecasts as extra columns in the Fundamentals tables.** The reported-results columns were often empty for revenue and EPS while the forecast columns were full (or the reverse), so the table showed either no history or no forecast and was harder to read than the two separate views. Analyst expectations stay where they were: the consensus card and "What the price implies" on Fundamentals, and the annual and quarterly estimates in the Valuation lab.
- **Tried and removed: saving readings (a bookmark button into the Journal).** It added a step for little gain over the Journal's existing External source entry, which remains available for anyone who wants to note something they read.
- The design work is complete at this version.

## 6L. 2.27.1: bug fixes (no new features)
- **Theme switch broke the next click.** The theme was stored as `data-t` on the page root, the same attribute company rows use to open a company, so after Toggle theme every click was read as "open company `dark`". The theme now uses `data-theme` (remembered in the browser), and the company-click handler ignores the root element.
- **Sidebar shows where you are.** Overview, Portfolio, Journal, Calendar and Guide are highlighted while open (not while a company is open; that company is highlighted in its group). Holdings and Watching groups start open.
- **Group is always visible.** The Group selector (Holdings / Watching / Ideas / Archived) now has a label and appears for any followed company, not only after the first analysis. Importing holdings sets Holdings automatically.
- **Extreme exit multiples.** When today's multiple on the chosen starting number is above 150x (P/E, P/FCF) or 100x (EV/EBITDA), the starting number is too small to mean anything (INTC free cash flow). It is still shown in the reference table, but it is no longer pre-filled as the exit multiple, and Compare reports the method as "review" instead of calculating. The page explains why and points to the peer and own-history rows. The hard input limits (500 / 300) are unchanged.
- **Readable validation errors.** The valuation page now reports "Exit multiple: must be less than or equal to 300 (you entered 1230.89)" instead of the raw validation list.

## 6M. 2.28.0: two dimensions instead of one group
- **Problem.** One list (Holdings / Watching / Ideas / Archived) mixed two different questions: do I own it, and how closely do I follow it. A small leftover position and a stock I am waiting to buy could not both be shown as important.
- **Held is derived, not chosen.** `held` is true when the broker import has a position with quantity above zero (`/companies` returns it). The sidebar shows a dot for held companies and has All / Held / Not held buttons. Nothing to maintain, and it cannot go out of date.
- **Focus level is the one manual setting.** Three values: Focus, Others, Archived. Focus is a short list of what you watch closely, held or not. Set it with the ☆ Focus button or the Level box on the company page. The sidebar groups by level; a Focus list longer than 10 is flagged. Moving a company out of Focus asks for an optional reason, saved as a decision note.
- **Migration.** Old values holding, watching and idea become Others at start-up (`database.migrate_attention`); the API still accepts them from old clients. Importing holdings no longer changes the level, and the Analyse button no longer sets "holding".
- **Tests.** A UI check for three levels, old values under Others, the held dot and the filters; a service test for the level mapping and the held flag.

## 6N. 2.28.1: selected item in colour
- The selected sidebar item (a section or a company) is filled with a tint of the accent colour, with accent-coloured text and a 4 px bar on the left, in both light and dark themes. Before, it was only a white row with a thin bar.

## 6O. 2.29.0: one period table, exit at a fiscal year end (formula valuation-v4)
- **Problem.** The valuation data was scattered: starting numbers picked by id from several anchor lists, a holding period counted in years from the import date, and the same defaults rebuilt in four places (form defaults, P/FCF defaults, Compare, the company page). Growth, multiple and period could sit on different bases.
- **One table.** `core/period_table.py` builds one table per import: reported fiscal years, the trailing twelve months (reference only), the analysts' years, then the years the user projects. Rows: revenue, EBITDA and margin, EPS, free cash flow, FCF per share (also after stock comp.), shares. Each cell carries kind (reported, analyst, derived), period end, currency, source, number of analysts, low and high, and growth against the previous column. Defaults, references, growth sources, the grid, Compare and the company-page link all read this table (`table_of(data)` builds it for older imports).
- **Exit at a fiscal year end.** The user picks an exit fiscal year; years = (exit date − valuation date) ÷ 365.25, fractional. The exit multiple is trailing: the price at that year end ÷ that year's metric. The old integer years and anchor id are gone (`exit_fy` replaces them).
- **Analyst years are fixed** and the same in Bear, Base and Bull. The scenarios differ in the growth of the first user year (fading linearly to "fade to", default 5%, by the exit year), the exit multiple and, for EV/EBITDA, the margin. If the exit year is an analyst year, only the multiple (and margin) differ.
- **P/FCF.** Analysts publish no FCF forecast. FY0e and FY1e FCF per share are derived from the last reported FCF per share × analyst revenue growth (shown in a different colour). The default growth is revenue growth, with an implied FCF margin check. Basis: before or after stock comp.
- **Defaults in one place** (`core/valuation_defaults.py`). Default exit multiple: today's price on this year's analyst estimate, else TTM; the extreme-multiple rule of 2.27.1 still applies.
- **Compare** snaps each company to the fiscal year end nearest the target date and shows that year and the years.
- **Analyst revisions.** An analysis stores the analyst estimates it used. On the next import, EPS moved by 3% or more, or revenue by 2% or more (constants in `valuation_link.py`), adds a factual notice in the lab and a "may be out of date" reason (kind `estimates`) on the company Valuation tab. Saved analyses are never changed. A newly reported fiscal year adds a reason too.
- **Migration.** `valuation.db` has `PRAGMA user_version` 4. On first start the old file is copied once to `valuation.v3.bak.db` and records the new model cannot read are removed. `workbench.db` (reviews, notes, assumption links, plans) is not touched.
- **UI.** Section 1 is a growth-ladder table; the selected multiple and growth rows are highlighted ("Your own value" when none matches); exit dropdown shows ≈ years; a year-by-year table shades analyst years against yours.
- **Behaviour change to know.** The default exit multiple is now on this year's estimate and the exit is a year end, so default results (for example MSFT) differ from 2.28.
- **Tests.** Period table (December and June year ends, no analysts, loss-making, non-USD), exit date and years, hand-calculated results for the three methods, extreme multiples, Compare with different year ends, migration, estimate-revision notice.

## 6P. 2.29.1: read this first, three lenses, and the fixes found on MSFT, DEO, CNOOC and INTC
- **Why.** Real runs showed results that differed a lot between sensible settings, and some defaults that produced nonsense (a 57x exit P/E on INTC, a fake "multiple expansion" on CNOOC, a +115% "earnings growth" on DEO). The answer was to make the dependence visible and to fix the defaults, not to add a model verdict.
- **Fixes.** (1) The analyst-year cash flow (no consensus exists) uses the newer of the last reported year's and the trailing twelve months' cash margin (`period_table['fcf_base']`), so a cyclical whose margin has moved is not pulled back. (2) A default exit multiple more than 1.5x the top of the reference range (sector band top, or own history high for P/E) is set to that top, with the reason; today's multiple stays in the reference table. (3) The first-user-year growth default is capped at 25% with a note (a rebound year's rate is not carried forward). (4) For a recovery or loss-to-profit case the return split starts from this year's analyst figure, not the trough TTM (otherwise "earnings +40%, multiple −25%"). (5) Method fit checks that a positive base exists; P/E with a negative trailing EPS but positive analyst years is "caution", not "avoid". (6) With the exit in an analyst year the growth inputs are dimmed and the cards say growth is not used. (7) EV/EBITDA from the provider is checked against the lab's own enterprise value; the dividend yield is recorded.
- **Read this first** (`core/diagnosis.py`, attached to each result as `diagnosis`). Pure rules on the period table and the result: a level (ok / care / does not suit), flags (few analysts, wide analyst range, high first-year growth, a share-count jump, high leverage, dividend, a share-change input that looks wrong, a moved cash margin, cyclical margins, a multiple far above any reference), "what the price already asks for" (the figure needed at exit at a few multiples), a count of "what you must believe" cells that meet the requirement, and suggestions.
- **Three lenses.** The Base case again with only the exit multiple changed: yours, today's held, the reference multiple, and a cautious one (history low or band bottom, growth cut to 60%). If they differ by more than 15 points a year the panel says the answer is mostly the multiple.
- **Suggestions never apply themselves.** Each is a button that fills a form field and recalculates; nothing is saved until the user saves.
- **Not covered, stated plainly.** Banks, insurers and REITs (P/B, FFO) and early-stage loss-making growth companies (EV/Sales) have no method here; the fit rules say "does not suit" instead of giving a number.
- **Tests.** `tests/test_diagnosis.py`: CNOOC-like cash margin, INTC-like negative base and capped multiple, rebound growth cap, recovery split, lenses, flags, the inputs and result unchanged by the diagnosis.
