import unittest

from app.ai import prompts
from app.ai.provider import MockProvider
from app.ai.schemas import TranslationOutput
from app.core import translate as z

R = {"one_liner": "Margins hold.", "narrative": "# Title\n\nBody.", "changes": [{"what": "GM up", "so_what": "Pricing power"}],
     "state": {"profile": {"classification": "Memory", "business_model": "bm", "moat": "m", "bear_case": "b", "valuation_view": "v",
                           "key_drivers": ["d1", "d2"], "key_risks": ["r1"]},
               "assumptions": [{"id": "a1", "statement": "HBM demand persists", "status": "holding", "evidence": ["gm=0.4"],
                                "kill_criteria": "GM < 30%", "materiality": "high", "warning_trigger": ""}],
               "monitor": [{"indicator": "Gross margin", "why": "w", "trigger": "< 30%"}],
               "valuation": {"implication": "Priced for growth", "consensus_gap": ""}}}


class TranslateTests(unittest.TestCase):
    def test_flatten_only_free_text(self):
        f = z.flatten(R)
        self.assertIn("a.a1.statement", f)
        self.assertIn("profile.key_drivers.1", f)
        self.assertIn("changes.0.so_what", f)
        self.assertNotIn("a.a1.warning_trigger", f)            # empty strings are not sent
        self.assertFalse(any("evidence" in k or "status" in k for k in f))

    def test_localize_keeps_structure_and_falls_back(self):
        items = {"one_liner": "利润率稳定。", "a.a1.statement": "HBM需求持续", "profile.key_drivers.0": "驱动一"}
        out = z.localize(R, items)
        self.assertEqual(out["one_liner"], "利润率稳定。")
        a = out["state"]["assumptions"][0]
        self.assertEqual((a["statement"], a["status"], a["id"], a["evidence"]), ("HBM需求持续", "holding", "a1", ["gm=0.4"]))
        self.assertEqual(out["state"]["profile"]["key_drivers"], ["驱动一", "d2"])      # d2 untranslated -> English
        self.assertEqual(R["one_liner"], "Margins hold.")                                 # original untouched

    def test_mock_translation_roundtrip(self):
        src = z.flatten(R)
        res = MockProvider().run(system=prompts.TRANSLATE_SYSTEM, schema=TranslationOutput, payload=prompts.translate_payload(src), max_tokens=100)
        got = {i["k"]: i["t"] for i in res.data["items"]}
        self.assertEqual(set(got), set(src))
        self.assertEqual(z.localize(R, got)["narrative"], "[中文] # Title\n\nBody.")


if __name__ == "__main__":
    unittest.main()
