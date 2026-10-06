# Personal Investment Workbench v2 — Thesis Tracker

Tracks an investment **thesis** per company over time instead of regenerating one-off reports.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # AI_PROVIDER=mock works with no API key
python -m uvicorn app.main:app --reload --reload-dir app   # --reload-dir app: do not watch .venv (OpenBB rebuilds files there)
./check.sh   # shows which folder/version the server on :8000 is really running
python -m unittest tests.test_signals -v   # pure-Python change-detection tests
python -m unittest tests.test_signals tests.test_portfolio tests.test_thesis tests.test_prompts   # pure-Python tests
python -m pytest -q                        # service lifecycle test (needs the installed packages)
```

Main call: `POST /api/v1/companies/{ticker}/refresh` — the system decides between a baseline,
an LLM update, or a free no-change check. Read `docs/DESIGN.md` first.
The frontend is a single file, `app/static/index.html`, served at `/`.
