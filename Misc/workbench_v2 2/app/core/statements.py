"""Annual and quarterly statement rows: merge, margins and growth. Pure Python; all arithmetic is done here, not by the model."""
from __future__ import annotations

from typing import Any

FIELDS = ("revenue", "gross_profit", "operating_income", "net_income", "diluted_eps",
          "operating_cash_flow", "capital_expenditure", "free_cash_flow")


def _n(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _end(row: dict) -> str | None:
    v = row.get("period_ending")
    return str(v)[:10] if v else None


def merge(income: list[dict], cash: list[dict], n: int) -> list[dict]:
    """Join income and cash-flow rows on period end, newest first, keeping only the fields we use."""
    by: dict[str, dict] = {}
    for src in (income or [], cash or []):
        for row in src:
            e = _end(row)
            if not e:
                continue
            d = by.setdefault(e, {"period_ending": e})
            for k in ("fiscal_year", "fiscal_period"):
                if row.get(k) is not None and d.get(k) is None:
                    d[k] = row[k]
            for k in FIELDS:
                v = _n(row.get(k))
                if v is not None and d.get(k) is None:
                    d[k] = v
    out = [by[k] for k in sorted(by, reverse=True)][:n]
    for d in out:
        if d.get("free_cash_flow") is None and d.get("operating_cash_flow") is not None and d.get("capital_expenditure") is not None:
            capex = d["capital_expenditure"]
            d["free_cash_flow"] = d["operating_cash_flow"] + (capex if capex <= 0 else -capex)
    return out


def _ratio(a, b):
    return round(a / b, 4) if a is not None and b not in (None, 0) else None


def _growth(new, old):
    return round(new / old - 1, 4) if new is not None and old not in (None, 0) and old > 0 else None


def analyse(rows: list[dict], lag: int) -> list[dict]:
    """Add margins and growth. `lag` is how many rows back is the same period a year ago (4 for quarters, 1 for years)."""
    out = []
    for i, r in enumerate(rows):
        prior = rows[i + lag] if i + lag < len(rows) else None
        prev = rows[i + 1] if i + 1 < len(rows) else None
        d = dict(r)
        d["gross_margin"] = _ratio(r.get("gross_profit"), r.get("revenue"))
        d["operating_margin"] = _ratio(r.get("operating_income"), r.get("revenue"))
        d["net_margin"] = _ratio(r.get("net_income"), r.get("revenue"))
        d["fcf_margin"] = _ratio(r.get("free_cash_flow"), r.get("revenue"))
        d["revenue_yoy"] = _growth(r.get("revenue"), prior.get("revenue")) if prior else None
        d["eps_yoy"] = _growth(r.get("diluted_eps"), prior.get("diluted_eps")) if prior else None
        d["revenue_qoq"] = _growth(r.get("revenue"), prev.get("revenue")) if (prev and lag == 4) else None
        out.append(d)
    return out


def view(statements: dict | None) -> dict:
    s = statements or {}
    return {"annual": analyse(s.get("annual") or [], 1), "quarterly": analyse(s.get("quarterly") or [], 4)}


def latest_quarter_end(statements: dict | None) -> str | None:
    q = (statements or {}).get("quarterly") or []
    return _end(q[0]) if q else None


def quarterly_trend(statements: dict | None) -> dict | None:
    """Last four quarters in a form small enough to send to the model."""
    q = view(statements)["quarterly"][:4]
    if not q:
        return None
    rows = [{k: v for k, v in {"period_end": r["period_ending"], "revenue_yoy": r.get("revenue_yoy"),
                               "gross_margin": r.get("gross_margin"), "operating_margin": r.get("operating_margin"),
                               "fcf_margin": r.get("fcf_margin"), "eps_yoy": r.get("eps_yoy")}.items() if v is not None} for r in q]
    out: dict = {"basis": "single reported quarters, newest first; margins and growth computed in code (growth vs the same quarter a year earlier)",
                 "quarters": rows}
    a, b = q[0].get("operating_margin"), (q[4 - 1].get("operating_margin") if len(q) >= 4 else None)
    if a is not None and b is not None:
        out["operating_margin_change_over_4q_pp"] = round((a - b) * 100, 1)
    return out


