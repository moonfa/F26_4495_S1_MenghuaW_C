from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, service
from ..adapters.openbb_adapter import OpenBBAdapter
from ..ai.provider import AIProviderError, BaseProvider, build_provider
from ..core import signals
from ..database import get_session
from ..models import Company, Note, Review, Snapshot

router = APIRouter(prefix="/api/v1")

# metrics shown as trend lines on the Fundamentals page
SERIES = ["financial_health.revenue_growth", "financial_health.gross_margin",
          "financial_health.operating_margin", "financial_health.return_on_invested_capital",
          "financial_health.debt_to_equity", "valuation.forward_pe", "valuation.pe_ttm",
          "valuation.free_cash_flow_yield"]


def get_adapter() -> OpenBBAdapter:
    return OpenBBAdapter(provider=config.OPENBB_PROVIDER)


def get_provider() -> BaseProvider:
    try:
        return build_provider()
    except AIProviderError as e:
        raise HTTPException(502, e.message)


def _company(session: Session, ticker: str) -> Company:
    c = session.scalar(select(Company).where(Company.ticker == ticker.strip().upper()))
    if not c:
        raise HTTPException(404, "Company not found. Run refresh first.")
    return c


def _reviews(session: Session, company_id: int) -> list[Review]:
    return list(session.scalars(select(Review).where(Review.company_id == company_id)
                                .order_by(Review.created_at, Review.id)))


def _a_changes(prev: Review | None, cur: Review) -> list[dict]:
    old = {a["id"]: a["status"] for a in (prev.state["assumptions"] if prev else [])}
    return [{"id": a["id"], "statement": a["statement"], "from": old.get(a["id"]), "to": a["status"]}
            for a in cur.state["assumptions"] if old.get(a["id"]) != a["status"]]


def _card(r: Review) -> dict:
    return {"id": r.id, "created_at": r.created_at, "kind": r.kind, "level": r.level,
            "view": r.view, "view_change": r.view_change, "one_liner": r.one_liner, "price": r.price}


# ---------------------------------------------------------------- companies
@router.get("/companies")
def companies(session: Session = Depends(get_session)):
    out = []
    for c in session.scalars(select(Company).order_by(Company.ticker)):
        r = service.latest_review(session, c.id)
        out.append({"ticker": c.ticker, "name": c.name, "language": c.language,
                    "view": r.view if r else None, "view_change": r.view_change if r else None,
                    "checked_at": r.created_at if r else None})
    return out


class RefreshRequest(BaseModel):
    language: Literal["en", "zh-CN"] | None = None
    force_rebaseline: bool = False


@router.post("/companies/{ticker}/refresh", status_code=201)
def refresh(ticker: str, payload: RefreshRequest, session: Session = Depends(get_session),
            adapter=Depends(get_adapter), provider: BaseProvider = Depends(get_provider)):
    """Single entry point. The system decides: baseline, LLM update, or free no-change check."""
    try:
        r = service.refresh(session, ticker, adapter=adapter, provider=provider,
                            language=payload.language, force_rebaseline=payload.force_rebaseline)
    except service.ServiceError as e:
        raise HTTPException(e.http, {"code": e.code, "message": e.message})
    return {**_card(r), "level_reason": r.level_reason, "llm_called": r.kind != "check"}


# ---------------------------------------------------------------- page 1: brief
@router.get("/companies/{ticker}/brief")
def brief(ticker: str, session: Session = Depends(get_session)):
    c = _company(session, ticker)
    latest = service.latest_review(session, c.id)
    if not latest:
        raise HTTPException(404, "No review yet.")
    anchor = service.latest_review(session, c.id, analysed_only=True)
    prior = session.get(Review, anchor.prev_review_id) if anchor and anchor.prev_review_id else None
    old = {a["id"]: a["status"] for a in (prior.state["assumptions"] if prior else [])}
    assumptions = [{**a, "prev_status": old.get(a["id"])} for a in anchor.state["assumptions"]]
    health: dict[str, int] = {}
    for a in assumptions:
        health[a["status"]] = health.get(a["status"], 0) + 1
    anchor_snap = session.get(Snapshot, anchor.snapshot_id)
    last_snap = session.get(Snapshot, latest.snapshot_id)
    p0, p1 = anchor_snap.price, last_snap.price
    return {
        "ticker": c.ticker, "name": c.name, "language": c.language,
        "view": anchor.view, "view_change": anchor.view_change, "one_liner": anchor.one_liner,
        "analysed_at": anchor.created_at, "checked_at": latest.created_at,
        "last_check_level": latest.level, "last_check_reason": latest.level_reason,
        "price": p1, "price_since_analysis_pct": round((p1 - p0) / p0, 4) if p0 and p1 else None,
        "health": health, "assumptions": assumptions,
        "top_changes": anchor.changes or [], "monitor": anchor.state["monitor"],
        "rebaseline_suggested": bool(anchor.state.get("rebaseline")),
        "meta": {"review_id": anchor.id, "kind": anchor.kind, "model": anchor.model,
                 "prompt_version": anchor.prompt_version, "usage": anchor.usage},
    }


# ---------------------------------------------------------------- page 2: thesis
@router.get("/companies/{ticker}/thesis")
def thesis(ticker: str, session: Session = Depends(get_session)):
    c = _company(session, ticker)
    revs = [r for r in _reviews(session, c.id) if r.kind != "check"]
    if not revs:
        raise HTTPException(404, "No review yet.")
    cur = revs[-1]
    history: dict[str, list] = {}
    for r in revs:
        for a in r.state["assumptions"]:
            history.setdefault(a["id"], []).append({"review_id": r.id, "at": r.created_at, "status": a["status"]})
    return {"profile": cur.state["profile"], "assumptions": [{**a, "history": history[a["id"]]}
            for a in cur.state["assumptions"]], "monitor": cur.state["monitor"],
            "report_markdown": next((r.narrative for r in reversed(revs) if r.kind in ("baseline", "rebaseline")), "")}


# ---------------------------------------------------------------- page 3: fundamentals
@router.get("/companies/{ticker}/fundamentals")
def fundamentals(ticker: str, session: Session = Depends(get_session)):
    c = _company(session, ticker)
    snaps = list(session.scalars(select(Snapshot).where(Snapshot.company_id == c.id)
                                 .order_by(Snapshot.retrieved_at, Snapshot.id)))
    series: dict[str, list] = {k: [] for k in SERIES}
    for s in snaps:
        for k in SERIES:
            sec, f = k.split(".")
            v = (s.payload.get(sec) or {}).get(f)
            if isinstance(v, (int, float)):
                series[k].append({"t": s.retrieved_at, "v": v})
    # percentile of the latest multiple within OUR OWN history (needs several snapshots)
    pct = {}
    for k in ("valuation.forward_pe", "valuation.pe_ttm"):
        vals = [p["v"] for p in series[k]]
        if len(vals) >= 5:
            pct[k] = round(sum(v <= vals[-1] for v in vals) / len(vals), 3)
    latest = snaps[-1].payload if snaps else {}
    return {"series": series, "own_history_percentile": pct, "n_snapshots": len(snaps),
            "price_series": [{"t": s.retrieved_at, "v": s.price} for s in snaps if s.price],
            "latest": {k: latest.get(k) for k in ("market", "valuation", "financial_health", "analyst_consensus")}}


# ---------------------------------------------------------------- page 4: timeline
@router.get("/companies/{ticker}/timeline")
def timeline(ticker: str, session: Session = Depends(get_session)):
    c = _company(session, ticker)
    out, prev_analysed = [], None
    for r in _reviews(session, c.id):
        d = r.delta or {}
        out.append({**_card(r), "level_reason": r.level_reason,
                    "changes": r.changes or [], "assumption_changes": _a_changes(prev_analysed, r) if r.kind != "check" else [],
                    "delta_summary": {"price_pct": d.get("price_pct"), "n_fundamental": len(d.get("fundamental_changes") or []),
                                      "n_news": len(d.get("new_news") or [])}})
        if r.kind != "check":
            prev_analysed = r
    return out


@router.get("/reviews/{review_id}")
def review_detail(review_id: int, session: Session = Depends(get_session)):
    r = session.get(Review, review_id)
    if not r:
        raise HTTPException(404, "Review not found")
    return {**_card(r), "level_reason": r.level_reason, "state": r.state, "narrative": r.narrative,
            "changes": r.changes, "delta": r.delta, "meta": {"model": r.model, "provider": r.provider,
            "prompt_version": r.prompt_version, "usage": r.usage, "snapshot_id": r.snapshot_id}}


@router.get("/companies/{ticker}/compare")
def compare(ticker: str, a: int, b: int, session: Session = Depends(get_session)):
    c = _company(session, ticker)
    ra, rb = session.get(Review, a), session.get(Review, b)
    if not ra or not rb or ra.company_id != c.id or rb.company_id != c.id:
        raise HTTPException(404, "Review not found for this company")
    if ra.created_at > rb.created_at:
        ra, rb = rb, ra
    ea, eb = session.get(Snapshot, ra.snapshot_id).payload, session.get(Snapshot, rb.snapshot_id).payload
    return {"from": _card(ra), "to": _card(rb), "assumption_changes": _a_changes(ra, rb),
            "metrics": signals.compute_delta(eb, ea)}


# ---------------------------------------------------------------- notes
class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=20000)
    kind: Literal["hypothesis", "valuation_assumption", "planned_action", "review_outcome", "general"] = "general"
    review_id: int | None = None


@router.get("/companies/{ticker}/notes")
def notes(ticker: str, session: Session = Depends(get_session)):
    c = _company(session, ticker)
    return [{"id": n.id, "kind": n.kind, "body": n.body, "review_id": n.review_id, "created_at": n.created_at}
            for n in session.scalars(select(Note).where(Note.company_id == c.id).order_by(Note.created_at.desc()))]


@router.post("/companies/{ticker}/notes", status_code=201)
def add_note(ticker: str, payload: NoteIn, session: Session = Depends(get_session)):
    c = _company(session, ticker)
    n = Note(company_id=c.id, **payload.model_dump())
    session.add(n)
    session.commit()
    return {"id": n.id}
