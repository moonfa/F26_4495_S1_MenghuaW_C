"""Price-discipline status for a position plan. Pure Python. Long positions only."""
from __future__ import annotations

NEAR = 0.03          # within 3% counts as "near"
ORDER = ("stop_breached", "near_stop", "over_max", "target_reached", "near_target", "buy_zone")


def sizing(value, target_amount=None, max_amount=None, weight=None) -> dict | None:
    """Position size against your own plan, in money (the stock's currency). `value` is quantity x price.
    `weight` is the broker's portfolio weight as a fraction and is shown for context only."""
    if target_amount is None and max_amount is None:
        return None
    v = value or 0.0
    return {"value": round(v), "target": target_amount, "max": max_amount,
            "room_to_target": None if target_amount is None else round(target_amount - v),
            "room_to_max": None if max_amount is None else round(max_amount - v),
            "over_max": bool(max_amount is not None and v > max_amount),
            "pct_of_portfolio": None if weight is None else round(weight * 100, 1)}


def plan_status(price, buy_below=None, target=None, stop=None, near: float = NEAR,
                value=None, target_amount=None, max_amount=None, weight=None) -> dict | None:
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
    size = sizing(value, target_amount, max_amount, weight)
    if size and size["over_max"]:
        flags.append("over_max")
    flags = [f for f in flags if f]
    flags.sort(key=ORDER.index)
    rel = lambda x: round(x / price - 1, 4) if x else None
    return {"status": flags[0] if flags else "on_plan", "flags": flags,
            "to_target": rel(target), "to_stop": rel(stop), "to_buy": rel(buy_below), "sizing": size}


