"""Chinese view of a stored analysis. Only free-text fields are translated; numbers, ids, tickers and enums are never sent.
Translations are stored per review as {key: text}; a review never changes after it is written, so a stored translation never goes stale."""
from __future__ import annotations

import copy
from typing import Iterator

PROFILE = ("classification", "business_model", "moat", "bear_case", "valuation_view")
ASSUMPTION = ("statement", "kill_criteria", "causal_mechanism", "missing_evidence", "warning_trigger", "last_reason", "time_horizon")
MONITOR = ("indicator", "why", "trigger", "why_this_level")


def _t(key: str, c, f) -> Iterator[tuple[str, object, object]]:
    try:
        v = c[f]
    except (KeyError, IndexError, TypeError):
        return
    if isinstance(v, str) and v.strip():
        yield key, c, f


def targets(r: dict) -> Iterator[tuple[str, object, object]]:
    """Every translatable (key, container, field) in a review-shaped dict: {one_liner, narrative, changes, state}."""
    yield from _t("one_liner", r, "one_liner")
    yield from _t("narrative", r, "narrative")
    for i, c in enumerate(r.get("changes") or []):
        for f in ("what", "so_what"):
            yield from _t(f"changes.{i}.{f}", c, f)
    st = r.get("state") or {}
    pr = st.get("profile") or {}
    for f in PROFILE:
        yield from _t(f"profile.{f}", pr, f)
    for f in ("key_drivers", "key_risks"):
        for i in range(len(pr.get(f) or [])):
            yield from _t(f"profile.{f}.{i}", pr[f], i)
    for a in st.get("assumptions") or []:
        for f in ASSUMPTION:
            yield from _t(f"a.{a.get('id')}.{f}", a, f)
    for i, m in enumerate(st.get("monitor") or []):
        for f in MONITOR:
            yield from _t(f"m.{i}.{f}", m, f)
    for f in ("implication", "consensus_gap"):
        yield from _t(f"valuation.{f}", st.get("valuation") or {}, f)


def flatten(r: dict) -> dict[str, str]:
    return {k: c[f] for k, c, f in targets(r)}


def localize(r: dict, items: dict[str, str] | None) -> dict:
    """A copy of r with translated text swapped in; anything without a translation stays English."""
    out = copy.deepcopy(r)
    if items:
        for k, c, f in targets(out):
            if items.get(k):
                c[f] = items[k]
    return out
