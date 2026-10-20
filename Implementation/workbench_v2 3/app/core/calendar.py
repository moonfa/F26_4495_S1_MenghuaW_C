"""Pure helpers for the trade calendar: market-local dates and simple behaviour flags. No I/O."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


def market_tz(symbol: str) -> str:
    s = (symbol or "").upper()
    return "Asia/Hong_Kong" if s.endswith(".HK") else "Asia/Singapore" if s.endswith(".SI") else "America/New_York"


def local_date(executed_at: str, symbol: str) -> str:
    """The calendar day the trade happened on in its own market (UTC would put some Hong Kong trades on the wrong day)."""
    d = datetime.fromisoformat(executed_at)
    if d.tzinfo is None:
        d = d.replace(tzinfo=ZoneInfo("UTC"))
    return d.astimezone(ZoneInfo(market_tz(symbol))).date().isoformat()


def round_trips(trades: list[dict], days: int = 10) -> set[int]:
    """Ids of trades where the same symbol was bought and sold within `days` days of each other (a fact, not a verdict)."""
    by: dict[str, list[dict]] = {}
    for t in trades:
        by.setdefault(t["symbol"], []).append(t)
    out: set[int] = set()
    for rows in by.values():
        for a in rows:
            for b in rows:
                if a["side"] == "buy" and b["side"] == "sell" and abs((date.fromisoformat(a["date"]) - date.fromisoformat(b["date"])).days) <= days:
                    out.update((a["id"], b["id"]))
    return out


def since_pct(price: float | None, now: float | None) -> float | None:
    return round(now / price - 1, 4) if price and now else None


