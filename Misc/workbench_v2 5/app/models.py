"""Four tables. A Review is a full, self-contained thesis state, so any two
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
