"""Deterministic change detection. Pure Python, no I/O, no AI.

Valuation multiples move with the share price, so a P/E jump caused by a rally
is NOT a fundamental change. We strip the price effect before deciding whether
anything thesis-relevant happened.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from dataclasses import dataclass
from typing import Any

FUNDAMENTAL_SECTIONS = ("financial_health", "analyst_consensus")
MULTIPLES = ("pe_ttm", "forward_pe", "peg", "price_to_sales", "price_to_book",
             "price_to_free_cash_flow", "ev_to_ebitda")   # scale WITH price
YIELDS = ("free_cash_flow_yield",)                          # scale INVERSELY

HARD_NEWS = ("raises guidance", "cuts guidance", "lowers guidance", "withdraws guidance",
             "earnings miss", "earnings beat", "acquisition", "acquires", "merger",
             "bankruptcy", "restatement", "sec investigation", "antitrust",
             "ceo resign", "ceo steps down", "chief executive",
             "上调指引", "下调指引", "撤回指引", "业绩不及预期", "业绩超预期",
             "收购", "并购", "破产", "财务重述", "反垄断", "首席执行官辞职")
SOFT_NEWS = ("guidance", "downgrade", "upgrade", "lawsuit", "recall", "layoff",
             "dividend", "buyback", "repurchase", "investigation", "cfo",
             "指引", "评级下调", "评级上调", "诉讼", "召回", "裁员", "分红", "回购")


@dataclass(frozen=True)
class Thresholds:
    fundamental_minor: float = 0.03
    fundamental_material: float = 0.15
    valuation_minor: float = 0.08      # measured after removing the price effect
    valuation_material: float = 0.20
    abs_floor: float = 1e-4


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _pct(old: float, new: float) -> float:
    return (new - old) / max(abs(old), 1e-9)


def price_of(evidence: dict | None) -> float | None:
    return _num(((evidence or {}).get("market") or {}).get("current_price"))


def news_titles(evidence: dict | None) -> list[str]:
    return [str(n["title"]).strip() for n in (evidence or {}).get("recent_news") or []
            if isinstance(n, dict) and n.get("title")]


def compute_delta(cur: dict, prev: dict | None, th: Thresholds = Thresholds()) -> dict:
    """Compare current evidence with the last *analysed* anchor."""
    if not prev:
        return {"status": "initial", "price_pct": None, "fundamental_changes": [],
                "valuation_changes": [], "new_news": [], "price_driven_valuation": False}

    p_old, p_new = price_of(prev), price_of(cur)
    price_pct = _pct(p_old, p_new) if p_old and p_new else None

    fund = []
    for sec in FUNDAMENTAL_SECTIONS:
        a, b = prev.get(sec) or {}, cur.get(sec) or {}
        for k, v in b.items():
            old, new = _num(a.get(k)), _num(v)
            if old is None or new is None or abs(new - old) < th.abs_floor:
                continue
            pc = _pct(old, new)
            if abs(pc) >= th.fundamental_minor:
                fund.append({"metric": f"{sec}.{k}", "old": old, "new": new, "pct": round(pc, 4)})

    val, price_driven = [], False
    a, b = prev.get("valuation") or {}, cur.get("valuation") or {}
    for k in MULTIPLES + YIELDS:
        old, new = _num(a.get(k)), _num(b.get(k))
        if old is None or new is None or old == 0:
            continue
        raw = _pct(old, new)
        if price_pct is None:
            non_price = raw
        elif k in YIELDS:
            non_price = (1 + raw) * (1 + price_pct) - 1
        else:
            non_price = (1 + raw) / (1 + price_pct) - 1
        if abs(non_price) >= th.valuation_minor:
            val.append({"metric": f"valuation.{k}", "old": old, "new": new,
                        "raw_pct": round(raw, 4), "ex_price_pct": round(non_price, 4)})
        elif abs(raw) >= th.valuation_minor:
            price_driven = True

    old_t = set(news_titles(prev))
    fresh = [n for n in (cur.get("recent_news") or [])
             if isinstance(n, dict) and n.get("title") and str(n["title"]).strip() not in old_t]
    new_news = [{"title": n["title"], "date": n.get("date"), "source": n.get("source")} for n in fresh[:8]]

    changed = bool(fund or val or new_news)
    return {"status": "changed" if changed else "unchanged",
            "price_pct": None if price_pct is None else round(price_pct, 4),
            "fundamental_changes": fund[:20], "valuation_changes": val[:10],
            "new_news": new_news, "price_driven_valuation": price_driven}


def classify(delta: dict, th: Thresholds = Thresholds()) -> tuple[str, str]:
    """(level, reason); level is none | minor | material."""
    if delta.get("status") == "initial":
        return "material", "No prior analysis: baseline required."
    text = " ".join(n["title"].lower() for n in delta.get("new_news") or [])
    hard = next((w for w in HARD_NEWS if w in text), None)
    if hard:
        return "material", f"Material news keyword: '{hard}'."
    big_f = [c for c in delta.get("fundamental_changes") or [] if abs(c["pct"]) >= th.fundamental_material]
    if big_f:
        return "material", f"{big_f[0]['metric']} moved >= {th.fundamental_material:.0%}."
    big_v = [c for c in delta.get("valuation_changes") or [] if abs(c["ex_price_pct"]) >= th.valuation_material]
    if big_v:
        return "material", f"{big_v[0]['metric']} moved >= {th.valuation_material:.0%} beyond price."
    if delta.get("fundamental_changes"):
        return "minor", "Fundamental metric(s) moved beyond the minor threshold."
    if delta.get("valuation_changes"):
        return "minor", "Valuation changed beyond what price explains."
    soft = next((w for w in SOFT_NEWS if w in text), None)
    if soft:
        return "minor", f"News keyword: '{soft}'."
    if len(delta.get("new_news") or []) >= 3:
        return "minor", "Three or more new headlines."
    return "none", "No thesis-relevant change (price and multiple moves are explained by price)."


def fingerprint(evidence: dict) -> str:
    """Hash of rounded, thesis-relevant evidence. Excludes price, market cap and news,
    so a price tick never invalidates the LLM cache."""
    out: dict[str, float] = {}
    for sec in FUNDAMENTAL_SECTIONS:
        for k, v in (evidence.get(sec) or {}).items():
            n = _num(v)
            if n is not None:
                out[f"{sec}.{k}"] = float(f"{n:.3g}")
    return hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()[:24]


def compact_evidence(evidence: dict, max_desc: int = 500) -> dict:
    """Strip nulls and bulky text before sending to the model."""
    def clean(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items() if v not in (None, "", [], {})}
        if isinstance(o, list):
            return [clean(x) for x in o]
        return round(o, 4) if isinstance(o, float) else o
    e = dict(evidence)
    e.pop("data_quality", None)
    e.pop("schema_version", None)
    comp = dict(e.get("company") or {})
    for k in ("company_url", "employees", "stock_exchange"):
        comp.pop(k, None)
    if comp.get("long_description"):
        comp["long_description"] = str(comp["long_description"])[:max_desc]
    e["company"] = comp
    e["recent_news"] = [{"date": n.get("date"), "title": n.get("title")} for n in (e.get("recent_news") or [])[:5]]
    e["evidence_basis"] = evidence_basis(evidence)
    e["data_gaps"] = data_gaps(evidence)
    e["derived"] = derived_metrics(evidence)
    return clean(e)


# ---------------------------------------------------------------------------
# Evidence basis, data gaps and code-computed "what the price implies" metrics.
# All arithmetic happens here; the model only interprets the results.
# ---------------------------------------------------------------------------
CYCLICAL_WORDS = ("memory", "semiconductor", "steel", "oil", "gas", "coal", "mining", "gold", "copper", "aluminum",
                  "chemical", "auto manufacturers", "airline", "shipping", "marine", "homebuild", "building materials",
                  "lumber", "paper", "agricultural", "farm", "equipment", "metals", "uranium", "solar")
CYCLICAL_SECTORS = ("energy", "basic materials")
STALE_DAYS = 380


def _first_num(*vals):
    for v in vals:
        n = _num(v)
        if n is not None:
            return n
    return None


def _age_days(iso, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(str(iso)[:10])).days
    except ValueError:
        return None


def evidence_basis(ev: dict, now: datetime | None = None) -> dict:
    """What period each block of evidence covers. Ratios have no period tag in the source (TTM / latest reported);
    statement rows do, and they can lag the ratios right after earnings."""
    today = (now or datetime.now(timezone.utc)).date()
    fh = ev.get("financial_health") or {}
    inc = fh.get("income_statement_latest") or {}
    cfh = fh.get("cash_flow_history") or []
    ends = [x for x in (inc.get("period_ending"), (cfh[0] or {}).get("period_ending") if cfh else None) if x]
    age = _age_days(max(ends), today) if ends else None
    out = {"retrieved": today.isoformat(),
           "ratios": "TTM or latest reported (Yahoo Finance via OpenBB); the source gives no period label",
           "statements": {"period_end": inc.get("period_ending"), "fiscal_year": inc.get("fiscal_year"),
                          "fiscal_period": inc.get("fiscal_period"), "age_days": age,
                          "stale": bool(age is not None and age > STALE_DAYS)}}
    if cfh:
        out["cash_flow_history"] = "annual fiscal years " + ", ".join(str(r.get("fiscal_year") or r.get("period_ending")) for r in cfh[:4])
    return out


def data_gaps(ev: dict, now: datetime | None = None) -> list[str]:
    gaps = []
    b = evidence_basis(ev, now)
    if b["statements"]["stale"]:
        gaps.append(f"Statement rows end {b['statements']['period_end']} ({b['statements']['age_days']} days old) while ratios are newer "
                    "(TTM); do not combine figures across the two.")
    if not (ev.get("recent_news") or []):
        gaps.append("No news returned by the data source.")
    if not any(_num(v) is not None for v in (ev.get("analyst_consensus") or {}).values()):
        gaps.append("No analyst consensus data.")
    if not any(_num(v) is not None for v in (ev.get("financial_health") or {}).values()):
        gaps.append("No financial-health ratios.")
    return gaps


def is_cyclical(ev: dict) -> str | None:
    co = ev.get("company") or {}
    text = f"{co.get('industry') or ''} {co.get('sector') or ''}".lower()
    hit = next((w for w in CYCLICAL_WORDS if w in text), None) or next((w for w in CYCLICAL_SECTORS if w in text), None)
    return hit


def derived_metrics(ev: dict) -> dict:
    """Simple ratios computed from fields we already hold. No forecasts are invented."""
    m, v, fh = ev.get("market") or {}, ev.get("valuation") or {}, ev.get("financial_health") or {}
    cap = _num(m.get("market_cap"))
    cfh = fh.get("cash_flow_history") or []
    fcf = _first_num(fh.get("free_cash_flow"), (cfh[0] or {}).get("free_cash_flow") if cfh else None)
    fy = (cfh[0] or {}).get("fiscal_year") if cfh else None
    ev_val = _first_num(v.get("enterprise_value"), m.get("enterprise_value"))
    pe, fpe = _num(v.get("pe_ttm")), _num(v.get("forward_pe"))
    out: dict = {}
    if cap and fcf is not None:
        out["fcf_yield"] = {"value": round(fcf / cap, 4), "basis": f"FCF {'FY' + str(fy) if fy else 'latest'} / market cap"}
    if ev_val and fcf:
        out["ev_to_fcf"] = {"value": round(ev_val / fcf, 1), "basis": "enterprise value / latest annual FCF"}
    if pe and pe > 0:
        out["earnings_yield_ttm"] = {"value": round(1 / pe, 4), "basis": "1 / P/E (TTM)"}
    if fpe and fpe > 0:
        out["earnings_yield_forward"] = {"value": round(1 / fpe, 4), "basis": "1 / forward P/E (consensus)"}
    if pe and fpe and pe > 0 and fpe > 0:
        out["consensus_implied_eps_change"] = {"value": round(pe / fpe - 1, 3),
            "basis": "TTM P/E divided by forward P/E at one price: analysts expect forward EPS to differ from TTM EPS by this much (derived)"}
    hit = is_cyclical(ev)
    if hit:
        out["cyclical_flag"] = {"matched": hit, "caution": "Cyclical industry: a low P/E can mean peak earnings. Judge on mid-cycle earnings, not spot."}
    return out
