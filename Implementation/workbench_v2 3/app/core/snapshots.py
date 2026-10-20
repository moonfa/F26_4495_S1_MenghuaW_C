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


def referenced_ids(conn):
    """Ids of data records that a saved analysis or comparison points to. Those must stay: they reproduce the result."""
    ids = set()
    for kind, raw in conn.execute("SELECT kind,payload FROM valuations WHERE kind IN ('analysis','comparison')"):
        try:
            p = json.loads(raw)
        except ValueError:
            continue
        if kind == "analysis" and p.get("data_id"):
            ids.add(p["data_id"])
        elif kind == "comparison":
            ids.update(p.get("data_ids") or [])
    return ids


def delete_record(conn, ident):
    """The user deletes one record. An imported-data record that a saved result still uses is refused ('in_use')."""
    row = conn.execute("SELECT kind FROM valuations WHERE id=?", (ident,)).fetchone()
    if not row:
        return "missing"
    if row[0] == "data" and ident in referenced_ids(conn):
        return "in_use"
    conn.execute("DELETE FROM valuations WHERE id=?", (ident,))
    return "deleted"


def prune_data(conn, ticker, keep_latest=True):
    """Remove imported data for a ticker that nothing uses (no saved analysis or comparison points to it). The newest import is kept."""
    ids = [r[0] for r in conn.execute("SELECT id FROM valuations WHERE ticker=? AND kind='data' ORDER BY rowid DESC", (ticker.upper(),))]
    if keep_latest:
        ids = ids[1:]
    used = referenced_ids(conn)
    gone = [i for i in ids if i not in used]
    for i in gone:
        conn.execute("DELETE FROM valuations WHERE id=?", (i,))
    return len(gone)
