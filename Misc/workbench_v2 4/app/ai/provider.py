"""LLM access. System prompt goes through `system_instruction`; user content is compact JSON.
Output is schema-constrained, truncation is detected and retried once."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .. import config
from .prompts import dumps


log = logging.getLogger("uvicorn.error")


def _classify(e: Exception) -> str | None:
    """quota / unavailable / model_unavailable errors are rejected before any tokens are spent: try the next model."""
    code, msg = getattr(e, "code", None), str(e).lower()
    if code == 429 or any(w in msg for w in ("resource_exhausted", "quota", "rate limit")):
        return "quota"
    if code in (500, 503) or any(w in msg for w in ("unavailable", "overloaded")):
        return "unavailable"
    if code == 404 or "not found" in msg or "is not supported" in msg:
        return "model_unavailable"
    return None


class AIProviderError(RuntimeError):
    def __init__(self, code: str, message: str, usage: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.usage = code, message, usage or {}


@dataclass
class AIResult:
    data: dict[str, Any]
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = ""


class BaseProvider:
    name = "base"
    model = ""

    def run(self, *, system: str, payload: dict, schema: type[BaseModel], max_tokens: int) -> AIResult:
        raise NotImplementedError


class MockProvider(BaseProvider):
    name, model = "mock", "mock-model"

    def run(self, *, system, payload, schema, max_tokens) -> AIResult:
        if schema.__name__ == "BaselineOutput":
            ev = payload.get("evidence", {})
            name = (ev.get("company") or {}).get("name") or (ev.get("company") or {}).get("symbol") or "Company"
            out = {
                "one_liner": f"[mock] Baseline thesis for {name}.",
                "view": "neutral",
                "assumptions": [
                    {"id": f"a{i}", "statement": f"[mock] Core assumption {i}", "status": "unverified",
                     "evidence": [], "kill_criteria": f"[mock] Kill criterion {i}", "confidence": "low"}
                    for i in (1, 2, 3)],
                "profile": {"classification": "mock", "business_model": "mock", "moat": "mock",
                            "key_drivers": ["mock driver"], "key_risks": ["mock risk"],
                            "bear_case": "mock bear case", "valuation_view": "mock"},
                "monitor": [{"indicator": "Gross margin", "why": "mock", "trigger": "< prior - 2pp"},
                            {"indicator": "Revenue growth", "why": "mock", "trigger": "< 0"}],
                "report_markdown": f"# {name}\n\nMock baseline. Set AI_PROVIDER=gemini for a real analysis.",
            }
        elif schema.__name__ == "TranslationOutput":
            out = {"items": [{"k": i["k"], "t": "[中文] " + i["t"]} for i in payload.get("items", [])]}
        else:
            out = {
                "one_liner": payload.get("prior_one_liner", "[mock] update"),
                "view": payload.get("prior_view", "neutral"), "view_change": "unchanged",
                "assumption_updates": [], "new_assumptions": [],
                "changes": [{"what": "[mock] evidence changed", "so_what": "[mock] no interpretation in mock mode"}],
                "valuation_note": "", "monitor_adds": [], "rebaseline_recommended": False,
                "rebaseline_reason": "", "narrative": "[mock] Mock update.",
            }
        return AIResult(schema.model_validate(out).model_dump(mode="json"), {"input": 0, "output": 0}, "mock-model")


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self, models: list[str]):
        if not models:
            raise AIProviderError("missing_model", "AI_MODEL is not configured.")
        if not config.GEMINI_API_KEY:
            raise AIProviderError("missing_ai_credentials", "GEMINI_API_KEY is not configured.")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise AIProviderError("sdk_missing", "pip install -U google-genai") from exc
        self.models, self.model = list(models), models[0]      # .model = primary (cache key / display)
        self._types = types
        self._client = genai.Client(api_key=config.GEMINI_API_KEY)

    def _call(self, model, system, payload, schema, max_tokens, budget):
        kw = dict(system_instruction=system, response_mime_type="application/json",
                  response_schema=schema, temperature=0.3, max_output_tokens=max_tokens)
        if budget is not None:
            try:
                kw["thinking_config"] = self._types.ThinkingConfig(thinking_budget=budget)
            except Exception:   # SDK/model without this setting
                pass
        return self._client.models.generate_content(
            model=model, contents=dumps(payload), config=self._types.GenerateContentConfig(**kw))

    def run(self, *, system, payload, schema, max_tokens) -> AIResult:
        """Walk the model chain. A model that is out of quota / overloaded / unknown is skipped (no tokens were spent);
        any other failure stops the walk so we never burn several models on one bad request."""
        total = {"input": 0, "output": 0, "thinking": 0}
        skipped: list[str] = []
        last: AIProviderError | None = None
        for model in self.models:
            try:
                res = self._run_one(model, system, payload, schema, max_tokens, total)
                res.model = model
                res.usage = {**total, **({"skipped_models": skipped} if skipped else {})}
                return res
            except AIProviderError as e:
                last = e
                if e.code in ("quota", "unavailable", "model_unavailable"):
                    log.warning("Model %s skipped (%s): %s", model, e.code, e.message[:160])
                    skipped.append(f"{model}:{e.code}")
                    continue
                break
        assert last is not None
        last.usage = dict(total)
        last.message = f"{last.message} Models tried: {', '.join(skipped) or self.models[0]}. Tokens billed: input {total['input']}, output {total['output']}, thinking {total['thinking']}."
        raise last

    def _run_one(self, model, system, payload, schema, max_tokens, total) -> AIResult:
        """Thinking tokens count against max_output_tokens, so: cap thinking, leave headroom, and on truncation retry
        ONCE with a larger limit. Usage of every attempt is summed because truncated calls are still billed."""
        budget, limit, last = config.AI_THINKING_BUDGET, max_tokens, None
        for attempt in (1, 2):
            note = "" if attempt == 1 else "\nIMPORTANT: your previous output was cut off or invalid. Be much shorter."
            try:
                try:
                    resp = self._call(model, system + note, payload, schema, limit, budget)
                except Exception as exc:
                    if budget is not None and "thinking" in str(exc).lower():
                        budget = None
                        resp = self._call(model, system + note, payload, schema, limit, budget)
                    else:
                        raise
                um = getattr(resp, "usage_metadata", None)
                total["input"] += getattr(um, "prompt_token_count", 0) or 0
                total["output"] += getattr(um, "candidates_token_count", 0) or 0
                total["thinking"] += getattr(um, "thoughts_token_count", 0) or 0
                cands = getattr(resp, "candidates", None) or []
                if cands and "MAX_TOKENS" in str(getattr(cands[0], "finish_reason", "")):
                    raise AIProviderError("truncated", "Output hit the token limit.")
                parsed = getattr(resp, "parsed", None)
                if isinstance(parsed, BaseModel):
                    return AIResult(parsed.model_dump(mode="json"), dict(total))
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (getattr(resp, "text", "") or "").strip(), flags=re.I)
                return AIResult(schema.model_validate(json.loads(text)).model_dump(mode="json"), dict(total))
            except AIProviderError as e:
                last = e
                limit = int(limit * 1.5)
            except Exception as e:
                kind = _classify(e)
                if kind:
                    raise AIProviderError(kind, str(e)[:240]) from e
                last = AIProviderError("ai_error", str(e)[:400])
        assert last is not None
        raise last


def _chain(*first: str) -> list[str]:
    seen, out = set(), []
    for m in [*first, config.AI_MODEL, *config.AI_MODEL_FALLBACKS]:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def build_provider() -> BaseProvider:
    if config.AI_PROVIDER == "mock":
        return MockProvider()
    if config.AI_PROVIDER in {"gemini", "google"}:
        return GeminiProvider(_chain())
    raise AIProviderError("unsupported_provider", f"AI_PROVIDER={config.AI_PROVIDER}")


def build_baseline_provider() -> BaseProvider | None:
    """Optional stronger model tried first for baselines (rare, decides thesis quality). None = normal provider."""
    if config.AI_PROVIDER in {"gemini", "google"} and config.AI_MODEL_BASELINE:
        return GeminiProvider(_chain(config.AI_MODEL_BASELINE))
    return None
