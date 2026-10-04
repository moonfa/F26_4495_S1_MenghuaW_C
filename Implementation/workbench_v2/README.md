# Personal Investment Workbench v2 — Thesis Tracker

Tracks an investment **thesis** per company over time instead of regenerating one-off reports.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # AI_PROVIDER=mock works with no API key
uvicorn app.main:app --reload   # API docs: http://127.0.0.1:8000/docs
python -m unittest tests.test_signals -v   # pure-Python change-detection tests
python -m pytest -q                        # service lifecycle test
```

Main call: `POST /api/v1/companies/{ticker}/refresh` — the system decides between a baseline,
an LLM update, or a free no-change check. Read `docs/DESIGN.md` first.
The frontend is a single file, `app/static/index.html`, served at `/`.
