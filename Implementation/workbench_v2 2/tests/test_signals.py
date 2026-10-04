import unittest
from app.core import signals as s


def ev(price=100, pe=20, gm=0.40, news=()):
    return {"market": {"current_price": price},
            "valuation": {"pe_ttm": pe, "free_cash_flow_yield": 0.04 * 100 / price},
            "financial_health": {"gross_margin": gm, "revenue_growth": 0.08},
            "analyst_consensus": {"target_consensus": 120},
            "recent_news": [{"title": t, "date": "2026-09-01"} for t in news]}


class SignalTests(unittest.TestCase):
    def test_initial(self):
        d = s.compute_delta(ev(), None)
        self.assertEqual(s.classify(d)[0], "material")

    def test_price_rally_is_not_a_fundamental_change(self):
        # price +20%, P/E +20% (earnings unchanged), FCF yield falls with price
        d = s.compute_delta(ev(price=120, pe=24), ev())
        self.assertEqual(d["valuation_changes"], [])
        self.assertTrue(d["price_driven_valuation"])
        self.assertEqual(s.classify(d)[0], "none")

    def test_multiple_moves_beyond_price_is_flagged(self):
        d = s.compute_delta(ev(price=100, pe=26), ev())  # price flat, P/E +30%
        self.assertEqual(s.classify(d)[0], "material")

    def test_margin_change_minor_vs_material(self):
        self.assertEqual(s.classify(s.compute_delta(ev(gm=0.415), ev()))[0], "minor")
        self.assertEqual(s.classify(s.compute_delta(ev(gm=0.30), ev()))[0], "material")

    def test_news_keywords(self):
        d = s.compute_delta(ev(news=["Company raises guidance for FY27"]), ev())
        self.assertEqual(s.classify(d)[0], "material")
        d = s.compute_delta(ev(news=["公司宣布启动股份回购"]), ev())
        self.assertEqual(s.classify(d)[0], "minor")
        d = s.compute_delta(ev(news=["Stock drifts on quiet day"]), ev())
        self.assertEqual(s.classify(d)[0], "none")

    def test_fingerprint_ignores_price_and_news(self):
        self.assertEqual(s.fingerprint(ev(price=100)), s.fingerprint(ev(price=137, news=["x"])))
        self.assertNotEqual(s.fingerprint(ev(gm=0.40)), s.fingerprint(ev(gm=0.35)))

    def test_compact_drops_nulls(self):
        e = ev(); e["company"] = {"name": "X", "employees": 5, "sector": None, "long_description": "a" * 900}
        c = s.compact_evidence(e)
        self.assertNotIn("sector", c["company"]); self.assertEqual(len(c["company"]["long_description"]), 500)


if __name__ == "__main__":
    unittest.main()
