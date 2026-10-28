"""valuation.db upgrade (2.28 → 2.29) and the analyst-revision notice on import. Uses a temporary database file."""
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

try:
    import fastapi  # noqa: F401
except ImportError:                      # a bare environment: stand in for the three names the module imports so the storage code can still be tested
    fa = types.ModuleType('fastapi'); fr = types.ModuleType('fastapi.responses')

    class HTTPException(Exception):
        def __init__(self, status_code, detail=None):
            super().__init__(detail); self.status_code = status_code; self.detail = detail

    class APIRouter:
        def __getattr__(self, name):
            return lambda *a, **k: (lambda f: f)
    fa.APIRouter, fa.HTTPException, fr.FileResponse = APIRouter, HTTPException, object
    sys.modules['fastapi'], sys.modules['fastapi.responses'] = fa, fr

from app.api import valuation as V
from app.core.valuation import Assumptions, calculate
from tests.fixtures_val import company


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = V.DB
        V.DB = Path(self.tmp.name) / 'valuation.db'

    def tearDown(self):
        V.DB = self.old
        self.tmp.cleanup()

    def _old_db(self):
        c = sqlite3.connect(V.DB)
        c.execute("CREATE TABLE valuations (id TEXT PRIMARY KEY, ticker TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
        c.execute("INSERT INTO valuations VALUES ('d3','MSFT','data','2026-09-01T00:00:00+00:00',?)", (json.dumps(dict(schema_version='valuation-data-v3')),))
        c.execute("INSERT INTO valuations VALUES ('a3','MSFT','analysis','2026-09-01T00:00:00+00:00',?)", (json.dumps(dict(result=dict(formula_version='valuation-v3'))),))
        c.execute("INSERT INTO valuations VALUES ('c3','MSFT+DEO','comparison','2026-09-01T00:00:00+00:00',?)", (json.dumps(dict(result=dict(rows=[dict(methods=[dict(years=3)])]))),))
        c.commit(); c.close()

    def test_upgrade_backs_up_then_clears_old_records(self):
        self._old_db()
        with V.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM valuations").fetchone()[0], 0)
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], V.SCHEMA_VERSION)
        bak = V.DB.with_name('valuation.v3.bak.db')
        self.assertTrue(bak.exists())
        b = sqlite3.connect(bak)
        self.assertEqual(b.execute("SELECT COUNT(*) FROM valuations").fetchone()[0], 3); b.close()

    def test_second_start_changes_nothing_and_new_records_survive(self):
        self._old_db()
        with V.connect():
            pass
        d = company()
        rec = V.save('ABC', 'data', d)
        with V.connect():
            pass
        self.assertEqual(V.read(rec['id'])['ticker'], 'ABC')

    def test_a_new_database_needs_no_backup(self):
        with V.connect():
            pass
        self.assertFalse(V.DB.with_name('valuation.v3.bak.db').exists())

    def test_import_says_what_moved_in_the_analyst_numbers(self):
        old = company()
        V.save('ABC', 'data', old)
        res = calculate(old, Assumptions(exit_fy='2029-12-31', required_return=.1, growth=.1, exit_pe=20, growth_spread=.03, pe_spread=.1))
        V.save('ABC', 'analysis', dict(data_id='x', result=res))
        cut = company(valuation='2026-10-19', est=(2.2, 2.5 * .9, 1100e6, 1210e6))
        self.assertIn('analyst EPS for FY2027 moved from 2.50 to 2.25', V.estimate_notice('ABC')(cut))
        self.assertIsNone(V.estimate_notice('ABC')(company(valuation='2026-10-19')))
        self.assertIsNone(V.estimate_notice('NONE')(cut))                   # nothing saved for this ticker: nothing to compare


if __name__ == '__main__':
    unittest.main()
