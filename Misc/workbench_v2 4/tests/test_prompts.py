import unittest
from app.ai import prompts as p


class PromptTests(unittest.TestCase):
    def test_rules_have_no_company_specific_examples(self):
        for w in ("NVIDIA", "HBM", "ASIC", "hyperscaler", "Micron"):
            self.assertNotIn(w, p.BASELINE_SYSTEM + p.UPDATE_SYSTEM)

    def test_baseline_payload_injects_sector_hint(self):
        out = p.baseline_payload({"company": {"industry": "Restaurants"}}, "en", None)
        self.assertIn("same-store", out["kpi_hint"])
        self.assertNotIn("kpi_hint", p.dumps(p.baseline_payload({"company": {"industry": "Unknownium"}}, "en", None)))

    def test_update_payload_tolerates_old_states(self):
        prior = {"view": "neutral", "one_liner": "x", "state": {"profile": {"classification": "c", "key_drivers": []},
                 "assumptions": [{"id": "a1", "statement": "s", "status": "holding", "kill_criteria": "k"}]}}
        self.assertEqual(p.update_payload(prior, {"status": "changed"}, "minor", "en", 0.1)["assumptions"][0]["materiality"], None)


if __name__ == "__main__":
    unittest.main()
