"""Trade calendar data: trades by market-local day, review due dates and journal events. Code only, no model calls."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import calendar as cal
from ..database import get_session
from ..models import Company, Holding, JournalEntry, Note, Plan, Trade, TradeReason
from . import routes

router = APIRouter(prefix="/api/v1")


def _current_prices(session: Session) -> dict[str, float]:
    px = {h.symbol: h.price for h in session.scalars(select(Holding)) if h.price}
    for c in session.scalars(select(Company)):
        p = routes._snap_price(session, c.id)
        if p:
            px[c.ticker] = p
    return px


@router.get("/calendar")
def calendar(start: date, end: date, session: Session = Depends(get_session)):
    if end < start or (end - start).days > 1500:
        raise HTTPException(400, "Choose a range of at most 1500 days.")
    lo, hi = (start - timedelta(days=12)).isoformat(), (end + timedelta(days=13)).isoformat()    # padding for time zones and round-trip look-around
    px = _current_prices(session)
    plans = {p.symbol: p for p in session.scalars(select(Plan))}
    rows = []
    for t, r in session.execute(select(Trade, TradeReason).outerjoin(TradeReason, TradeReason.trade_id == Trade.id)
                                .where(Trade.executed_at >= lo, Trade.executed_at < hi).order_by(Trade.executed_at)):
        now = px.get(t.symbol)
        rows.append({**routes._trade(t, r, plans.get(t.symbol)), "date": cal.local_date(t.executed_at, t.symbol), "now": now,
                     "since_pct": cal.since_pct(t.price, now), "pre_split": bool(now and t.price > now * 4)})
    loops = cal.round_trips(rows)
    days: dict[str, dict] = {}

    def day(d: str) -> dict:
        return days.setdefault(d, {"trades": [], "due": [], "events": []})

    s, e = start.isoformat(), end.isoformat()
    for t in rows:
        if s <= t["date"] <= e:
            day(t["date"])["trades"].append({**t, "round_trip": t["id"] in loops})
    for t, r in session.execute(select(Trade, TradeReason).join(TradeReason, TradeReason.trade_id == Trade.id).where(
            TradeReason.revisit_on >= s, TradeReason.revisit_on <= e, TradeReason.reviewed_at.is_(None))):
        day(r.revisit_on)["due"].append({"kind": "trade", "symbol": t.symbol, "trade_id": t.id,
                                         "text": f"Review your {t.side} of {t.quantity:g} at {t.price:g}"})
    for n in session.scalars(select(Note).where(Note.revisit_on >= s, Note.revisit_on <= e, Note.done.is_(False))):
        c = session.get(Company, n.company_id)
        day(n.revisit_on)["due"].append({"kind": "note", "symbol": c.ticker if c else "", "text": n.body[:120]})
    for j in session.scalars(select(JournalEntry)):
        d = j.event_on or j.created_at.date().isoformat()
        if s <= d <= e:
            day(d)["events"].append({"id": j.id, "kind": j.kind, "title": j.title or j.body[:60], "tickers": j.tickers or [],
                                     "is_event": bool(j.event_on)})
        if j.revisit_on and s <= j.revisit_on <= e and not j.done:
            day(j.revisit_on)["due"].append({"kind": "journal", "symbol": ", ".join(j.tickers or []), "text": j.title or j.body[:100]})
    return {"start": s, "end": e, "days": days}


