"""Price-discipline status for a position plan. Pure Python. Long positions only."""
from __future__ import annotations

NEAR = 0.03          # within 3% counts as "near"
ORDER = ("stop_breached", "near_stop", "target_reached", "near_target", "buy_zone")


def plan_status(price, buy_below=None, target=None, stop=None, near: float = NEAR) -> dict | None:
    """Most important flag first. Distances are relative to the current price."""
    if not price or price <= 0:
        return None
    flags = []
    if stop:
        flags.append("stop_breached" if price <= stop else "near_stop" if price <= stop * (1 + near) else None)
    if target:
        flags.append("target_reached" if price >= target else "near_target" if price >= target * (1 - near) else None)
    if buy_below and price <= buy_below:
        flags.append("buy_zone")
    flags = [f for f in flags if f]
    flags.sort(key=ORDER.index)
    rel = lambda x: round(x / price - 1, 4) if x else None
    return {"status": flags[0] if flags else "on_plan", "flags": flags,
            "to_target": rel(target), "to_stop": rel(stop), "to_buy": rel(buy_below)}
