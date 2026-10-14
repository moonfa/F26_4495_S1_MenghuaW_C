"""Core tables. A Review is a full, self-contained thesis state, so any two
reviews can be diffed and the timeline is just the list of reviews."""
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(10), default="en")
    status: Mapped[str | None] = mapped_column(String(10), nullable=True, default="watching")   # holding|watching|idea|archived
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Snapshot(Base):
    """Normalized evidence at a point in time (raw provider payload is not stored)."""
    __tablename__ = "snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class Review(Base):
    """kind: baseline | rebaseline | update (LLM) | check (deterministic, no LLM).
    level: none | minor | material. view: constructive | neutral | cautious."""
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"))
    prev_review_id: Mapped[int | None] = mapped_column(ForeignKey("reviews.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(16))
    level: Mapped[str] = mapped_column(String(10))
    level_reason: Mapped[str] = mapped_column(Text, default="")
    view: Mapped[str] = mapped_column(String(16))
    view_change: Mapped[str] = mapped_column(String(10))          # new | up | unchanged | down
    one_liner: Mapped[str] = mapped_column(Text)
    state: Mapped[dict[str, Any]] = mapped_column(JSON)           # profile, assumptions, monitor
    changes: Mapped[list | None] = mapped_column(JSON, nullable=True)   # [{what, so_what}]
    narrative: Mapped[str] = mapped_column(Text, default="")
    delta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="zh-CN")
    provider: Mapped[str] = mapped_column(String(30), default="none")
    model: Mapped[str] = mapped_column(String(120), default="")
    prompt_version: Mapped[str] = mapped_column(String(60), default="")
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)     # token counts
    zh: Mapped[dict | None] = mapped_column(JSON, nullable=True)        # {"items": {key: Chinese text}, "model", "usage"}
    __table_args__ = (Index("ix_review_company_time", "company_id", "created_at", "id"),)


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    review_id: Mapped[int | None] = mapped_column(ForeignKey("reviews.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(24), default="comment")   # decision | comment | source | question
    body: Mapped[str] = mapped_column(Text)
    assumption_id: Mapped[str | None] = mapped_column(String(8), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)     # captured automatically
    revisit_on: Mapped[str | None] = mapped_column(String(10), nullable=True)   # YYYY-MM-DD
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssumptionDriver(Base):
    """Which valuation input a thesis assumption bears on. Chosen by the user; the program never guesses a link."""
    __tablename__ = "assumption_drivers"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    assumption_id: Mapped[str] = mapped_column(String(8))
    driver: Mapped[str] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("ux_driver_company_assumption", "company_id", "assumption_id", unique=True),)


class Holding(Base):
    """Latest imported snapshot of broker positions (replaced on each import)."""
    __tablename__ = "holdings"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(20), index=True)      # data-source symbol, e.g. 9961.HK
    name: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(8), default="stock")    # stock | etf | cash
    currency: Mapped[str] = mapped_column(String(4), default="USD")
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)           # broker's diluted cost
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)         # broker-computed, fraction of account
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Trade(Base):
    """Filled quantities only. `key` de-duplicates repeated imports."""
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True)
    code: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(4), default="USD")
    market: Mapped[str] = mapped_column(String(10), default="")
    executed_at: Mapped[str] = mapped_column(String(32), index=True)


class Plan(Base):
    """Your own price discipline for a symbol (works for holdings with no analysis, and for watch-list names)."""
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    style: Mapped[str] = mapped_column(String(12), default="investment")      # investment | trade | defensive
    buy_below: Mapped[float | None] = mapped_column(Float, nullable=True)     # target cost / add zone
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    rules: Mapped[str] = mapped_column(Text, default="")                      # add / trim / exit rules, free text
    target_amount: Mapped[float | None] = mapped_column(Float, nullable=True)  # position value you intend to hold, in the stock's currency
    max_amount: Mapped[float | None] = mapped_column(Float, nullable=True)     # position value above which you review concentration
    strategy: Mapped[str] = mapped_column(String(16), default="")              # holding strategy for this position (see Guide)
    rationale: Mapped[str] = mapped_column(Text, default="")                   # the standing logic behind the position; trades inherit it
    rationale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TradeReason(Base):
    """Why you made a trade, and how it turned out. One row per imported trade."""
    __tablename__ = "trade_reasons"
    id: Mapped[int] = mapped_column(primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"), unique=True, index=True)
    strategy: Mapped[str] = mapped_column(String(16), default="")           # long_term | swing | short_term | defensive | rebalance
    fundamental: Mapped[str] = mapped_column(Text, default="")
    technical: Mapped[str] = mapped_column(Text, default="")
    revisit_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    review: Mapped[str] = mapped_column(Text, default="")                   # outcome, written later
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_on: Mapped[str | None] = mapped_column(String(10), nullable=True)      # day the decision was made (defaults to the trade day)
    outcome: Mapped[str] = mapped_column(String(8), default="")                    # "" | open | success | mixed | failed
    followup: Mapped[str] = mapped_column(Text, default="")                        # what you will do next
    action: Mapped[str] = mapped_column(String(10), default="")                    # role in the position: initial | add | trim | exit | swap
    from_plan: Mapped[bool] = mapped_column(Boolean, default=False)                # logic text was copied from the plan at the time


class JournalEntry(Base):
    """Portfolio-level diary: decisions, periodic reviews, macro ideas, outside sources. Private; never sent to a model."""
    __tablename__ = "journal_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(12), default="decision")        # decision | review | macro | source
    title: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    tickers: Mapped[list | None] = mapped_column(JSON, nullable=True)       # symbols this entry is about
    revisit_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    event_on: Mapped[str | None] = mapped_column(String(10), nullable=True)      # the day a market event happened (war, outbreak, ...)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)      # portfolio as it stood when written
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


