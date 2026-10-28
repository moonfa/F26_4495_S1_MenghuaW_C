# 2.29.0 manual verification checklist (needs real Yahoo data)

Setup: unzip workbench_v2_2.29.0.zip, copy ONLY your old `workbench.db` into the new folder, start the server, check the sidebar shows `v2.29.0-valuation-table`. On first start `valuation.v3.bak.db` appears next to `valuation.db` (old records are removed from `valuation.db`). Run `python -m pytest -q` and `node tests/ui_smoke.js`.

For each company: Valuation lab → Company → Import latest data.

| Company | What to check |
|---|---|
| **MSFT** (June year end) | Table 1 shows FY-3..FY-1 reported, TTM (grey, reference), FY0e and FY1e analyst, growth under each value. Exit dropdown lists June year ends with ≈ years (e.g. FY2029 ≈ 2.7). P/E, P/FCF, EV/EBITDA all run. FCF FY0e/FY1e show in the "derived" colour. Click a multiple row / growth row: it highlights; type another number: "Your own value" appears. Base return is higher than 2.28 by design (earlier exit, multiple on this year's estimate). |
| **DEO** (June year end, earnings dislocation) | The "earnings far below analysts" card appears; the result starts from the analyst years; the grid has a "no recovery" row. |
| **0883.HK** (HKD price, CNY accounts) | Currency conversion note still shows; all three methods run with one currency; no mismatch error. |
| **INTC** (tiny FCF) | P/FCF exit multiple is NOT pre-filled when today's multiple is above 150×; the message says why; typing 1230 gives a readable error, not a raw list. |

Flow checks:
1. Change the exit year: years in the result line change; Bear/Base/Bull analyst years stay the same.
2. Save an analysis, open the company page → Valuation tab: it shows "Sold at the end of FYxxxx" and the return at your plan price.
3. Import again later when analyst EPS has moved ≥3% (or revenue ≥2%): a factual line appears in the lab and "may be out of date" on the company tab; the saved analysis itself is unchanged.
4. Compare MSFT, DEO: each row shows its own exit year and years.
