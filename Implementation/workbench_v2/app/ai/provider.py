"""LLM access. System prompt goes through `system_instruction`; user content is compact JSON.
Output is schema-constrained, truncation is detected and retried once."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .. import config
from .prompts import dumps


class AIProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class AIResult:
    data: dict[str, Any]
    usage: dict[str, int] = field(default_factory=dict)


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
        else:
            out = {
                "one_liner": payload.get("prior_one_liner", "[mock] update"),
                "view": payload.get("prior_view", "neutral"), "view_change": "unchanged",
                "assumption_updates": [], "new_assumptions": [],
                "changes": [{"what": "[mock] evidence changed", "so_what": "[mock] no interpretation in mock mode"}],
                "valuation_note": "", "monitor_adds": [], "rebaseline_recommended": False,
                "rebaseline_reason": "", "narrative": "[mock] Mock update.",
            }
        return AIResult(schema.model_validate(out).model_dump(mode="json"), {"input": 0, "output": 0})


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self, model: str):
        if not model:
            raise AIProviderError("missing_model", "AI_MODEL is not configured.")
        if not config.GEMINI_API_KEY:
            raise AIProviderError("missing_ai_credentials", "GEMINI_API_KEY is not configured.")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise AIProviderError("sdk_missing", "pip install -U google-genai") from exc
        self.model, self._types = model, types
        self._client = genai.Client(api_key=config.GEMINI_API_KEY)

    def run(self, *, system, payload, schema, max_tokens) -> AIResult:
        last: Exception | None = None
        for attempt in (1, 2):
            note = "" if attempt == 1 else "\nIMPORTANT: your previous output was cut off or invalid. Be much shorter."
            try:
                cfg = self._types.GenerateContentConfig(
                    system_instruction=system + note, response_mime_type="application/json",
                    response_schema=schema, temperature=0.3, max_output_tokens=max_tokens)
                resp = self._client.models.generate_content(
                    model=self.model, contents=dumps(payload), config=cfg)
                um = getattr(resp, "usage_metadata", None)
                usage = {"input": getattr(um, "prompt_token_count", 0) or 0,
                         "output": getattr(um, "candidates_token_count", 0) or 0}
                cands = getattr(resp, "candidates", None) or []
                if cands and "MAX_TOKENS" in str(getattr(cands[0], "finish_reason", "")):
                    raise AIProviderError("truncated", "Output hit max_output_tokens.")
                parsed = getattr(resp, "parsed", None)
                if isinstance(parsed, BaseModel):
                    return AIResult(parsed.model_dump(mode="json"), usage)
                text = (getattr(resp, "text", "") or "").strip()
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
                return AIResult(schema.model_validate(json.loads(text)).model_dump(mode="json"), usage)
            except AIProviderError as e:
                last = e
            except Exception as e:   # validation, JSON, network
                last = AIProviderError("ai_error", str(e)[:400])
        assert last is not None
        raise last if isinstance(last, AIProviderError) else AIProviderError("ai_error", str(last)[:400])


def build_provider() -> BaseProvider:
    if config.AI_PROVIDER == "mock":
        return MockProvider()
    if config.AI_PROVIDER in {"gemini", "google"}:
        return GeminiProvider(config.AI_MODEL)
    raise AIProviderError("unsupported_provider", f"AI_PROVIDER={config.AI_PROVIDER}")
