import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from . import config  # noqa: F401  (loads .env before anything else)
from . import security
from .api.routes import router
from .api.journal import router as journal_router
from .database import Base, engine, ensure_columns, normalize_symbols
from . import models  # noqa: F401

Base.metadata.create_all(engine)
ensure_columns()
normalize_symbols()
STATIC = Path(__file__).resolve().parent / "static"
log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # OpenBB installs signal handlers while it builds its extensions, which only works in the
    # main thread. Request handlers run in worker threads, so import it once here at startup.
    try:
        from openbb import obb  # noqa: F401
        log.info("OpenBB initialized.")
    except Exception as exc:  # keep the API up so /docs and saved data still work
        log.error("OpenBB failed to initialize at startup: %s", exc)
    yield


app = FastAPI(title="Personal Investment Workbench", version=config.APP_VERSION, lifespan=lifespan)


@app.middleware("http")
async def guard(request: Request, call_next):
    host = request.headers.get("host")
    if not security.host_ok(host):
        return JSONResponse({"detail": "Host not allowed."}, status_code=400)
    if not security.origin_ok(request.method, request.headers.get("origin"), host):
        return JSONResponse({"detail": "Cross-site request refused."}, status_code=403)
    resp = await call_next(request)
    for k, v in security.HEADERS.items():
        resp.headers[k] = v
    if request.url.path == "/":                  # the page; /docs loads its own assets from a CDN
        resp.headers["Content-Security-Policy"] = security.CSP
    return resp


app.include_router(router)
app.include_router(journal_router)


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "version": config.APP_VERSION, "ai_provider": config.AI_PROVIDER, "model": config.AI_MODEL or None}


@app.get("/")
def home():
    index = STATIC / "index.html"
    if index.exists():
        return FileResponse(index, headers={"Cache-Control": "no-store"})
    return JSONResponse({"detail": "Frontend not built yet. See /docs for the API."})
