from collections.abc import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from . import config

_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_session() -> Generator[Session, None, None]:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def normalize_symbols() -> None:
    """One-off fix: BRK.B -> BRK-B in rows imported before symbols were normalised (never overwrites an existing row)."""
    from sqlalchemy import select, update
    from sqlalchemy.orm import Session
    from . import models as m
    from .portfolio import norm_symbol
    with Session(engine) as s:
        have = set(s.scalars(select(m.Company.ticker)))
        for col, model in ((m.Holding.symbol, m.Holding), (m.Trade.symbol, m.Trade), (m.Plan.symbol, m.Plan), (m.Company.ticker, m.Company)):
            for old in set(s.scalars(select(col))):
                new = norm_symbol(old)
                if new != old and not (model is m.Company and new in have) and not (model is m.Plan and s.scalar(select(m.Plan.id).where(m.Plan.symbol == new))):
                    s.execute(update(model).where(col == old).values({col.key: new}))
        s.commit()


def ensure_columns() -> None:
    """Tiny migration: add columns that newer models have but an existing SQLite table lacks."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'))
