import unittest
from app.core import thesis as t
from app.adapters import news_fallback as n


class ThesisTests(unittest.TestCase):
    def test_hints_are_sector_specific(self):
        self.assertIn("same-store", t.sector_hint({"industry": "Restaurants"}))
        self.assertIn("ASP", t.sector_hint({"industry": "Semiconductors"}))
        self.assertNotIn("ASP", t.sector_hint({"industry": "Restaurants"}))
        self.assertIsNone(t.sector_hint({"industry": "Unknownium"}))

    def test_health(self):
        a = lambda i, st, m="medium": {"id": i, "status": st, "materiality": m}
        self.assertEqual(t.health([a("a1", "holding"), a("a2", "strengthened")])[0], "Intact")
        self.assertEqual(t.health([a("a1", "weakened")])[0], "Watch")
        self.assertEqual(t.health([a("a1", "unverified", "high")])[0], "Watch")
        self.assertEqual(t.health([a("a1", "weakened", "high")])[0], "At risk")
        self.assertEqual(t.health([{"id": "a1", "status": "broken"}])[0], "At risk")
        self.assertEqual(t.health([{"id": "a1", "status": "holding"}])[0], "Intact")   # old states lack materiality


class NewsTests(unittest.TestCase):
    def test_nested_and_flat(self):
        nested = {"content": {"title": " A ", "pubDate": "2026-10-01T10:00:00Z", "canonicalUrl": {"url": "https://x/a"}, "provider": {"displayName": "Reuters"}}}
        flat = {"title": "B", "link": "https://x/b", "publisher": "AP", "providerPublishTime": 1790000000}
        r = n.parse_yf_news([nested, flat, {"foo": 1}, "bad"])
        self.assertEqual([x["title"] for x in r], ["A", "B"])
        self.assertEqual((r[0]["url"], r[0]["source"]), ("https://x/a", "Reuters"))
        self.assertEqual((r[1]["url"], r[1]["source"]), ("https://x/b", "AP"))
        self.assertTrue(r[1]["date"].startswith("2026-"))


class RssTests(unittest.TestCase):
    def test_rss(self):
        xml = """<rss><channel><item><title> Headline A </title><link>https://x/a</link><pubDate>Mon, 05 Oct 2026 14:00:00 +0000</pubDate></item><item><title></title></item></channel></rss>"""
        r = n.parse_rss(xml)
        self.assertEqual(len(r), 1); self.assertEqual(r[0]["title"], "Headline A"); self.assertTrue(r[0]["date"].startswith("2026-10-05"))


if __name__ == "__main__":
    unittest.main()
