import json, sqlite3, unittest
from app.core.snapshots import history_rows, delete_record, prune_data


def db(rows):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE valuations (id TEXT PRIMARY KEY, ticker TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
    for r in rows:
        c.execute("INSERT INTO valuations VALUES (?,?,?,?,?)", (r[0], r[1], r[2], r[3], json.dumps(r[4]) if not isinstance(r[4], str) else r[4]))
    return c


class History(unittest.TestCase):
    def test_labels_and_facts(self):
        c = db([("d1", "WMT", "data", "2026-10-13T20:24:00+00:00", dict(quote=dict(value=112.28, currency="USD"))),
                ("a1", "WMT", "analysis", "2026-10-14T01:34:00+00:00",
                 dict(data_id="d1", result=dict(assumptions=dict(method="pe", years=3, required_return=.1),
                                                scenarios=[dict(scenario="Bear", price_cagr=.0168), dict(scenario="Base", price_cagr=.0831)]))),
                ("x1", "OTHER", "data", "2026-10-14T01:35:00+00:00", {})])
        rows = history_rows(c, "wmt")
        self.assertEqual([r["id"] for r in rows], ["a1", "d1"])                       # newest first, only this ticker
        self.assertEqual(rows[0]["label"], "Saved analysis")
        self.assertEqual(rows[0]["summary"]["method"], "P/E")
        self.assertAlmostEqual(rows[0]["summary"]["base"], .0831)
        self.assertEqual(rows[1]["summary"]["price"], 112.28)

    def test_old_or_broken_records_do_not_break_the_list(self):
        c = db([("a1", "WMT", "analysis", "2026-10-10T17:00:00+00:00", dict(data_id="d0")),
                ("a2", "WMT", "analysis", "2026-10-10T17:01:00+00:00", "not json"),
                ("c1", "WMT", "comparison", "2026-10-10T17:02:00+00:00", dict(result=dict(rows=[])))])
        rows = history_rows(c, "WMT")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["label"], "Saved comparison")
        self.assertIsNone(next(r for r in rows if r["id"] == "a1")["summary"]["base"])


class Delete(unittest.TestCase):
    def rows(self):
        return db([("d1", "WMT", "data", "t1", dict(quote={})), ("d2", "WMT", "data", "t2", dict(quote={})), ("d3", "WMT", "data", "t3", dict(quote={})),
                   ("a1", "WMT", "analysis", "t4", dict(data_id="d2", result={})), ("o1", "MU", "data", "t5", {})])

    def test_data_in_use_is_refused_and_analysis_can_go(self):
        c = self.rows()
        self.assertEqual(delete_record(c, "d2"), "in_use")
        self.assertEqual(delete_record(c, "a1"), "deleted")
        self.assertEqual(delete_record(c, "d2"), "deleted")      # nothing uses it any more
        self.assertEqual(delete_record(c, "nope"), "missing")

    def test_prune_keeps_latest_and_anything_in_use(self):
        c = self.rows()
        self.assertEqual(prune_data(c, "wmt"), 1)               # d1 only: d3 is the newest, d2 is used
        left = {r[0] for r in c.execute("SELECT id FROM valuations")}
        self.assertEqual(left, {"d2", "d3", "a1", "o1"})        # other tickers untouched

    def test_comparison_keeps_its_data(self):
        c = db([("d1", "A", "data", "t", {}), ("d2", "A", "data", "t", {}), ("c1", "A+B", "comparison", "t", dict(data_ids=["d1"]))])
        self.assertEqual(prune_data(c, "A"), 0)


if __name__ == "__main__":
    unittest.main()
