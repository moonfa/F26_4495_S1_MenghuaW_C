"""Valuation as seen from a company's research page. Reads the valuation lab's own store and the thesis; changes neither.
The only thing written here is the user's own assumption-to-valuation-input link."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core import valuation_link as link
from ..database import get_session
from ..models import AssumptionDriver, Company, Plan, Review, Snapshot
from . import valuation as store

router = APIRouter(prefix="/api/v1")


def _company(session: Session, ticker: str) -> Company:
    c = session.scalar(select(Company).where(Company.ticker == ticker.strip().upper()))
    if not c:
        raise HTTPException(404, "Company not found. Run refresh first.")
    return c


def _latest(kind: str, ticker: str, limit: int = 1) -> list[str]:
    with store.connect() as c:
        rows = c.execute("SELECT id FROM valuations WHERE ticker=? AND kind=? ORDER BY rowid DESC LIMIT ?", (ticker, kind, limit)).fetchall()
    return [r[0] for r in rows]


def _drivers(session: Session, company_id: int) -> dict[str, str]:
    return {d.assumption_id: d.driver for d in session.scalars(select(AssumptionDriver).where(AssumptionDriver.company_id == company_id))}


@router.get("/companies/{ticker}/valuation")
def company_valuation(ticker: str, session: Session = Depends(get_session)):
    c = _company(session, ticker)
    revs = list(session.scalars(select(Review).where(Review.company_id == c.id).order_by(Review.created_at, Review.id)))
    thesis = [r for r in revs if r.kind != "check"]
    assumptions = [{"id": a["id"], "statement": a.get("statement", ""), "status": a.get("status")} for a in (thesis[-1].state.get("assumptions") or [])] if thesis else []
    snap = session.scalar(select(Snapshot).where(Snapshot.company_id == c.id).order_by(Snapshot.retrieved_at.desc(), Snapshot.id.desc()))
    plan = session.scalar(select(Plan).where(Plan.symbol == c.ticker))
    data_ids = _latest("data", c.ticker)
    data = store.read(data_ids[0]) if data_ids else None
    analyses = []
    for aid in _latest("analysis", c.ticker, 20):
        rec = store.read(aid)
        try:
            d = store.read(rec["payload"]["data_id"])["payload"]
            rec["data_price"], rec["data_fetched"] = (d.get("quote") or {}).get("value"), d.get("retrieved_at")
        except HTTPException:
            rec["data_price"] = rec["data_fetched"] = None
        analyses.append(rec)
    out = link.summarize(data, analyses, snap.price if snap else None,
                         [{"created_at": r.created_at.isoformat() if r.created_at else None, "kind": r.kind, "level": r.level} for r in revs],
                         assumptions, _drivers(session, c.id),
                         plan and {"buy_below": plan.buy_below, "target_price": plan.target_price}, datetime.now(timezone.utc))
    out["assumptions"] = assumptions
    out["assumption_drivers"] = _drivers(session, c.id)
    return out


class DriverIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    driver: str = ""          # "" or "none" removes the link


@router.put("/companies/{ticker}/assumption-drivers/{assumption_id}")
def put_driver(ticker: str, assumption_id: str, payload: DriverIn, session: Session = Depends(get_session)):
    c = _company(session, ticker)
    if not assumption_id.startswith("a") or not assumption_id[1:].isdigit():
        raise HTTPException(422, "Invalid assumption id")
    session.execute(delete(AssumptionDriver).where(AssumptionDriver.company_id == c.id, AssumptionDriver.assumption_id == assumption_id))
    if payload.driver and payload.driver != "none":
        if payload.driver not in link.DRIVERS:
            raise HTTPException(422, "Unknown valuation input")
        session.add(AssumptionDriver(company_id=c.id, assumption_id=assumption_id, driver=payload.driver))
    session.commit()
    return {"assumption_id": assumption_id, "driver": payload.driver if payload.driver in link.DRIVERS else ""}
