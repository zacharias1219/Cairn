"""The Cairn API: one Python service (section 9)."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cairn.api.routes import console, pap, public
from cairn.config import get_settings
from cairn.db.core import close_pools, open_pools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    await open_pools(max_size=20)
    stop = asyncio.Event()
    worker = None
    if s.run_worker:
        from cairn.jobs.worker import run_forever

        worker = asyncio.create_task(run_forever(stop))
    try:
        yield
    finally:
        stop.set()
        if worker:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await worker
        await close_pools()


app = FastAPI(title="Cairn", version="0.1.0", lifespan=lifespan,
              description="The supervised, auditable front door for a business. Every agent leaves a trail.")

_origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins if _origins != ["*"] else ["*"],
    allow_credentials=_origins != ["*"],
    allow_methods=["*"], allow_headers=["*"],
)

app.include_router(console.router)
app.include_router(public.router)
app.include_router(pap.router)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "model_mode": "claude" if get_settings().use_claude else "sandbox"}
