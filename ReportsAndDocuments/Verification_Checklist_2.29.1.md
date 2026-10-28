# 2.29.1 manual checks (real Yahoo data)

Unzip workbench_v2_2.29.1.zip, keep your `workbench.db` and `valuation.db` (no migration this time), start the server, check the version `v2.29.1-read-first`. Import each company again (old imports still work, but re-import to get the new cash-flow base). Run `python -m pytest -q` and `node tests/ui_smoke.js`.

| Company | What should be different now |
|---|---|
| **0883.HK** | FY2026 FCF per share is no longer below the trailing figure; the "multiple +7%/yr" is gone or small. Dividend note appears (yield). With the exit in an analyst year, the growth inputs are greyed and the cards say "growth not used". |
| **INTC** | P/E is "use with care" (trailing EPS negative), not "does not suit". P/FCF is "does not suit" and is not starred. Default exit P/E is at most the top of the reference range, with a note saying why; today's 57x stays in the reference table. Share change default is 0. |
| **DEO** | The return split no longer shows "+40% earnings / −25% multiple": it starts from FY2027 (analyst) and says why. "Read this first" shows the lenses (yours / reference / cautious). |
| **MSFT** | "Read this first" shows how much of the Base return depends on the exit multiple, and "what the price already asks for" at three multiples. |

Click one suggested-settings button: it fills the form field and recalculates; nothing is saved until you press Save.
