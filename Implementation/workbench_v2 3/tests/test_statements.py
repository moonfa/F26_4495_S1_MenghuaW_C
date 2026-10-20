import unittest
from app.core import statements as st, signals
from app.core.plan import plan_status as ps


def q(end, rev, op, ocf=None, capex=None, fy=2026, fp="Q1"):
    d = {"period_ending": end, "revenue": rev, "operating_income": op, "fiscal_year": fy, "fiscal_period": fp}
    c = {"period_ending": end, "operating_cash_flow": ocf, "capital_expenditure": capex}
    return d, c


ENDS = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"]
REV = [130, 120, 115, 110, 100, 95]


def stm(n=6):
    inc, cash = [], []
    for e, r in zip(ENDS[:n], REV[:n]):
        a, b = q(e, r, r * 0.2, ocf=r * 0.3, capex=-r * 0.1)
        inc.append(a); cash.append(b)
    return {"annual": [], "quarterly": st.merge(inc, cash, 8)}


class StatementTests(unittest.TestCase):
    def test_merge_and_fcf(self):
        m = stm()["quarterly"]
        self.assertEqual(m[0]["period_ending"], "2026-06-30")
        self.assertAlmostEqual(m[0]["free_cash_flow"], 130 * 0.2)       # ocf + (negative capex)

    def test_growth_and_margin(self):
        v = st.view(stm())["quarterly"]
        self.assertAlmostEqual(v[0]["revenue_yoy"], 0.3)                  # 130 vs 100 four quarters earlier
        self.assertAlmostEqual(v[0]["operating_margin"], 0.2)
        self.assertIsNone(v[4]["revenue_yoy"])

    def test_trend_for_model_is_small(self):
        t = st.quarterly_trend(stm())
        self.assertEqual(len(t["quarters"]), 4)
        self.assertIn("operating_margin_change_over_4q_pp", t["basis"] and t)
        self.assertIsNone(st.quarterly_trend({}))

    def test_new_quarter_is_a_change_only_if_anchor_had_quarters(self):
        old = {"statements": stm(5), "financial_health": {}}
        new = {"statements": stm(6), "financial_health": {}}
        self.assertEqual(signals.compute_delta(new, {"statements": stm(6)})["status"], "unchanged")
        # drop the newest row from the anchor: the new evidence shows a later quarter
        a = stm(6); a["quarterly"] = a["quarterly"][1:]
        d = signals.compute_delta(new, {"statements": a})
        self.assertTrue(any(c["metric"] == "statements.new_quarter" for c in d["fundamental_changes"]))
        self.assertEqual(signals.compute_delta(new, {"financial_health": {}})["status"], "unchanged")   # old snapshot without statements

    def test_model_never_gets_raw_statements(self):
        e = signals.compact_evidence({"statements": stm(), "company": {}, "market": {}})
        self.assertNotIn("statements", e)
        self.assertIn("quarterly_trend", e["derived"])


class SizingTests(unittest.TestCase):
    def test_over_max_flag(self):
        r = ps(100, None, None, None, value=7000, target_amount=5000, max_amount=6000, weight=0.07)
        self.assertEqual(r["status"], "over_max")
        self.assertEqual(r["sizing"]["room_to_max"], -1000)
        self.assertEqual(r["sizing"]["room_to_target"], -2000)
        self.assertEqual(r["sizing"]["pct_of_portfolio"], 7.0)

    def test_room_left(self):
        r = ps(100, None, None, None, value=3200, target_amount=5000, max_amount=6000)
        self.assertEqual(r["status"], "on_plan")
        self.assertEqual((r["sizing"]["room_to_target"], r["sizing"]["room_to_max"]), (1800, 2800))
        self.assertIsNone(ps(100, 90, 130, 85)["sizing"])

    def test_not_held_yet(self):
        r = ps(100, None, None, None, value=0, target_amount=5000)
        self.assertEqual(r["sizing"]["room_to_target"], 5000)
        self.assertFalse(r["sizing"]["over_max"])

    def test_stop_outranks_over_max(self):
        self.assertEqual(ps(80, None, None, 85, value=9000, max_amount=6000)["status"], "stop_breached")


if __name__ == "__main__":
    unittest.main()


