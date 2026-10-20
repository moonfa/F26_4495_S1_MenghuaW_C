import unittest

from app.core import calendar as c


class CalendarTests(unittest.TestCase):
    def test_market_local_date(self):
        # 01:30 UTC on the 18th is still the 17th in New York, but already the 18th in Hong Kong
        self.assertEqual(c.local_date("2026-07-18T01:30:00+00:00", "MU"), "2026-07-17")
        self.assertEqual(c.local_date("2026-07-18T01:30:00+00:00", "0700.HK"), "2026-07-18")
        self.assertEqual(c.local_date("2026-07-18T20:30:00+00:00", "0700.HK"), "2026-07-19")

    def test_round_trips(self):
        t = [{"id": 1, "symbol": "MU", "side": "buy", "date": "2026-07-01"}, {"id": 2, "symbol": "MU", "side": "sell", "date": "2026-07-08"},
             {"id": 3, "symbol": "NVDA", "side": "buy", "date": "2026-07-01"}, {"id": 4, "symbol": "NVDA", "side": "sell", "date": "2026-09-01"}]
        self.assertEqual(c.round_trips(t), {1, 2})

    def test_since(self):
        self.assertEqual(c.since_pct(100, 110), 0.1)
        self.assertIsNone(c.since_pct(None, 110))


if __name__ == "__main__":
    unittest.main()
