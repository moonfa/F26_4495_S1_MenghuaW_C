"""Model-chain behaviour with a fake Gemini client. Stubs pydantic / google-genai only when they are not installed."""
import sys
import types
import unittest

try:
    import pydantic  # noqa: F401
except ImportError:
    m = types.ModuleType("pydantic")
    m.BaseModel = type("BaseModel", (), {})
    sys.modules["pydantic"] = m
try:
    from google import genai  # noqa: F401
except ImportError:
    g, gg = types.ModuleType("google"), types.ModuleType("google.genai")
    gg.Client = lambda api_key=None: None
    gg.types = types.SimpleNamespace(GenerateContentConfig=lambda **kw: kw, ThinkingConfig=lambda **kw: kw)
    g.genai = gg
    sys.modules.update({"google": g, "google.genai": gg, "google.genai.types": gg.types})

from app import config
from app.ai import provider as P


class QuotaErr(Exception):
    code = 429


class Schema:
    @staticmethod
    def model_validate(d):
        return types.SimpleNamespace(model_dump=lambda mode=None: d)


class Resp:
    def __init__(self, text='{"ok": 1}'):
        self.text, self.parsed, self.candidates = text, None, []
        self.usage_metadata = types.SimpleNamespace(prompt_token_count=10, candidates_token_count=5, thoughts_token_count=2)


class Fake:
    def __init__(self, plan):
        self.plan, self.calls = plan, []
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        out = self.plan[model]
        if isinstance(out, Exception):
            raise out
        return out


def make(models, plan):
    config.GEMINI_API_KEY = "x"
    p = P.GeminiProvider(models)
    p._client = Fake(plan)
    p._types = types.SimpleNamespace(GenerateContentConfig=lambda **kw: kw, ThinkingConfig=lambda **kw: kw)
    return p


class ChainTests(unittest.TestCase):
    def test_falls_back_on_quota(self):
        p = make(["a", "b", "c"], {"a": QuotaErr("RESOURCE_EXHAUSTED"), "b": QuotaErr("quota"), "c": Resp()})
        r = p.run(system="s", payload={}, schema=Schema, max_tokens=100)
        self.assertEqual(r.model, "c"); self.assertEqual(r.usage["skipped_models"], ["a:quota", "b:quota"])
        self.assertEqual(p._client.calls, ["a", "b", "c"])

    def test_other_errors_stop_the_walk(self):
        p = make(["a", "b"], {"a": ValueError("boom"), "b": Resp()})
        with self.assertRaises(P.AIProviderError):
            p.run(system="s", payload={}, schema=Schema, max_tokens=100)
        self.assertNotIn("b", p._client.calls)

    def test_all_exhausted(self):
        p = make(["a", "b"], {"a": QuotaErr("quota"), "b": QuotaErr("quota")})
        with self.assertRaises(P.AIProviderError) as cm:
            p.run(system="s", payload={}, schema=Schema, max_tokens=100)
        self.assertEqual(cm.exception.code, "quota"); self.assertIn("a:quota", cm.exception.message)

    def test_chain_order_and_dedupe(self):
        config.AI_MODEL, config.AI_MODEL_FALLBACKS = "m1", ["m2", "m1", "m3"]
        self.assertEqual(P._chain(), ["m1", "m2", "m3"])
        self.assertEqual(P._chain("big"), ["big", "m1", "m2", "m3"])


if __name__ == "__main__":
    unittest.main()
