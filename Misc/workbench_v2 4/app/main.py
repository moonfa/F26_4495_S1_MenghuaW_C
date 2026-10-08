import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from . import config  # noqa: F401  (loads .env before anything else)
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
