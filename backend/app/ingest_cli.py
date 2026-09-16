"""CLI: python -m app.ingest_cli --once"""
import argparse
import asyncio
import logging

from app.core.db import SessionLocal, init_db
from app.core.logging import setup_logging
from app.services import ingest as ingest_svc

setup_logging()
log = logging.getLogger(__name__)


async def main(once: bool):
    await init_db()
    async with SessionLocal() as session:
        if once:
            summary = await ingest_svc.run_ingest(session)
            print(summary)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    asyncio.run(main(args.once))
