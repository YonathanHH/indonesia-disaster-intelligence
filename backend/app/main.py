"""FastAPI application entrypoint."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import settings
from app.core.db import SessionLocal, init_db
from app.core.logging import setup_logging
from app.services import ingest as ingest_svc

setup_logging()
log = logging.getLogger(__name__)


async def _background_loop():
    while True:
        try:
            async with SessionLocal() as session:
                summary = await ingest_svc.run_ingest(session)
                log.info("background ingest: %s", summary)
        except Exception:
            log.exception("background ingest failed")
        await asyncio.sleep(settings.ingest_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    task = asyncio.create_task(_background_loop())
    yield
    task.cancel()


app = FastAPI(title="BMKG Intelligence API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"service": "bmkgintel", "attribution": "Data: BMKG (Badan Meteorologi, Klimatologi, dan Geofisika)"}
