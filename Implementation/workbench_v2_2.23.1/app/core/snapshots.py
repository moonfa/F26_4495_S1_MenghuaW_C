"""One-line descriptions of saved valuation records, so the snapshot list says what each one is.

Pure SQLite, no web framework. It only reads; it never changes a record."""
import json

KIND_LABEL = {"data": "Imported data", "analysis": "Saved analysis", "comparison": "Saved comparison"}
METHOD_LABEL = {"pe": "P/E", "p_fcf": "P/FCF", "ev_ebitda": "EV/EBITDA"}


def _summary(kind, ticker, payload):
    """Short facts for the list. `payload` is the parsed record; every field is optional (older records differ)."""
    try:
        if kind == "data":
            q = payload.get("quote") or {}
            return dict(price=q.get("value"), currency=q.get("currency"))
        if kind == "analysis":
            res = payload.get("result") or {}
            a = res.get("assumptions") or {}
            base = next((s for s in res.get("scenarios") or [] if s.get("scenario") == "Base"), None)
            return dict(method=METHOD_LABEL.get(a.get("method") or res.get("method") or "pe", "P/E"),
                        base=base and base.get("price_cagr"), years=a.get("years"), required=a.get("required_return"))
        if kind == "comparison":
            return dict(tickers=ticker)
    except (AttributeError, TypeError):
        pass
    return {}


def history_rows(conn, ticker, limit=50):
    """Newest first. Parses each record in Python so an older record with a different shape cannot break the list."""
    rows = conn.execute("SELECT id,kind,created_at,payload FROM valuations WHERE ticker=? ORDER BY rowid DESC LIMIT ?", (ticker.upper(), limit)).fetchall()
    out = []
    for ident, kind, created, raw in rows:
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {}
        out.append(dict(id=ident, kind=kind, created_at=created, label=KIND_LABEL.get(kind, kind), summary=_summary(kind, ticker, payload)))
    return out
