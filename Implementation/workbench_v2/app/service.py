"""Orchestration: refresh evidence -> detect change -> (maybe) call the model -> store a Review.

Cost control: no thesis-relevant change => zero LLM calls. Minor/material => ONE small call that
sees the prior structured thesis plus the delta only. The static profile is generated once.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai import prompts
from .ai.provider import AIProviderError, BaseProvider
from .ai.schemas import BaselineOutput, UpdateOutput
from .core import signals
from .models import Company, Review, Snapshot

VIEW_ORDER = {"cautious": 0, "neutral": 1, "constructive": 2}
BASELINE_MAX_TOKENS, UPDATE_MAX_TOKENS = 7000, 2500


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
    return s


def _hash(parts: dict) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def refresh(session: Session, ticker: str, *, adapter, provider: BaseProvider,
            language: str | None = None, force_rebaseline: bool = False) -> Review:
    try:
        evidence, _meta = adapter.get_equity_research_snapshot(ticker.strip().upper())
    except Exception as exc:   # OpenBBAdapterError and anything the provider throws
        raise ServiceError(getattr(exc, "code", "evidence_error"), str(getattr(exc, "message", exc))[:300], 502)

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
                   one_liner=last.one_liner, state=last.state, changes=[], delta=delta,
                   price=snap.price, language=lang, provider="none", prompt_version=prompts.PROMPT_VERSION)
        session.add(r)
        session.commit()
        return r

    # ---- cache: same thesis inputs => reuse ----
    new_titles = sorted(n["title"] for n in delta.get("new_news") or [])
    ihash = _hash({"pv": prompts.PROMPT_VERSION, "model": provider.model, "lang": lang, "kind": kind,
                   "anchor": anchor.id if anchor else None, "fp": snap.fingerprint, "news": new_titles})
    cached = session.scalar(select(Review).where(Review.input_hash == ihash, Review.company_id == company.id))
    if cached:
        return cached

    compact = signals.compact_evidence(evidence)
    try:
        if kind in ("baseline", "rebaseline"):
            res = provider.run(system=prompts.BASELINE_SYSTEM, schema=BaselineOutput,
                               payload=prompts.baseline_payload(compact, lang, anchor.state if anchor else None),
                               max_tokens=BASELINE_MAX_TOKENS)
            o = res.data
            state = {"profile": o["profile"], "assumptions": o["assumptions"], "monitor": o["monitor"]}
            r = Review(kind=kind, view=o["view"], view_change=_view_change(anchor.view if anchor else None, o["view"]),
                       one_liner=o["one_liner"], state=state, narrative=o["report_markdown"], changes=[])
        else:
            prior = {"view": anchor.view, "one_liner": anchor.one_liner, "state": anchor.state}
            res = provider.run(system=prompts.UPDATE_SYSTEM, schema=UpdateOutput,
                               payload=prompts.update_payload(prior, delta, level, lang, delta.get("price_pct")),
                               max_tokens=UPDATE_MAX_TOKENS)
            o = res.data
            state = apply_update(anchor.state, o)
            vc = _view_change(anchor.view, o["view"])           # derived, never trusted from the model
            r = Review(kind="update", view=o["view"], view_change=vc, one_liner=o["one_liner"], state=state,
                       narrative=o["narrative"], changes=o["changes"])
            if o.get("rebaseline_recommended"):
                state["rebaseline"] = o.get("rebaseline_reason") or True
    except AIProviderError as exc:
        session.rollback()
        raise ServiceError(exc.code, exc.message, 502)

    r.company_id, r.snapshot_id, r.prev_review_id = company.id, snap.id, anchor.id if anchor else None
    r.level, r.level_reason, r.delta, r.price, r.language = level, reason, delta, snap.price, lang
    r.provider, r.model, r.prompt_version, r.input_hash, r.usage = (
        provider.name, provider.model, prompts.PROMPT_VERSION, ihash, res.usage)
    session.add(r)
    session.commit()
    return r
