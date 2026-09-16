"""Tests for the grounded LLM executive note (always mocked — no network)."""
import httpx

from app.core.config import settings
from app.services import enrichment


class _FakeResp:
    def __init__(self, payload=None):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _evidence():
    return {
        "headline": "2 high-priority events active.",
        "overview": ["2 active events tracked."],
        "counts": {"active": 2},
        "events": [
            {"event_id": "e1", "title": "M7.0 — South Java", "type": "tsunami_alert",
             "priority": "CRITICAL", "score": 9.0, "magnitude": 7.0, "depth_km": 20.0,
             "latitude": -8.0, "longitude": 110.0, "occurred_at": "2026-09-15T10:00:00+07:00",
             "region": "South Java", "felt": "III Cilacap"},
        ],
        "volcano": {"available": False, "siaga": [], "waspada_count": 0},
    }


GOOD_NOTE = ("Two high-priority events are active including a CRITICAL M7.0 tsunami-potential "
             "earthquake near South Java with shaking felt in Cilacap. Maintain coastal evacuation "
             "readiness and monitor official BMKG bulletins for updates.")


async def test_no_key_returns_off(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    note, status = await enrichment.maybe_llm_note(_evidence())
    assert (note, status) == (None, "off")


async def test_placeholder_model_returns_misconfigured(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-test")
    monkeypatch.setattr(settings, "openrouter_model", "openrouter/free")
    note, status = await enrichment.maybe_llm_note(_evidence())
    assert (note, status) == (None, "misconfigured")


async def test_success_json_contract(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-test")
    monkeypatch.setattr(settings, "openrouter_model", "meta-llama/llama-3-8b-instruct")
    calls: dict = {}

    async def fake_post(self, url, headers=None, json=None):
        calls.update(url=url, headers=headers, json=json)
        return _FakeResp({"choices": [{"message": {"content": f'{{"summary": "{GOOD_NOTE}"}}'}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    note, status = await enrichment.maybe_llm_note(_evidence())
    assert status == "ok" and note == GOOD_NOTE
    assert calls["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert calls["headers"]["Authorization"] == "Bearer sk-or-test"
    assert calls["json"]["model"] == "meta-llama/llama-3-8b-instruct"
    assert calls["json"]["response_format"] == {"type": "json_object"}
    assert calls["json"]["messages"][0]["role"] == "system"


async def test_failure_falls_back_to_error(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-test")
    monkeypatch.setattr(settings, "openrouter_model", "some/model")

    async def boom(self, *a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    assert await enrichment.maybe_llm_note(_evidence()) == (None, "error")


async def test_null_content_falls_back_to_empty(monkeypatch):
    """Free-router models sometimes return reasoning-only (null content)."""
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-test")
    monkeypatch.setattr(settings, "openrouter_model", "some/model")

    async def fake_post(self, url, headers=None, json=None):
        return _FakeResp({"model": "some-free-reasoner",
                          "choices": [{"message": {"content": None, "reasoning": "..."}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    assert await enrichment.maybe_llm_note(_evidence()) == (None, "empty")


def test_sanitize_rejects_prompt_echo():
    ev = _evidence()
    assert enrichment.sanitize_llm_note("Facts: {...} Draft: ... " + GOOD_NOTE, ev) is None
    assert enrichment.sanitize_llm_note("As an AI language model, " + GOOD_NOTE, ev) is None
    assert enrichment.sanitize_llm_note("Sorry, I cannot do that.", ev) is None
    assert enrichment.sanitize_llm_note("Too short.", ev) is None


def test_sanitize_rejects_ungrounded_magnitude():
    ev = _evidence()  # only M7.0 in evidence
    bad = ("A M9.5 earthquake struck the region with massive destruction expected. "
           "Authorities should respond immediately to this catastrophic event now.")
    assert enrichment.sanitize_llm_note(bad, ev) is None
    # Grounded magnitude passes.
    assert enrichment.sanitize_llm_note(GOOD_NOTE, ev) == GOOD_NOTE


def test_sanitize_strips_preamble_and_markdown():
    ev = _evidence()
    raw = "Here is your briefing: " + GOOD_NOTE
    assert enrichment.sanitize_llm_note(raw, ev) == GOOD_NOTE
    md = "**" + GOOD_NOTE + "**"
    assert enrichment.sanitize_llm_note(md, ev) == GOOD_NOTE


def test_build_evidence_bounds_fields():
    class E:
        id = "e1"
        title = "T" * 500
        type = "earthquake"
        priority = "HIGH"
        score = 7.0
        magnitude = 5.0
        depth_km = 10.0
        latitude = -7.0
        longitude = 110.0
        occurred_at = None
        extra = {"region": "R" * 200, "felt": "F" * 500}

    ev = enrichment.build_briefing_evidence("H" * 500, ["O" * 500], [E()])
    assert len(ev["headline"]) <= 300
    assert len(ev["events"][0]["title"]) <= 160
    assert len(ev["events"][0]["region"]) <= 80
