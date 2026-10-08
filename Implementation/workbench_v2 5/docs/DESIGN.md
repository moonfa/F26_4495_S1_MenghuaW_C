---
title: "Personal Investment Workbench v2 — Design Document"
subtitle: "Thesis tracking, portfolio, position plans, trade review and portfolio journal (version 2.11.0)"
date: "2026-10-08"
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
| `app/ai/` | Schemas, prompts (version tracker-1.6), provider with Gemini model chain |
| `app/portfolio.py` | Broker CSV parsing (holdings, trades) and symbol normalisation |
| `app/service.py` | Refresh orchestration: validation, caching, choosing the analysis type, calling the model |
| `app/security.py` | Host / Origin checks, upload limit, response headers |
| `app/api/routes.py`, `journal.py` | HTTP endpoints |
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
| `plans` | Position plan: style, buy zone, target price, stop price, add / trim / exit rules |
| `trade_reasons` | Why each trade was made (strategy, fundamental and technical reasons, revisit date) and the later outcome review |
| `journal_entries` | Portfolio journal: type, title, body, related symbols, revisit date, and a snapshot of the portfolio when written |

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

## 6.2 Position plans (`plans`)

For each symbol you set a style (investment / trade / defensive), a buy zone, a target price, a stop price and add / trim / exit rules. Plan status is evaluated by code (long positions only):

| Status | Condition |
|---|---|
| Stop breached / Near stop | Price at or below the stop / within 3% of the stop |
| Target reached / Near target | Price at or above the target / within 3% of the target |
| In buy zone | Price at or below the top of the buy zone |
| On plan | None of the above |

## 6.3 Trade reasons and review (`trade_reasons`)

Each filled trade can carry a strategy (long-term hold, swing, short-term, defensive, rebalance), a fundamental reason, a technical reason and a revisit date. After the revisit date you write the outcome. The Portfolio page lists trades that still need a reason. A trade price more than four times the current price is flagged as possibly pre-split.

# 7. Portfolio Journal and Period Digest

## 7.1 Journal page

- Entry types: decision, portfolio review, macro idea, external source. Each has a title, optional related symbols and an optional revisit date.
- Every entry stores a snapshot of the portfolio when it was written: position count, top-5 weight, weight in Cautious names, unanalysed weight, and the top 15 holdings with weight and view.
- The **review checklist** (`GET /journal/checklist`) is generated by code with no model call: concentration; trades in the period and which lack a reason; view and assumption-status changes; plan alerts; holdings never analysed or older than 30 days; items that are due; and the holdings with the largest weight x move. The default window starts at the last "portfolio review" entry, or 30 days back.
- **Start review** pre-fills the entry from the checklist and leaves three prompts: what changed in my thinking, what I will do next, what would prove me wrong. Every field has a "?" help bubble.
- Journal entries tagged with a symbol, and company notes, are merged into that company's timeline.
- Journal content stays local and is never sent to a model.

## 7.2 Period digest on Overview

The digest is about **your own portfolio**, not a macro view. The model has no live market data, and asking it to comment on "the market this month" invites invention, so that is deliberately not built. The default window is the last 30 days (monthly), with 7 and 90 days available. It uses the same data as the review checklist: counts of trades, thesis changes, plan alerts and due items, followed by the specific names and the largest movers. Everything is computed by code and costs no tokens.

# 8. Chinese Translation

- Analysis is always generated in English. Chinese is an on-demand translation, not a second analysis.
- A button at the top right of a company page switches the view. When the latest review has no translation, the Brief and Thesis pages show "Translate to Chinese". In the Timeline an older version can be translated individually. The full baseline report belongs to an earlier review and is translated separately.
- Only free-text fields are translated (view, assumption statements, triggers, causal mechanisms, change descriptions, narrative). Numbers, symbols, assumption ids, status labels and enums are never sent to the model.
- A translation is stored per review. Reviews never change after they are written, so a stored translation never goes stale; a new analysis creates a new review that can be translated when needed.
- The model must return items one by one. If fewer than 60% come back, nothing is saved and the user is asked to retry.

# 9. Front-end Information Architecture

Sidebar: Overview, Portfolio, Journal, then the company list grouped as Holdings / Watching / Ideas / Archived. Groups collapse (only Holdings is open by default; a group with matches opens while searching), there is a filter box above, and the add-symbol box, theme switch, today's AI usage and version stay fixed at the bottom. For Hong Kong and Singapore codes the sidebar shows the company name under the code, using the name from your broker export.

| Page | Content |
|---|---|
| Overview | Period digest; company table with search, filters (group, market, view, sector), several sort orders, 20 rows per page |
| Portfolio | Collapsible CSV import; summary cards (positions, top 5, weight in Cautious names, unanalysed weight, plan alerts); allocation bar (by sector, investment purpose, type, view); trades needing a reason; holdings table with search, filters, sorting, paging, plan editing, analysis and type change |
| Journal | Review checklist; new entry form; entry list filterable by type |
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
| `PUT/DELETE /plans/{symbol}` | Position plan |
| `GET /companies/{t}/trades`, `GET /trades/pending`, `PUT /trades/{id}/reason` | Trades and reasons |
| `GET/POST /journal`, `POST /journal/{id}/done`, `DELETE /journal/{id}` | Journal |
| `GET /journal/checklist?since=` | Review checklist and period digest |
| `GET /usage`, `GET /health` | Today's AI usage; version |

# 12. Testing

| Category | Content |
|---|---|
| Unit tests (`unittest`) | Change detection, broker CSV parsing and symbol normalisation, thesis health, prompts, model chain, plan status, translation field extraction, security checks |
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
| Done | Thesis tracking with change detection; four company pages; grouped sidebar and Overview; broker CSV import; position plans; trade reasons and review; portfolio journal and checklist; period digest; on-demand Chinese translation; list filters and paging; allocation bar; request guards and upload limit |
| Optional | An AI draft of the period digest (one call, based only on the digest's facts, labelled as a draft); currency conversion; price and plan tracking for ETFs; export |
| Wrap-up | Git clean-up is left for the author to do at the end of the project |
