"""Portfolio journal: private diary entries plus a code-generated review checklist (no model calls)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import service
from ..database import get_session
from ..models import Company, JournalEntry, Note, Review, Trade, TradeReason
from . import routes

router = APIRouter(prefix="/api/v1")
ALERTS = {"stop_breached", "near_stop", "target_reached", "near_target", "buy_zone"}


def _naive(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=None) if d and d.tzinfo else d


def _snapshot(session: Session) -> dict:
    """Compact picture of the portfolio right now, stored with each entry so the decision can be judged in context."""
    p = routes.get_portfolio(session)
    return {"as_of": datetime.now(timezone.utc).isoformat(), "positions": p["count"], "top5": p["top5"],
            "cautious": p["cautious"], "unanalysed": p["unanalysed"],
            "holdings": [{"symbol": i["symbol"], "weight": i["weight"], "view": i["view"], "price": i["price"],
                          "plan_status": (i["plan_status"] or {}).get("status")} for i in p["items"][:15]]}


def _entry(e: JournalEntry) -> dict:
    return {"id": e.id, "kind": e.kind, "title": e.title, "body": e.body, "tickers": e.tickers or [], "revisit_on": e.revisit_on,
            "done": e.done, "snapshot": e.snapshot, "created_at": e.created_at}


class EntryIn(BaseModel):
    kind: Literal["decision", "review", "macro", "source"] = "decision"
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=20000)
    tickers: list[str] = Field(default_factory=list, max_length=30)
    revisit_on: date | None = None


@router.get("/journal")
def list_entries(kind: str | None = None, ticker: str | None = None, session: Session = Depends(get_session)):
    q = select(JournalEntry).order_by(JournalEntry.created_at.desc(), JournalEntry.id.desc())
    if kind:
        q = q.where(JournalEntry.kind == kind)
    rows = [_entry(e) for e in session.scalars(q)]
    if ticker:
        rows = [r for r in rows if ticker.upper() in r["tickers"]]
    return rows


@router.post("/journal", status_code=201)
def add_entry(payload: EntryIn, session: Session = Depends(get_session)):
    if not (payload.title.strip() or payload.body.strip()):
        raise HTTPException(400, "Write a title or some text first.")
    e = JournalEntry(kind=payload.kind, title=payload.title.strip(), body=payload.body.strip(),
                     tickers=sorted({t.strip().upper() for t in payload.tickers if t.strip()}),
                     revisit_on=payload.revisit_on.isoformat() if payload.revisit_on else None, snapshot=_snapshot(session))
    session.add(e)
    session.commit()
    return _entry(e)


@router.post("/journal/{entry_id}/done")
def entry_done(entry_id: int, session: Session = Depends(get_session)):
    e = session.get(JournalEntry, entry_id)
    if not e:
        raise HTTPException(404, "Entry not found")
    e.done = True
    session.commit()
    return {"ok": True}


@router.delete("/journal/{entry_id}")
def entry_delete(entry_id: int, session: Session = Depends(get_session)):
    e = session.get(JournalEntry, entry_id)
    if e:
        session.delete(e)
        session.commit()
    return {"ok": True}


@router.get("/journal/checklist")
def checklist(since: date | None = None, session: Session = Depends(get_session)):
    """What to look at in a portfolio review, computed from stored data. Default window: since the last review entry, else 30 days."""
    if since:
        start = datetime(since.year, since.month, since.day)
    else:
        last = session.scalar(select(JournalEntry).where(JournalEntry.kind == "review").order_by(JournalEntry.created_at.desc()))
        start = _naive(last.created_at) if last else datetime.utcnow() - timedelta(days=30)
    iso, today = start.isoformat(), date.today().isoformat()
    p = routes.get_portfolio(session)
    cos = {c.id: c for c in session.scalars(select(Company))}

    trades = []
    for t, r in session.execute(select(Trade, TradeReason).outerjoin(TradeReason, TradeReason.trade_id == Trade.id)
                                .where(Trade.executed_at >= iso).order_by(Trade.executed_at.desc())):
        trades.append({"id": t.id, "symbol": t.symbol, "side": t.side, "quantity": t.quantity, "price": t.price,
                       "currency": t.currency, "executed_at": t.executed_at, "has_reason": bool(r)})

    changes = []
    for c in cos.values():
        prev = None
        for r in routes._reviews(session, c.id):
            if r.kind == "check":
                continue
            if _naive(r.created_at) >= start and r.kind != "baseline":
                ac = routes._a_changes(prev, r)
                if r.view_change in ("up", "down") or ac:
                    changes.append({"symbol": c.ticker, "when": r.created_at, "view": r.view, "view_change": r.view_change,
                                    "assumptions": [{"id": a["id"], "from": a["from"], "to": a["to"]} for a in ac]})
            prev = r
    changes.sort(key=lambda x: str(x["when"]), reverse=True)

    alerts = [{"symbol": i["symbol"], "status": i["plan_status"]["status"]} for i in p["items"]
              if i["plan_status"] and i["plan_status"]["status"] in ALERTS]
    stale = []
    for i in p["items"]:
        if i["kind"] != "stock":
            continue
        c = next((x for x in cos.values() if x.ticker == i["symbol"]), None)
        a = service.latest_review(session, c.id, analysed_only=True) if c else None
        age = (datetime.utcnow() - _naive(a.created_at)).days if a else None
        if a is None or age > 30:
            stale.append({"symbol": i["symbol"], "weight": i["weight"], "days": age})
    due = [{"kind": "note", "symbol": cos[n.company_id].ticker if n.company_id in cos else "", "text": n.body[:140], "revisit_on": n.revisit_on}
           for n in session.scalars(select(Note).where(Note.done.is_(False), Note.revisit_on.is_not(None), Note.revisit_on <= today))]
    for t, r in session.execute(select(Trade, TradeReason).join(TradeReason, TradeReason.trade_id == Trade.id).where(
            TradeReason.revisit_on.is_not(None), TradeReason.revisit_on <= today, TradeReason.reviewed_at.is_(None))):
        due.append({"kind": "trade", "symbol": t.symbol, "text": f"{t.side} {t.quantity:g} @ {t.price:g} ({t.executed_at[:10]})", "revisit_on": r.revisit_on})
    due += [{"kind": "journal", "symbol": ", ".join(e.tickers or []), "text": e.title or e.body[:100], "revisit_on": e.revisit_on}
            for e in session.scalars(select(JournalEntry).where(JournalEntry.done.is_(False), JournalEntry.revisit_on.is_not(None),
                                                                 JournalEntry.revisit_on <= today))]
    return {"since": iso[:10], "exposure": {"positions": p["count"], "top5": p["top5"], "cautious": p["cautious"], "unanalysed": p["unanalysed"]},
            "trades": trades, "trades_without_reason": sum(1 for t in trades if not t["has_reason"]),
            "changes": changes, "plan_alerts": alerts, "stale": stale[:8], "due": due}
