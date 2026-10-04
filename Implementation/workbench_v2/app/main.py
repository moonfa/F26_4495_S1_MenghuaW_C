import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from . import config  # noqa: F401  (loads .env before anything else)
from .api.routes import router
from .database import Base, engine
from . import models  # noqa: F401

Base.metadata.create_all(engine)
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


app = FastAPI(title="Personal Investment Workbench", version="2.0.0", lifespan=lifespan)
app.include_router(router)


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "ai_provider": config.AI_PROVIDER, "model": config.AI_MODEL or None}


@app.get("/")
def home():
    index = STATIC / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"detail": "Frontend not built yet. See /docs for the API."})