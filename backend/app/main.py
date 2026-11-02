"""FastAPI application entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import jobs
from app.api.routes import router
from app.core.config import settings
from app.core.db import init_db
from app.core.logging import setup_logging

setup_logging()
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # No resident ingest loop: a serverless invocation is not a process that can
    # host `while True`. Collection is driven by the crons in vercel.json and by
    # the claim-guarded POST /ingest/run on dashboard load.
    await init_db()
    yield


app = FastAPI(title="BMKG Intelligence API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"service": "bmkgintel", "attribution": "Data: BMKG (Badan Meteorologi, Klimatologi, dan Geofisika)"}
