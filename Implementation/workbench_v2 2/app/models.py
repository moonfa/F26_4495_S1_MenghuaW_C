"""Four tables. A Review is a full, self-contained thesis state, so any two
reviews can be diffed and the timeline is just the list of reviews."""
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, Index
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
    kind: Mapped[str] = mapped_column(String(24), default="general")
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
