from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.models import Briefing, JobState


async def test_new_tables_exist(session):
    session.add(JobState(key="ingest"))
    session.add(
        Briefing(
            kind="daily",
            generated_at=datetime.now(timezone.utc),
            based_on_ingest_at=None,
            payload={"headline": "x"},
            llm_status="ok",
            llm_model="openrouter/free",
            created_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
    row = (await session.execute(select(Briefing))).scalar_one()
    assert row.payload == {"headline": "x"}
    assert row.kind == "daily"


def test_new_settings_defaults():
    assert settings.brief_min_rebuild_seconds == 900
    assert settings.cron_secret == ""
    assert settings.allowed_origins == ""
    assert settings.operator_secret == ""
    assert settings.cors_origins == []
