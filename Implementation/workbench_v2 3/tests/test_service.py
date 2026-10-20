"""Integration test: fake evidence adapter + mock provider + in-memory SQLite.
Run: python -m pytest -q   (needs the packages in requirements.txt, not OpenBB)."""
import copy
import os
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AI_PROVIDER"] = "mock"

import pytest
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import database, models, service
from app.ai.provider import MockProvider

BASE = {"company": {"symbol": "TST", "name": "Test Co"},
        "market": {"current_price": 100.0},
        "valuation": {"pe_ttm": 20.0, "free_cash_flow_yield": 0.04},
        "financial_health": {"gross_margin": 0.40, "revenue_growth": 0.08},
        "analyst_consensus": {"target_consensus": 120.0},
        "recent_news": [{"title": "Quiet day", "date": "2026-09-01"}]}


class FakeAdapter:
    def __init__(self):
        self.ev = copy.deepcopy(BASE)

    def get_equity_research_snapshot(self, ticker):
        return copy.deepcopy(self.ev), {}


@pytest.fixture()
def session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    database.Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def test_lifecycle(session):
    ad, ai = FakeAdapter(), MockProvider()
    r1 = service.refresh(session, "tst", adapter=ad, provider=ai)
    assert r1.kind == "baseline" and len(r1.state["assumptions"]) == 3

    # price rally only -> deterministic check, no LLM
    ad.ev["market"]["current_price"] = 120.0
    ad.ev["valuation"]["pe_ttm"] = 24.0
    ad.ev["valuation"]["free_cash_flow_yield"] = 0.04 * 100 / 120
    r2 = service.refresh(session, "tst", adapter=ad, provider=ai)
    assert r2.kind == "check" and r2.provider == "none"

    # repeated heartbeat collapses into the same row
    r3 = service.refresh(session, "tst", adapter=ad, provider=ai)
    assert r3.id == r2.id

    # real fundamental change -> LLM update, anchored on the baseline
    ad.ev["financial_health"]["gross_margin"] = 0.30
    r4 = service.refresh(session, "tst", adapter=ad, provider=ai)
    assert r4.kind == "update" and r4.level == "material" and r4.prev_review_id == r1.id

    # the update is now the anchor, so identical inputs mean "nothing changed": a free check, no model call
    r5 = service.refresh(session, "tst", adapter=ad, provider=ai)
    assert r5.kind == "check" and r5.provider == "none" and r5.prev_review_id == r4.id




def test_focus_level_and_held_flag(session):
    """2.28.0: focus level is manual (focus | normal | archived); 'held' comes from the broker import."""
    from app.api import routes
    session.add_all([models.Company(ticker="AAA", name="A", status="holding"), models.Company(ticker="BBB", name="B", status="watching"),
                     models.Company(ticker="CCC", name="C", status="focus"), models.Company(ticker="DDD", name="D")])
    session.add(models.Holding(symbol="AAA", code="AAA", name="A", quantity=5, currency="USD", kind="stock"))
    session.add(models.Holding(symbol="BBB", code="BBB", name="B", quantity=0, currency="USD", kind="stock"))
    session.commit()
    rows = {r["ticker"]: r for r in routes.companies(session)}
    assert [rows[t]["status"] for t in ("AAA", "BBB", "CCC", "DDD")] == ["normal", "normal", "focus", "normal"]
    assert rows["AAA"]["held"] is True and rows["BBB"]["held"] is False and rows["CCC"]["held"] is False
    routes.set_status("DDD", routes.StatusIn(status="focus"), session)
    routes.set_status("AAA", routes.StatusIn(status="watching"), session)           # old value from an old client
    assert session.query(models.Company).filter_by(ticker="DDD").one().status == "focus"
    assert session.query(models.Company).filter_by(ticker="AAA").one().status == "normal"
