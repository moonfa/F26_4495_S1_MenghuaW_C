"""Orchestration: refresh evidence -> detect change -> (maybe) call the model -> store a Review.

Cost control: no thesis-relevant change => zero LLM calls. Minor/material => ONE small call that
sees the prior structured thesis plus the delta only. The static profile is generated once.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai import prompts
from .ai.provider import AIProviderError, BaseProvider
from .ai.schemas import BaselineOutput, UpdateOutput
from .core import signals
from .models import Company, Note, Review, Snapshot

VIEW_ORDER = {"cautious": 0, "neutral": 1, "constructive": 2}
BASELINE_MAX_TOKENS, UPDATE_MAX_TOKENS = 12000, 5000


log = logging.getLogger("uvicorn.error")


class ServiceError(Exception):
    def __init__(self, code: str, message: str, http: int = 400):
        super().__init__(message)
        self.code, self.message, self.http = code, message, http


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_or_create_company(session: Session, ticker: str, name: str | None = None) -> Company:
    t = ticker.strip().upper()
    c = session.scalar(select(Company).where(Company.ticker == t))
    if c is None:
        c = Company(ticker=t, name=name or t)
        session.add(c)
        session.flush()
    elif name and c.name == c.ticker:
        c.name = name
    return c


def latest_review(session: Session, company_id: int, *, analysed_only: bool = False) -> Review | None:
    q = select(Review).where(Review.company_id == company_id)
    if analysed_only:
        q = q.where(Review.kind != "check")
    return session.scalar(q.order_by(Review.created_at.desc(), Review.id.desc()))


def _view_change(prev: str | None, new: str) -> str:
    if prev is None:
        return "new"
    a, b = VIEW_ORDER[prev], VIEW_ORDER[new]
    return "up" if b > a else "down" if b < a else "unchanged"


def apply_update(state: dict, out: dict) -> dict:
    s = copy.deepcopy(state)
    by_id = {a["id"]: a for a in s["assumptions"]}
    for u in out["assumption_updates"]:
        a = by_id.get(u["id"])
        if a:
            a["status"], a["last_reason"] = u["new_status"], u["reason"]
            if u["evidence"]:
                a["evidence"] = u["evidence"]
    nxt = max([int(a["id"][1:]) for a in s["assumptions"]] + [0])
    for n in out["new_assumptions"]:
        nxt += 1
        n = dict(n, id=f"a{nxt}")
        s["assumptions"].append(n)
    s["monitor"] = (s["monitor"] + out["monitor_adds"])[:6]
    if out.get("valuation_note"):
        s.setdefault("valuation", {})["implication"] = out["valuation_note"]
    return s


def _hash(parts: dict) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def refresh(session: Session, ticker: str, *, adapter, provider: BaseProvider,
            language: str | None = None, force_rebaseline: bool = False,
            baseline_provider: BaseProvider | None = None) -> Review:
    try:
        evidence, meta = adapter.get_equity_research_snapshot(ticker.strip().upper())
    except Exception as exc:   # OpenBBAdapterError and anything the provider throws
        raise ServiceError(getattr(exc, "code", "evidence_error"), str(getattr(exc, "message", exc))[:300], 502)

    evidence.setdefault("data_quality", {})["warnings"] = [str(w)[:200] for w in (meta.get("warnings") or [])][:6]
    has_numbers = any(isinstance(v, (int, float)) for sec in ("valuation", "financial_health") for v in (evidence.get(sec) or {}).values())
    if signals.price_of(evidence) is None or not has_numbers:
        raise ServiceError("ticker_not_found", f"No market data found for '{ticker.strip().upper()}'. Check the ticker symbol. Nothing was saved and no model call was made.", 404)

    if not evidence.get("recent_news"):                         # the OpenBB news route often returns nothing
        from .adapters.news_fallback import fetch_news
        evidence["recent_news"], note = fetch_news(ticker.strip().upper())
        evidence["data_quality"]["warnings"].append(note[:400])

    name = (evidence.get("company") or {}).get("name")
    company = get_or_create_company(session, ticker, name)
    if language:
        company.language = language
    lang = company.language

    snap = Snapshot(company_id=company.id, price=signals.price_of(evidence),
                    fingerprint=signals.fingerprint(evidence), payload=evidence)
    session.add(snap)
    session.flush()

    anchor = latest_review(session, company.id, analysed_only=True)
    last = latest_review(session, company.id)
    anchor_ev = session.get(Snapshot, anchor.snapshot_id).payload if anchor else None
    delta = signals.compute_delta(evidence, anchor_ev)
    level, reason = signals.classify(delta)
    kind = ("baseline" if anchor is None else "rebaseline" if force_rebaseline else
            "update" if level != "none" else "check")

    # ---- no thesis-relevant change: free, deterministic heartbeat ----
    if kind == "check":
        if last.kind == "check":                       # collapse repeated heartbeats
            last.snapshot_id, last.price, last.created_at = snap.id, snap.price, _now()
            last.delta, last.level_reason = delta, reason
            session.commit()
            return last
        r = Review(company_id=company.id, snapshot_id=snap.id, prev_review_id=last.id, kind="check",
                   level="none", level_reason=reason, view=last.view, view_change="unchanged",
                   one_liner=last.one_liner, state={k: v for k, v in last.state.items() if k != "what_changed"}, changes=[], delta=delta,
                   price=snap.price, language=lang, provider="none", prompt_version=prompts.PROMPT_VERSION)
        session.add(r)
        session.commit()
        return r

    # ---- cache: same thesis inputs => reuse ----
    new_titles = sorted(n["title"] for n in delta.get("new_news") or [])
    nrows = list(session.scalars(select(Note).where(Note.company_id == company.id, Note.kind.in_(("comment", "source", "question")))
                                 .order_by(Note.created_at.desc(), Note.id.desc()).limit(5)))
    active = (baseline_provider or provider) if kind in ("baseline", "rebaseline") else provider
    ihash = _hash({"pv": prompts.PROMPT_VERSION, "model": active.model, "lang": lang, "kind": kind,
                   "anchor": anchor.id if anchor else None, "fp": snap.fingerprint, "news": new_titles, "notes": [n.id for n in nrows]})
    cached = session.scalar(select(Review).where(Review.input_hash == ihash, Review.company_id == company.id))
    if cached:
        return cached

    compact = signals.compact_evidence(evidence)
    notes = [{"type": n.kind, "about": n.assumption_id, "text": n.body[:400]} for n in nrows] or None
    try:
        if kind in ("baseline", "rebaseline"):
            res = active.run(system=prompts.BASELINE_SYSTEM, schema=BaselineOutput,
                               payload=prompts.baseline_payload(compact, lang, anchor.state if anchor else None, notes),
                               max_tokens=BASELINE_MAX_TOKENS)
            o = res.data
            state = {"profile": o["profile"], "assumptions": o["assumptions"], "monitor": o["monitor"],
                     "valuation": {"implication": o["valuation_implication"], "consensus_gap": o["consensus_gap"]}}
            r = Review(kind=kind, view=o["view"], view_change=_view_change(anchor.view if anchor else None, o["view"]),
                       one_liner=o["one_liner"], state=state, narrative=o["report_markdown"], changes=[])
        else:
            prior = {"view": anchor.view, "one_liner": anchor.one_liner, "state": anchor.state}
            res = provider.run(system=prompts.UPDATE_SYSTEM, schema=UpdateOutput,
                               payload=prompts.update_payload(prior, delta, level, lang, delta.get("price_pct"), notes),
                               max_tokens=UPDATE_MAX_TOKENS)
            o = res.data
            state = apply_update(anchor.state, o)
            state["what_changed"] = o.get("what_changed") or []
            vc = _view_change(anchor.view, o["view"])           # derived, never trusted from the model
            r = Review(kind="update", view=o["view"], view_change=vc, one_liner=o["one_liner"], state=state,
                       narrative=o["narrative"], changes=o["changes"])
            if o.get("rebaseline_recommended"):
                state["rebaseline"] = o.get("rebaseline_reason") or True
    except AIProviderError as exc:
        log.error("AI call failed for %s (%s): %s usage=%s", ticker, exc.code, exc.message, exc.usage)
        session.rollback()
        raise ServiceError(exc.code, exc.message, 502)

    r.company_id, r.snapshot_id, r.prev_review_id = company.id, snap.id, anchor.id if anchor else None
    r.level, r.level_reason, r.delta, r.price, r.language = level, reason, delta, snap.price, lang
    r.provider, r.model, r.prompt_version, r.input_hash, r.usage = (
        active.name, getattr(res, "model", "") or active.model, prompts.PROMPT_VERSION, ihash, res.usage)
    session.add(r)
    session.commit()
    return r
