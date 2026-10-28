"""Valuation storage, physically separate from research and Plan. Records are never edited; the user may delete one.
An import that no saved result uses is replaced when the same ticker is imported again."""
from pathlib import Path
from datetime import datetime, timezone
import json, sqlite3, uuid, re, shutil
from contextlib import contextmanager
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from ..core.valuation import Assumptions, EbitdaAssumptions, PfcfAssumptions, calculate, consensus_bridge
from ..adapters.valuation_adapter import fetch
from ..adapters.valuation_references import SCHEMA
from ..core.compare import compare as compare_rows
from ..core.diagnosis import diagnose
from ..core.snapshots import history_rows, delete_record, prune_data
from ..core.valuation import FORMULA
from ..core.period_table import table_of
from ..core.valuation_link import estimate_changes, estimate_text

ROOT=Path(__file__).resolve().parents[2]
DB=ROOT/"valuation.db"
router=APIRouter()
VALUATION_API=8   # bump when request/response shapes change; the page checks it against /api/v1/health

SCHEMA_VERSION=4   # PRAGMA user_version of valuation.db: 4 = valuation-v4 records only

def _is_v4(kind,payload):
    if kind=="data": return payload.get("schema_version")==SCHEMA
    if kind=="analysis": return (payload.get("result") or {}).get("formula_version")==FORMULA
    if kind=="comparison": return all(m.get("exit_fy") for r in (payload.get("result") or {}).get("rows",[]) for m in r.get("methods",[]))
    return False

def migrate(c):
    """Upgrade from the 2.28 valuation model: back the file up once as valuation.v3.bak.db, then drop records the new model cannot read.
    The workbench database (reviews, notes, assumption links) is a different file and is never touched."""
    if c.execute("PRAGMA user_version").fetchone()[0]>=SCHEMA_VERSION: return
    rows=c.execute("SELECT id,kind,payload FROM valuations").fetchall()
    if rows:
        c.commit()
        bak=DB.with_name("valuation.v3.bak.db")
        if not bak.exists(): shutil.copyfile(DB,bak)
        old=[r[0] for r in rows if not _is_v4(r[1],json.loads(r[2]))]
        c.executemany("DELETE FROM valuations WHERE id=?",[(i,) for i in old])
    c.execute("PRAGMA user_version=%d"%SCHEMA_VERSION)
    c.commit()

@contextmanager
def connect():
    c=sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS valuations (id TEXT PRIMARY KEY, ticker TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
    migrate(c)
    try:
        with c:
            yield c
    finally:
        c.close()

def save(ticker,kind,payload):
    ident=str(uuid.uuid4()); now=datetime.now(timezone.utc).isoformat()
    with connect() as c:
        c.execute("INSERT INTO valuations VALUES (?,?,?,?,?)",(ident,ticker,kind,now,json.dumps(payload,allow_nan=False)))
    return dict(id=ident,ticker=ticker,kind=kind,created_at=now,payload=payload)

def read(ident,hydrate=False):
    with connect() as c: row=c.execute("SELECT id,ticker,kind,created_at,payload FROM valuations WHERE id=?",(ident,)).fetchone()
    if not row: raise HTTPException(404,"Snapshot not found")
    rec=dict(id=row[0],ticker=row[1],kind=row[2],created_at=row[3],payload=json.loads(row[4]))
    if hydrate: hydrated(rec)
    return rec

def hydrated(rec):
    """Analyses store only data_id; attach the data snapshot for display. Older rows that embedded a copy keep working."""
    p=rec["payload"]
    if rec["kind"]=="analysis" and "data" not in p:
        p["data"]=read(p["data_id"])["payload"]
    return rec

@router.get("/valuation")
def page(): return FileResponse(ROOT/"app/static/valuation.html",headers={"Cache-Control":"no-store"})

def estimate_notice(ticker):
    """Returns a function: given a new data payload, one factual line on how the analysts' numbers moved since the newest saved analysis, or None.
    Nothing is overwritten; the saved analysis keeps the estimates it used."""
    with connect() as c:
        row=c.execute("SELECT payload FROM valuations WHERE ticker=? AND kind='analysis' ORDER BY rowid DESC LIMIT 1",(ticker,)).fetchone()
    used=(json.loads(row[0]).get("result") or {}).get("estimates_used") if row else None
    return lambda payload: (estimate_text(estimate_changes(used,table_of(payload))) if used else None)

class FetchRequest(BaseModel):
    peers: list[str] = Field(default_factory=list,max_length=5)
    industry: bool = False

@router.post("/api/v1/valuation/{ticker}/fetch")
def load(ticker: str, req: FetchRequest | None = None):
    ticker=ticker.strip().upper()
    if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=-]{0,19}",ticker): raise HTTPException(422,"Invalid ticker")
    peers=[s.strip().upper() for s in (req.peers if req else [])]
    if any(not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=-]{0,19}",s) for s in peers): raise HTTPException(422,"Invalid peer ticker")
    notice=estimate_notice(ticker)
    rec=save(ticker,"data",fetch(ticker,peer_symbols=list(dict.fromkeys(peers)),industry=bool(req and req.industry)))
    notice=notice(rec["payload"])
    with connect() as c: prune_data(c,ticker)      # earlier imports that no saved result uses are replaced by this one
    return dict(rec,estimate_notice=notice)

@router.get("/api/v1/valuation/{ticker}/history")
def history(ticker: str):
    with connect() as c: return history_rows(c,ticker,50)

@router.delete("/api/v1/valuation/snapshots/{ident}")
def delete_snapshot(ident: str):
    with connect() as c: r=delete_record(c,ident)
    if r=="missing": raise HTTPException(404,"Snapshot not found")
    if r=="in_use": raise HTTPException(409,"Saved analyses or comparisons still use this imported data. Delete those first.")
    return dict(deleted=ident)

@router.post("/api/v1/valuation/{ticker}/cleanup")
def cleanup(ticker: str):
    with connect() as c: return dict(removed=prune_data(c,ticker))

@router.get("/api/v1/valuation/snapshots/{ident}")
def snapshot(ident: str): return read(ident,hydrate=True)

class ReferenceAssumptions(BaseModel):
    model_config=ConfigDict(allow_inf_nan=False,extra="forbid")
    pe: float=Field(gt=0,le=500)
    spread: float=Field(ge=0,lt=1)

class Request(BaseModel):
    model_config=ConfigDict(extra="forbid")
    data_id: str
    assumptions: Assumptions | EbitdaAssumptions | PfcfAssumptions
    reference: ReferenceAssumptions | None = None
    persist: bool = True   # False = live preview while editing: nothing is written

@router.post("/api/v1/valuation/calculate")
def compute(req: Request):
    data=read(req.data_id)
    if data["kind"]!="data": raise HTTPException(422,"Select a data snapshot")
    try: result=calculate(data["payload"],req.assumptions)
    except (ValueError,OverflowError) as e: raise HTTPException(422,str(e))
    try: result["diagnosis"]=diagnose(data["payload"],req.assumptions,result)
    except (ValueError,OverflowError,KeyError,TypeError,ZeroDivisionError) as e: result["diagnosis"]=None   # the read-this-first block is advice; it never blocks the calculation
    comparison=consensus_bridge(data["payload"],req.reference.pe,req.reference.spread) if req.reference else None
    payload=dict(data_id=req.data_id,result=result,market_comparison=comparison)
    if not req.persist: return hydrated(dict(id=None,ticker=data["ticker"],kind="analysis",created_at=None,payload=payload))
    return hydrated(save(data["ticker"],"analysis",payload))


class BridgeRequest(BaseModel):
    model_config=ConfigDict(allow_inf_nan=False,extra='forbid')
    data_id: str
    pe: float = Field(gt=0,le=500)
    spread: float = Field(ge=0,lt=1)

@router.post('/api/v1/valuation/reference-prices')
def bridge(req: BridgeRequest):
    snapshot=read(req.data_id)
    if snapshot['kind']!='data': raise HTTPException(422,'Select a data snapshot')
    return consensus_bridge(snapshot['payload'],req.pe,req.spread)




TICKER=re.compile(r"[A-Z0-9^][A-Z0-9.^=-]{0,19}")

def latest_data(ticker,hours):
    """Most recent saved data snapshot for the ticker that is younger than `hours`, else None."""
    if hours<=0: return None
    with connect() as c:
        row=c.execute("SELECT id,created_at FROM valuations WHERE ticker=? AND kind='data' ORDER BY rowid DESC LIMIT 1",(ticker,)).fetchone()
    if not row: return None
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(row[1])).total_seconds()/3600
    if age>hours: return None
    rec=read(row[0])
    return rec if rec['payload'].get('schema_version')==SCHEMA else None   # an older snapshot lacks the fields the current rules need

class CompareRequest(BaseModel):
    model_config=ConfigDict(allow_inf_nan=False,extra="forbid")
    tickers: list[str] = Field(min_length=2,max_length=5)
    years: float = Field(default=3,ge=0.5,le=10)
    required_return: float | None = Field(default=None,gt=-1,le=1)
    multiple_shift: float = Field(default=0,gt=-.9,le=2)
    reuse_hours: float = Field(default=6,ge=0,le=72)
    fade_to: float | None = Field(default=None,gt=-1,le=2)
    include_industry: bool = False

@router.post("/api/v1/valuation/compare")
def compare(req: CompareRequest):
    tickers=list(dict.fromkeys(t.strip().upper() for t in req.tickers))
    if len(tickers)<2 or any(not TICKER.fullmatch(t) for t in tickers): raise HTTPException(422,"Give 2–5 valid, distinct tickers")
    snaps,errors=[],{}
    for t in tickers:
        try:
            cached=latest_data(t,req.reuse_hours)
            if cached and req.include_industry and not cached["payload"].get("industry_ref"): cached=None
            snaps.append(cached or save(t,"data",fetch(t,industry=req.include_industry)))
        except Exception as e: errors[t]=str(e)[:200]
    result=compare_rows([x["payload"] for x in snaps],req.years,req.required_return,req.multiple_shift,req.fade_to)
    for t,msg in errors.items(): result["rows"].append(dict(ticker=t,methods=[],skipped=[dict(method="all",reason="data import failed: "+msg)],flags=[]))
    for row in result["rows"]:
        snap=next((x for x in snaps if x["ticker"]==row["ticker"]),None)
        row["data_id"]=snap["id"] if snap else None
    return save("+".join(tickers),"comparison",dict(data_ids=[x["id"] for x in snaps],result=result))
