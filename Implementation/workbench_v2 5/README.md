# Personal Investment Workbench v2 — Thesis Tracker

Tracks an investment **thesis** per company over time instead of regenerating one-off reports.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # AI_PROVIDER=mock works with no API key
python -m uvicorn app.main:app --reload --reload-dir app   # --reload-dir app: do not watch .venv. Keep the default host 127.0.0.1; never use --host 0.0.0.0 (the app has no login)
./check.sh   # shows which folder/version the server on :8000 is really running
python -m unittest tests.test_signals -v   # pure-Python change-detection tests
python -m unittest tests.test_signals tests.test_portfolio tests.test_thesis tests.test_prompts   # pure-Python tests
python -m pytest -q                        # service lifecycle test (needs the installed packages)
```

Main call: `POST /api/v1/companies/{ticker}/refresh` — the system decides between a baseline,
an LLM update, or a free no-change check. Read `docs/DESIGN.md` first.
The frontend is a single file, `app/static/index.html`, served at `/`.

## Journal (v2.7.0)
Sidebar → Journal. Private portfolio-level diary (decision / portfolio review / macro idea / external source). Each entry stores a snapshot of the portfolio at the time. The review checklist (`GET /api/v1/journal/checklist`) is computed from stored data with no model call: exposure, trades since the last review (and which lack a reason), thesis/view changes, plan alerts, stale holdings, items due. Entries tagged with a ticker also appear in that company's Timeline. New table `journal_entries` is created automatically on start-up.
Trade import now reports rows / unfilled / unreadable / symbols found, to diagnose missing trades.
