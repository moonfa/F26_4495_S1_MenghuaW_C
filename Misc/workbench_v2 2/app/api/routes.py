from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config, portfolio, security, service
from ..adapters.openbb_adapter import OpenBBAdapter
from ..ai.provider import AIProviderError, BaseProvider, build_baseline_provider, build_provider
from ..ai import prompts
from ..ai.schemas import TranslationOutput
from ..core import plan as plan_core, signals, thesis as thesis_core, translate as zh_core
from ..database import get_session
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..core import statements as statements_core
from ..models import AssumptionDriver, Company, Holding, Note, Plan, Review, Snapshot, Trade, TradeReason

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


def get_baseline_provider():
    try:
        return build_baseline_provider()
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


def _quote(p: dict, ticker: str) -> dict:
    co, m, an = p.get("company") or {}, p.get("market") or {}, p.get("analyst_consensus") or {}
    px, prev, tgt = m.get("current_price"), m.get("previous_close"), an.get("target_consensus")
    ratio = lambda a, b: round(a / b - 1, 4) if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b else None
    return {"sector": co.get("sector"), "industry": co.get("industry"), "price": px,
            "currency": m.get("currency") or co.get("currency"), "day_change_pct": ratio(px, prev),
            "year_high": m.get("year_high"), "year_low": m.get("year_low"), "market_cap": m.get("market_cap"),
            "target": tgt, "target_upside_pct": ratio(tgt, px),
            "yahoo_url": f"https://finance.yahoo.com/quote/{ticker}"}


def _pdict(p: Plan | None) -> dict | None:
    return None if not p else {"style": p.style, "buy_below": p.buy_below, "target_price": p.target_price,
                               "stop_price": p.stop_price, "rules": p.rules, "target_amount": p.target_amount,
                               "max_amount": p.max_amount, "strategy": p.strategy or "", "rationale": p.rationale or "",
                               "rationale_at": p.rationale_at}


def _pstat(p: Plan | None, price, hold: Holding | None = None):
    """Plan status. Position value is quantity x price in the stock's own currency."""
    if not p:
        return None
    value = (hold.quantity * price) if (hold and hold.quantity and price) else 0.0
    return plan_core.plan_status(price, p.buy_below, p.target_price, p.stop_price, value=value,
                                 target_amount=p.target_amount, max_amount=p.max_amount, weight=hold.weight if hold else None)


def _snap_price(session: Session, company_id: int):
    s = session.scalar(select(Snapshot).where(Snapshot.company_id == company_id).order_by(Snapshot.retrieved_at.desc(), Snapshot.id.desc()))
    return s.price if s else None


def _loc(r: Review, lang: str) -> dict:
    """The review's text fields, in Chinese when lang == "zh" and a stored translation exists."""
    base = {"one_liner": r.one_liner, "narrative": r.narrative, "changes": r.changes or [], "state": r.state}
    return zh_core.localize(base, (r.zh or {}).get("items")) if lang == "zh" and r.zh else base


class _S:                                   # lets _a_changes read a localized state
    def __init__(self, state):
        self.state = state


def _card(r: Review) -> dict:
    return {"id": r.id, "created_at": r.created_at, "kind": r.kind, "level": r.level,
            "view": r.view, "view_change": r.view_change, "one_liner": r.one_liner, "price": r.price}


# ---------------------------------------------------------------- companies
def _att(s):
    """Focus level of a company: focus | normal | archived. Old values (holding, watching, idea) count as normal."""
    return s if s in ("focus", "archived") else "normal"


@router.get("/companies")
def companies(session: Session = Depends(get_session)):
    out = []
    plans = {p.symbol: p for p in session.scalars(select(Plan))}
    broker = {h.symbol: h.name for h in session.scalars(select(Holding)) if h.name}     # the name you see in your broker app
    held = {h.symbol: h for h in session.scalars(select(Holding))}
    for c in session.scalars(select(Company).order_by(Company.ticker)):
        last = service.latest_review(session, c.id)
        anchor = service.latest_review(session, c.id, analysed_only=True)
        snap = session.get(Snapshot, last.snapshot_id) if last else None
        q = _quote(snap.payload, c.ticker) if snap else {}
        out.append({"ticker": c.ticker, "name": c.name, "alias": broker.get(c.ticker), "status": _att(c.status),
                    "held": c.ticker in held and (held[c.ticker].quantity or 0) > 0,
                    "view": anchor.view if anchor else None, "view_change": anchor.view_change if anchor else None,
                    "price": q.get("price"), "currency": q.get("currency"), "target_upside_pct": q.get("target_upside_pct"),
                    "analysed_at": anchor.created_at if anchor else None, "checked_at": last.created_at if last else None,
                    "sector": q.get("sector"), "pnl_pct": held[c.ticker].pnl_pct if c.ticker in held else None,
                    "weight": held[c.ticker].weight if c.ticker in held else None, "plan_status": _pstat(plans.get(c.ticker), q.get("price"), held.get(c.ticker))})
    return out


class StatusIn(BaseModel):
    status: Literal["focus", "normal", "archived", "holding", "watching", "idea"]   # last three: old clients, stored as normal


@router.patch("/companies/{ticker}")
def set_status(ticker: str, payload: StatusIn, session: Session = Depends(get_session)):
    c = _company(session, ticker)
    c.status = _att(payload.status)
    session.commit()
    return {"ticker": c.ticker, "status": c.status}


@router.delete("/companies/{ticker}")
def delete_company(ticker: str, session: Session = Depends(get_session)):
    """Permanent. Prefer archiving; delete is for mistakes."""
    c = _company(session, ticker)
    session.query(Note).filter(Note.company_id == c.id).delete()
    session.query(AssumptionDriver).filter(AssumptionDriver.company_id == c.id).delete()
    session.query(Review).filter(Review.company_id == c.id).update({Review.prev_review_id: None})
    session.query(Review).filter(Review.company_id == c.id).delete()
    session.query(Snapshot).filter(Snapshot.company_id == c.id).delete()
    session.delete(c)
    session.commit()
    return {"deleted": c.ticker}


class RefreshRequest(BaseModel):
    language: Literal["en", "zh-CN"] | None = None
    force_rebaseline: bool = False


@router.post("/companies/{ticker}/refresh", status_code=201)
def refresh(ticker: str, payload: RefreshRequest, session: Session = Depends(get_session),
            adapter=Depends(get_adapter), provider: BaseProvider = Depends(get_provider),
            baseline_provider=Depends(get_baseline_provider)):
    """Single entry point. The system decides: baseline, LLM update, or free no-change check."""
    try:
        r = service.refresh(session, ticker, adapter=adapter, provider=provider,
                            language=payload.language, force_rebaseline=payload.force_rebaseline,
                            baseline_provider=baseline_provider)
    except service.ServiceError as e:
        raise HTTPException(e.http, {"code": e.code, "message": e.message})
    return {**_card(r), "level_reason": r.level_reason, "llm_called": r.kind != "check"}


# ---------------------------------------------------------------- page 1: brief
@router.get("/companies/{ticker}/brief")
def brief(ticker: str, lang: str = "en", session: Session = Depends(get_session)):
    c = _company(session, ticker)
    latest = service.latest_review(session, c.id)
    if not latest:
        raise HTTPException(404, "No review yet.")
    anchor = service.latest_review(session, c.id, analysed_only=True)
    L = _loc(anchor, lang)
    prior = session.get(Review, anchor.prev_review_id) if anchor and anchor.prev_review_id else None
    old = {a["id"]: a["status"] for a in (prior.state["assumptions"] if prior else [])}
    assumptions = [{**a, "prev_status": old.get(a["id"])} for a in L["state"]["assumptions"]]
    health: dict[str, int] = {}
    for a in assumptions:
        health[a["status"]] = health.get(a["status"], 0) + 1
    anchor_snap = session.get(Snapshot, anchor.snapshot_id)
    last_snap = session.get(Snapshot, latest.snapshot_id)
    p0, p1 = anchor_snap.price, last_snap.price
    seen = set(signals.news_titles(anchor_snap.payload))
    news = [{"title": n.get("title"), "date": n.get("date"), "source": n.get("source"), "url": n.get("url"),
             "is_new": str(n.get("title")).strip() not in seen}
            for n in (last_snap.payload.get("recent_news") or [])[:6] if isinstance(n, dict) and n.get("title")]
    due = [{"id": n.id, "kind": n.kind, "body": n.body[:200], "revisit_on": n.revisit_on}
           for n in session.scalars(select(Note).where(Note.company_id == c.id, Note.done.is_(False), Note.revisit_on.is_not(None),
                                    Note.revisit_on <= date.today().isoformat()).order_by(Note.revisit_on))]
    for t, r in session.execute(select(Trade, TradeReason).join(TradeReason, TradeReason.trade_id == Trade.id).where(
            Trade.symbol == c.ticker, TradeReason.revisit_on.is_not(None), TradeReason.revisit_on <= date.today().isoformat(),
            TradeReason.reviewed_at.is_(None))):
        due.append({"id": None, "kind": "trade_review", "revisit_on": r.revisit_on,
                    "body": f"Review your {t.side} of {t.quantity:g} at {t.price:g} ({t.executed_at[:10]}): did it play out as expected?"})
    hold = session.scalar(select(Holding).where(Holding.symbol == c.ticker))
    pl = session.scalar(select(Plan).where(Plan.symbol == c.ticker))
    position = {"quantity": hold.quantity, "cost": hold.cost, "pnl_pct": hold.pnl_pct, "weight": hold.weight,
                "currency": hold.currency, "kind": hold.kind} if hold else None
    return {
        "position": position, "plan": _pdict(pl), "plan_status": _pstat(pl, p1 if p1 is not None else (hold.price if hold else None), hold),
        "news": news, "due_notes": due, "health": thesis_core.health(anchor.state["assumptions"])[0],
        "health_reason": thesis_core.health(anchor.state["assumptions"])[1], "status": _att(c.status),
        "data_notes": {"missing": (last_snap.payload.get("data_quality") or {}).get("sections_missing"),
                       "warnings": (last_snap.payload.get("data_quality") or {}).get("warnings"),
                       "gaps": [g for g in signals.data_gaps(last_snap.payload) if "news" not in g.lower()]},
        "ticker": c.ticker, "name": c.name, "language": c.language,
        "view": anchor.view, "view_change": anchor.view_change, "one_liner": L["one_liner"], "zh_available": bool(anchor.zh),
        "analysed_at": anchor.created_at, "checked_at": latest.created_at,
        "last_check_level": latest.level, "last_check_reason": latest.level_reason,
        "quote": _quote(last_snap.payload, c.ticker), "as_of": last_snap.retrieved_at,
        "price": p1, "price_since_analysis_pct": round((p1 - p0) / p0, 4) if p0 and p1 else None,
        "health_counts": health, "assumptions": assumptions, "valuation": L["state"].get("valuation"),
        "top_changes": L["changes"], "monitor": L["state"]["monitor"],
        "rebaseline_suggested": bool(anchor.state.get("rebaseline")),
        "meta": {"review_id": anchor.id, "kind": anchor.kind, "model": anchor.model,
                 "prompt_version": anchor.prompt_version, "usage": anchor.usage},
    }


# ---------------------------------------------------------------- page 2: thesis
@router.get("/companies/{ticker}/thesis")
def thesis(ticker: str, lang: str = "en", session: Session = Depends(get_session)):
    c = _company(session, ticker)
    revs = [r for r in _reviews(session, c.id) if r.kind != "check"]
    if not revs:
        raise HTTPException(404, "No review yet.")
    cur = revs[-1]
    L = _loc(cur, lang)
    history: dict[str, list] = {}
    for r in revs:
        for a in r.state["assumptions"]:
            history.setdefault(a["id"], []).append({"review_id": r.id, "at": r.created_at, "status": a["status"]})
    by_a: dict[str, list] = {}
    for n in session.scalars(select(Note).where(Note.company_id == c.id, Note.assumption_id.is_not(None)).order_by(Note.created_at.desc())):
        by_a.setdefault(n.assumption_id, []).append({"id": n.id, "body": n.body, "created_at": n.created_at})
    src = next((r for r in reversed(revs) if r.kind in ("baseline", "rebaseline")), None)
    return {"profile": L["state"]["profile"], "assumptions": [{**a, "history": history[a["id"]], "notes": by_a.get(a["id"], [])}
            for a in L["state"]["assumptions"]], "monitor": L["state"]["monitor"], "zh_available": bool(cur.zh), "review_id": cur.id,
            "report_markdown": _loc(src, lang)["narrative"] if src else "", "report_review_id": src.id if src else None,
            "report_zh": bool(src.zh) if src else False}


# ---------------------------------------------------------------- page 3: fundamentals
@router.get("/companies/{ticker}/fundamentals")
def fundamentals(ticker: str, session: Session = Depends(get_session)):
    """Latest snapshot grouped for display, plus the values at the last analysis for 'was X' hints."""
    c = _company(session, ticker)
    latest = session.scalar(select(Snapshot).where(Snapshot.company_id == c.id)
                            .order_by(Snapshot.retrieved_at.desc(), Snapshot.id.desc()))
    if not latest:
        raise HTTPException(404, "No snapshot yet.")
    anchor = service.latest_review(session, c.id, analysed_only=True)
    base = session.get(Snapshot, anchor.snapshot_id) if anchor else None
    keys = ("market", "valuation", "financial_health", "analyst_consensus")
    pick = lambda snap: {k: snap.payload.get(k) for k in keys} if snap else None
    return {"as_of": latest.retrieved_at, "analysed_at": base.retrieved_at if base else None, "currency": _quote(latest.payload, c.ticker)["currency"],
            "now": pick(latest), "at_analysis": pick(base), "derived": signals.derived_metrics(latest.payload),
            "statements": statements_core.view(latest.payload.get("statements")) if latest.payload.get("statements") else None}


# ---------------------------------------------------------------- page 4: timeline
@router.get("/companies/{ticker}/timeline")
def timeline(ticker: str, lang: str = "en", session: Session = Depends(get_session)):
    c = _company(session, ticker)
    out, prev_loc = [], None
    for r in _reviews(session, c.id):
        d, L = r.delta or {}, _loc(r, lang)
        out.append({**_card(r), "one_liner": L["one_liner"], "level_reason": r.level_reason, "zh_available": bool(r.zh),
                    "changes": L["changes"], "what_changed": (r.state or {}).get("what_changed") if r.kind == "update" else None,
                    "assumption_changes": _a_changes(_S(prev_loc["state"]) if prev_loc else None, _S(L["state"])) if r.kind != "check" else [],
                    "delta_summary": {"price_pct": d.get("price_pct"), "n_fundamental": len(d.get("fundamental_changes") or []),
                                      "n_news": len(d.get("new_news") or [])}})
        if r.kind != "check":
            prev_loc = L
    return out


@router.get("/reviews/{review_id}")
def review_detail(review_id: int, lang: str = "en", session: Session = Depends(get_session)):
    r = session.get(Review, review_id)
    if not r:
        raise HTTPException(404, "Review not found")
    L = _loc(r, lang)
    return {**_card(r), "one_liner": L["one_liner"], "level_reason": r.level_reason, "state": L["state"], "narrative": L["narrative"],
            "changes": L["changes"], "zh_available": bool(r.zh), "delta": r.delta, "meta": {"model": r.model, "provider": r.provider,
            "prompt_version": r.prompt_version, "usage": r.usage, "snapshot_id": r.snapshot_id}}


@router.post("/reviews/{review_id}/translate")
def translate_review(review_id: int, session: Session = Depends(get_session), provider: BaseProvider = Depends(get_provider)):
    """Manual, once per review: one model call over the free-text fields only. Stored; later views cost nothing."""
    r = session.get(Review, review_id)
    if not r:
        raise HTTPException(404, "Review not found")
    if r.zh:
        return {"ok": True, "cached": True}
    src = zh_core.flatten({"one_liner": r.one_liner, "narrative": r.narrative, "changes": r.changes or [], "state": r.state})
    try:
        res = provider.run(system=prompts.TRANSLATE_SYSTEM, schema=TranslationOutput, payload=prompts.translate_payload(src), max_tokens=12000)
    except AIProviderError as e:
        raise HTTPException(502, {"code": e.code, "message": e.message})
    got = {i["k"]: i["t"] for i in res.data.get("items", []) if i.get("k") in src and str(i.get("t", "")).strip()}
    if len(got) < max(1, int(len(src) * 0.6)):
        raise HTTPException(502, {"code": "translation_incomplete", "message": f"The model returned {len(got)} of {len(src)} text items. Nothing was saved; try again."})
    r.zh = {"items": got, "model": getattr(res, "model", "") or provider.model, "usage": res.usage, "missing": len(src) - len(got)}
    session.commit()
    return {"ok": True, "cached": False, "translated": len(got), "of": len(src)}


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
    kind: Literal["decision", "comment", "source", "question"] = "comment"
    assumption_id: str | None = Field(default=None, pattern=r"^a\d+$")
    revisit_on: date | None = None


def _latest_price(session: Session, company_id: int):
    s = session.scalar(select(Snapshot).where(Snapshot.company_id == company_id).order_by(Snapshot.retrieved_at.desc(), Snapshot.id.desc()))
    return s.price if s else None


@router.get("/companies/{ticker}/notes")
def notes(ticker: str, session: Session = Depends(get_session)):
    c = _company(session, ticker)
    items = [{"id": n.id, "kind": n.kind, "body": n.body, "assumption_id": n.assumption_id, "price": n.price,
              "revisit_on": n.revisit_on, "done": n.done, "created_at": n.created_at}
             for n in session.scalars(select(Note).where(Note.company_id == c.id).order_by(Note.created_at.desc(), Note.id.desc()))]
    return {"price_now": _latest_price(session, c.id), "items": items}


@router.post("/companies/{ticker}/notes", status_code=201)
def add_note(ticker: str, payload: NoteIn, session: Session = Depends(get_session)):
    c = _company(session, ticker)
    n = Note(company_id=c.id, kind=payload.kind, body=payload.body.strip(), assumption_id=payload.assumption_id,
             revisit_on=payload.revisit_on.isoformat() if payload.revisit_on else None, price=_latest_price(session, c.id))
    session.add(n)
    session.commit()
    return {"id": n.id}


@router.post("/notes/{note_id}/done")
def note_done(note_id: int, session: Session = Depends(get_session)):
    n = session.get(Note, note_id)
    if not n:
        raise HTTPException(404, "Note not found")
    n.done = True
    session.commit()
    return {"ok": True}


@router.delete("/notes/{note_id}")
def note_delete(note_id: int, session: Session = Depends(get_session)):
    n = session.get(Note, note_id)
    if n:
        session.delete(n)
        session.commit()
    return {"ok": True}


# ---------------------------------------------------------------- portfolio (broker CSV import)
async def _read_csv(file: UploadFile, parser):
    raw = await file.read(security.MAX_UPLOAD + 1)
    if len(raw) > security.MAX_UPLOAD:
        raise HTTPException(413, "File is too large for a broker export (limit 5 MB).")
    try:
        items = parser(portfolio.decode(raw))
    except ValueError as e:
        raise HTTPException(400, f"{e}. Is this the right export?")
    return items


@router.post("/portfolio/import/holdings")
async def import_holdings(file: UploadFile = File(...), session: Session = Depends(get_session)):
    items = await _read_csv(file, portfolio.parse_holdings)
    if not items:
        raise HTTPException(400, "No holdings found in this file.")
    old = {h.symbol: h.kind for h in session.scalars(select(Holding))}      # keep manual type overrides
    # A re-import replaces only the currencies present in the file, so a SGD file never wipes USD/HKD rows.
    session.query(Holding).filter(Holding.currency.in_({i["currency"] for i in items})).delete(synchronize_session=False)
    for it in items:
        session.add(Holding(**{**it, "kind": old.get(it["symbol"], it["kind"])}))
    session.commit()
    return {"imported": len(items)}


@router.post("/portfolio/import/trades")
async def import_trades(file: UploadFile = File(...), session: Session = Depends(get_session)):
    items, report = await _read_csv(file, portfolio.parse_trades_report)
    have = set(session.scalars(select(Trade.key)))
    new = {i["key"]: i for i in items if i["key"] not in have}
    session.add_all(Trade(**i) for i in new.values())
    session.commit()
    return {"added": len(new), "skipped": len(items) - len(new), "report": report}


@router.get("/portfolio")
def get_portfolio(session: Session = Depends(get_session)):
    hs = list(session.scalars(select(Holding).order_by(Holding.weight.desc())))
    cos = {c.ticker: c for c in session.scalars(select(Company))}
    plans = {p.symbol: p for p in session.scalars(select(Plan))}
    items, caut, unan = [], 0.0, 0.0
    for h in hs:
        c = cos.get(h.symbol)
        a = service.latest_review(session, c.id, analysed_only=True) if c else None
        w = h.weight or 0.0
        snap = session.scalar(select(Snapshot).where(Snapshot.company_id == c.id).order_by(Snapshot.retrieved_at.desc(), Snapshot.id.desc())) if c else None
        px = snap.price if snap else None
        px = px if px is not None else h.price
        sector = ((snap.payload or {}).get("company") or {}).get("sector") if snap else None
        pl = plans.get(h.symbol)
        caut += w if a and a.view == "cautious" else 0.0
        unan += w if (not a and h.kind == "stock") else 0.0
        items.append({"id": h.id, "code": h.code, "symbol": h.symbol, "name": h.name, "kind": h.kind, "currency": h.currency,
                      "quantity": h.quantity, "price": h.price, "pnl_pct": h.pnl_pct, "weight": h.weight,
                      "analysed": bool(a), "view": a.view if a else None, "sector": sector,
                      "plan": _pdict(pl), "plan_status": _pstat(pl, px, h)})
    return {"count": len(hs), "top5": sum(h.weight or 0 for h in hs[:5]), "cautious": caut, "unanalysed": unan,
            "imported_at": hs[0].imported_at if hs else None, "items": items}


class KindIn(BaseModel):
    kind: Literal["stock", "etf", "cash"]


@router.patch("/portfolio/holdings/{holding_id}")
def set_kind(holding_id: int, payload: KindIn, session: Session = Depends(get_session)):
    h = session.get(Holding, holding_id)
    if not h:
        raise HTTPException(404, "Holding not found")
    h.kind = payload.kind
    session.commit()
    return {"ok": True}


@router.get("/usage")
def usage(session: Session = Depends(get_session)):
    """Model calls that produced a stored analysis today (Pacific time, when Google resets daily quotas).
    Rejected or retried calls are not recorded, so the real quota use can be higher."""
    pt = ZoneInfo("America/Los_Angeles")
    start = datetime.now(pt).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    by: dict[str, int] = {}
    for r in session.scalars(select(Review).where(Review.created_at >= start, Review.kind != "check")):
        by[r.model or r.provider] = by.get(r.model or r.provider, 0) + 1
    return {"calls": sum(by.values()), "by_model": by}


# ---------------------------------------------------------------- position plans
STY_OF = {"long_term": "investment", "swing": "trade", "short_term": "trade", "defensive": "defensive", "rebalance": "defensive"}


class PlanIn(BaseModel):
    style: Literal["investment", "trade", "defensive"] = "investment"
    strategy: Literal["", "long_term", "swing", "short_term", "defensive", "rebalance"] = ""
    buy_below: float | None = Field(default=None, gt=0)
    target_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    target_amount: float | None = Field(default=None, gt=0)
    max_amount: float | None = Field(default=None, gt=0)
    rules: str = Field(default="", max_length=2000)
    rationale: str = Field(default="", max_length=4000)


@router.put("/plans/{symbol}")
def put_plan(symbol: str, payload: PlanIn, session: Session = Depends(get_session)):
    sym = symbol.strip().upper()
    if payload.stop_price and payload.target_price and payload.stop_price >= payload.target_price:
        raise HTTPException(400, "Stop must be below the target price.")
    if payload.buy_below and payload.target_price and payload.buy_below >= payload.target_price:
        raise HTTPException(400, "Buy-at-or-below must be below the target price.")
    if payload.target_amount and payload.max_amount and payload.target_amount > payload.max_amount:
        raise HTTPException(400, "Target position cannot be above the maximum position.")
    p = session.scalar(select(Plan).where(Plan.symbol == sym)) or Plan(symbol=sym)
    p.strategy = payload.strategy
    p.style = STY_OF.get(payload.strategy) or payload.style
    p.buy_below, p.target_price, p.stop_price, p.rules = payload.buy_below, payload.target_price, payload.stop_price, payload.rules.strip()
    p.target_amount, p.max_amount = payload.target_amount, payload.max_amount
    new = payload.rationale.strip()
    if new != (p.rationale or ""):
        p.rationale_at = datetime.now(timezone.utc) if new else None
    p.rationale = new
    p.updated_at = datetime.now(timezone.utc)
    session.add(p)
    session.commit()
    return {"ok": True}


@router.delete("/plans/{symbol}")
def delete_plan(symbol: str, session: Session = Depends(get_session)):
    session.query(Plan).filter(Plan.symbol == symbol.strip().upper()).delete()
    session.commit()
    return {"ok": True}


def _reason(r: TradeReason | None):
    return None if not r else {"strategy": r.strategy, "fundamental": r.fundamental, "technical": r.technical,
                               "revisit_on": r.revisit_on, "review": r.review, "reviewed": bool(r.reviewed_at),
                               "decided_on": r.decided_on, "outcome": r.outcome or "", "followup": r.followup or "",
                               "action": r.action or "", "from_plan": bool(r.from_plan)}


def _trade(t: Trade, r: TradeReason | None = None, pl: Plan | None = None) -> dict:
    logic = {"strategy": pl.strategy or "", "rationale": pl.rationale} if pl and (pl.rationale or "").strip() else None
    return {"plan_logic": logic, "id": t.id, "code": t.code, "symbol": t.symbol, "name": t.name, "side": t.side, "quantity": t.quantity,
            "price": t.price, "amount": t.amount, "fee": t.fee, "currency": t.currency, "executed_at": t.executed_at,
            "reason": _reason(r)}


@router.get("/companies/{ticker}/trades")
def company_trades(ticker: str, session: Session = Depends(get_session)):
    c = _company(session, ticker)
    rows = list(session.scalars(select(Trade).where(Trade.symbol == c.ticker).order_by(Trade.executed_at.desc())))
    rs = {r.trade_id: r for r in session.scalars(select(TradeReason).where(TradeReason.trade_id.in_([t.id for t in rows] or [0])))}
    pl = session.scalar(select(Plan).where(Plan.symbol == c.ticker))
    return [_trade(t, rs.get(t.id), pl) for t in rows]


@router.get("/trades/pending")
def pending_trades(limit: int = 30, session: Session = Depends(get_session)):
    """Imported trades with no stated reason yet, newest first."""
    left = Trade.id.not_in(select(TradeReason.trade_id))
    plans = {p.symbol: p for p in session.scalars(select(Plan))}
    return {"all": session.scalar(select(func.count()).select_from(Trade)) or 0,
            "total": session.scalar(select(func.count()).select_from(Trade).where(left)) or 0,
            "items": [_trade(t, None, plans.get(t.symbol)) for t in session.scalars(select(Trade).where(left).order_by(Trade.executed_at.desc()).limit(limit))]}


class ReasonIn(BaseModel):
    strategy: Literal["", "long_term", "swing", "short_term", "defensive", "rebalance"] = ""
    fundamental: str = Field(default="", max_length=3000)
    technical: str = Field(default="", max_length=3000)
    revisit_on: date | None = None
    review: str = Field(default="", max_length=3000)
    decided_on: date | None = None
    outcome: Literal["", "open", "success", "mixed", "failed"] = ""
    followup: str = Field(default="", max_length=2000)
    action: Literal["", "initial", "add", "trim", "exit", "swap"] = ""
    from_plan: bool = False


def _apply(r: TradeReason, p: ReasonIn) -> None:
    r.strategy, r.fundamental, r.technical = p.strategy, p.fundamental.strip(), p.technical.strip()
    r.revisit_on = p.revisit_on.isoformat() if p.revisit_on else None
    r.decided_on = p.decided_on.isoformat() if p.decided_on else None
    r.review, r.followup = p.review.strip(), p.followup.strip()
    r.outcome = p.outcome
    r.action, r.from_plan = p.action, p.from_plan
    r.reviewed_at = datetime.now(timezone.utc) if (r.review or r.outcome in ("success", "mixed", "failed")) else None
    r.updated_at = datetime.now(timezone.utc)


def _has_content(p: ReasonIn) -> bool:
    return bool(p.fundamental.strip() or p.technical.strip() or p.review.strip() or p.outcome)


@router.put("/trades/{trade_id}/reason")
def put_reason(trade_id: int, payload: ReasonIn, session: Session = Depends(get_session)):
    if not session.get(Trade, trade_id):
        raise HTTPException(404, "Trade not found")
    if not _has_content(payload):
        raise HTTPException(400, "Write a reason, a review, or mark an outcome.")
    r = session.scalar(select(TradeReason).where(TradeReason.trade_id == trade_id)) or TradeReason(trade_id=trade_id)
    _apply(r, payload)
    session.add(r)
    session.commit()
    return {"ok": True}


class BulkReasonIn(ReasonIn):
    trade_ids: list[int] = Field(min_length=1, max_length=200)
    keep_dates: bool = True       # decided_on stays each trade's own day when not given


@router.put("/trades/reason/bulk")
def put_reason_bulk(payload: BulkReasonIn, session: Session = Depends(get_session)):
    """One reason for several trades (split fills, same-day trades with one cause). Existing text is replaced."""
    if not _has_content(payload):
        raise HTTPException(400, "Write a reason, a review, or mark an outcome.")
    ids = list(dict.fromkeys(payload.trade_ids))
    trades = {t.id: t for t in session.scalars(select(Trade).where(Trade.id.in_(ids)))}
    if len(trades) != len(ids):
        raise HTTPException(404, "Some trades were not found.")
    have = {r.trade_id: r for r in session.scalars(select(TradeReason).where(TradeReason.trade_id.in_(ids)))}
    for tid in ids:
        r = have.get(tid) or TradeReason(trade_id=tid)
        _apply(r, payload)
        session.add(r)
    session.commit()
    return {"ok": True, "updated": len(ids)}


@router.post("/plans/{symbol}/apply-logic")
def apply_plan_logic(symbol: str, session: Session = Depends(get_session)):
    """Give every trade of this symbol that has no reason yet a copy of the plan's current logic.
    The copy is a snapshot: later edits to the plan do not rewrite history."""
    sym = symbol.strip().upper()
    pl = session.scalar(select(Plan).where(Plan.symbol == sym))
    if not pl or not (pl.rationale or "").strip():
        raise HTTPException(400, "Write the position logic in the plan first.")
    left = list(session.scalars(select(Trade).where(Trade.symbol == sym, Trade.id.not_in(select(TradeReason.trade_id)))))
    for t in left:
        session.add(TradeReason(trade_id=t.id, strategy=pl.strategy or "", fundamental=pl.rationale.strip(), from_plan=True,
                                action="", updated_at=datetime.now(timezone.utc)))
    session.commit()
    return {"ok": True, "updated": len(left)}


@router.get("/trades/outcomes")
def trade_outcomes(session: Session = Depends(get_session)):
    """Share of trades by strategy and outcome. Counts only; the sample is small, so no averages or scores."""
    rows = session.execute(select(Trade, TradeReason).outerjoin(TradeReason, TradeReason.trade_id == Trade.id)).all()
    out: dict[str, dict] = {}
    for t, r in rows:
        k = (r.strategy if r and r.strategy else "none")
        d = out.setdefault(k, {"total": 0, "buy": 0, "sell": 0, "success": 0, "mixed": 0, "failed": 0, "open": 0, "unrated": 0})
        d["total"] += 1
        d[t.side if t.side in ("buy", "sell") else "buy"] += 1
        o = r.outcome if r and r.outcome else "unrated"
        d[o] = d.get(o, 0) + 1
    tot = {k: sum(d[k] for d in out.values()) for k in ("total", "buy", "sell", "success", "mixed", "failed", "open", "unrated")}
    return {"by_strategy": out, "total": tot}


