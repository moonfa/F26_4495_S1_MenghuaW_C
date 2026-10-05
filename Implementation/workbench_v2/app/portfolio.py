"""Parse broker CSV exports (Futu layout). Pure Python, no I/O."""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = {"美东": "America/New_York", "香港": "Asia/Hong_Kong", "新加坡": "Asia/Singapore"}
FILLED = {"全部成交", "部成已撤"}          # fully filled, or partly filled then cancelled
CASH_WORDS = ("货币", "money market", "现金", "cash")
ETF_WORDS = ("etf", "etn", "基金", "fund", "trust", "信托", "指数", "index")


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "gbk", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def _table(text: str) -> tuple[list[str], list[list[str]]]:
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return [], []
    delim = "\t" if "\t" in lines[0] else ","
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim))
    return [h.strip() for h in rows[0]], rows[1:]


def _idx(header: list[str], name: str, last: bool = False) -> int:
    hits = [i for i, h in enumerate(header) if h == name]
    if not hits:
        raise ValueError(f"Missing column: {name}")
    return hits[-1] if last else hits[0]


def _num(s) -> float | None:
    try:
        return float(str(s or "").replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def _cell(row: list[str], i: int) -> str:
    return row[i].strip() if i < len(row) else ""


def symbol_of(code: str, currency: str | None = None) -> str:
    code = code.strip().upper()
    if code.isdigit():
        return f"{int(code):04d}.HK"
    return f"{code}.SI" if currency == "SGD" else code


def currency_of(code: str) -> str:
    return "HKD" if code.strip().isdigit() else "USD"      # SGD etc. are not inferred


def kind_of(name: str) -> str:
    n = name.lower()
    return "cash" if any(w in n for w in CASH_WORDS) else "etf" if any(w in n for w in ETF_WORDS) else "stock"


def parse_time(s: str) -> str | None:
    s = s.strip()
    tz = ZoneInfo("UTC")
    if "(" in s:
        s, label = s.split("(", 1)
        tz = ZoneInfo(TZ.get(label.strip(" )"), "UTC"))
    try:
        return datetime.strptime(s.strip(), "%Y/%m/%d %H:%M:%S").replace(tzinfo=tz).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def parse_holdings(text: str) -> list[dict]:
    h, rows = _table(text)
    c = {k: _idx(h, k) for k in ("代码", "名称", "现价", "摊薄成本价", "持仓盈亏", "盈亏比例", "持有数量", "市值", "持仓占比")}
    cur_i = h.index("币种") if "币种" in h else None
    out = []
    for r in rows:
        code = _cell(r, c["代码"])
        qty = _num(_cell(r, c["持有数量"]))
        cur = (_cell(r, cur_i).upper() if cur_i is not None else "") or currency_of(code)
        if not code or qty is None:
            continue
        name = _cell(r, c["名称"])
        pct = lambda k: (v / 100 if (v := _num(_cell(r, c[k]))) is not None else None)
        out.append({"code": code, "symbol": symbol_of(code, cur), "name": name, "quantity": qty,
                    "price": _num(_cell(r, c["现价"])), "cost": _num(_cell(r, c["摊薄成本价"])),
                    "pnl": _num(_cell(r, c["持仓盈亏"])), "pnl_pct": pct("盈亏比例"),
                    "market_value": _num(_cell(r, c["市值"])), "weight": pct("持仓占比"),
                    "currency": cur, "kind": kind_of(name)})
    return out


def parse_trades(text: str) -> list[dict]:
    """Only filled quantity counts; unfilled and cancelled orders are skipped."""
    h, rows = _table(text)
    c = {k: _idx(h, k) for k in ("方向", "代码", "名称", "交易状态", "成交数量", "成交价格", "成交金额", "成交时间", "合计费用")}
    cur, mkt = _idx(h, "币种", last=True), _idx(h, "市场", last=True)
    out = []
    for r in rows:
        qty = _num(_cell(r, c["成交数量"]))
        if _cell(r, c["交易状态"]) not in FILLED or not qty:
            continue
        side = "buy" if _cell(r, c["方向"]) == "买入" else "sell"
        code, price, when = _cell(r, c["代码"]), _num(_cell(r, c["成交价格"])), parse_time(_cell(r, c["成交时间"]))
        if not code or price is None or not when:
            continue
        ccy = (_cell(r, cur) or currency_of(code)).upper()
        out.append({"code": code, "symbol": symbol_of(code, ccy), "name": _cell(r, c["名称"]), "side": side, "quantity": qty,
                    "price": price, "amount": _num(_cell(r, c["成交金额"])), "fee": _num(_cell(r, c["合计费用"])) or 0.0,
                    "currency": ccy, "market": _cell(r, mkt), "executed_at": when,
                    "key": hashlib.sha1(f"{when}|{code}|{side}|{qty}|{price}".encode()).hexdigest()})
    return out
