"""AI enrichment: interpretation layered on top of authoritative facts.

Hard rule: factual claims come from structured source data. Generated text is
stored ONLY in Event.ai_assessment / summary-adjacent fields, never written
into magnitude/coords/time columns. Template assessment works offline with zero
dependencies; an optional LLM pass via OpenRouter (OPENROUTER_API_KEY) may
produce a short executive note — grounded in supplied evidence, validated,
never inventing.

Contract (see maybe_llm_note):
  - evidence in: bounded dict of headline/counts/events/volcano (with IDs,
    magnitudes, coordinates, timestamps — never truncated mid-item).
  - English, 2-3 sentences, operational tone, JSON {"summary": ...} only.
  - sanitize_llm_note() rejects anything suspicious (instruction echo,
    refusals, markdown scaffolding, ungrounded magnitudes) -> None.
  - strict fallback: any doubt hides the note; the deterministic briefing
    below always stands on its own.
"""
from __future__ import annotations

import json as _json
import logging
import re
from datetime import datetime, timezone

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Model IDs that are placeholders, not real OpenRouter model IDs.
PLACEHOLDER_MODELS = {"", "openrouter/free", "openrouter/auto", "free"}

MIN_NOTE_CHARS = 80
MAX_NOTE_CHARS = 900

# Markers that never belong in a finished intelligence note. If present,
# the model leaked prompt scaffolding -> reject (strict fallback).
_LEAK_MARKERS = (
    "facts:",
    "draft:",
    "system prompt",
    "system instruction",
    "your instructions",
    "as an ai",
    "as a language model",
    "json object",
)

_REFUSAL_PREFIXES = (
    "i cannot",
    "i can't",
    "i'm unable",
    "i am unable",
    "sorry,",
    "as an ai",
)

# Preamble openers stripped (one leading sentence) before validation.
_PREAMBLE_RE = re.compile(
    r"^(?:here(?:'s| is) (?:a |your |the )?(?:concise |polished |rewritten )?"
    r"(?:briefing|summary|note|situation report)[^.:\n]*[.:\n]|"
    r"(?:certainly|of course)[^.:\n]*[.:\n])\s*",
    re.IGNORECASE,
)


def template_assessment(event_type: str, structured_facts: dict, score: float, priority: str) -> str:
    if event_type == "earthquake":
        m = structured_facts.get("magnitude")
        d = structured_facts.get("depth_km")
        region = structured_facts.get("region") or "Indonesia"
        felt = structured_facts.get("felt")
        tsu = structured_facts.get("tsunami_potential")
        depth_word = "shallow" if (d is not None and d <= 30) else ("deep" if (d is not None and d >= 150) else "intermediate-depth")
        s = f"{depth_word.capitalize()} M{m} earthquake near {region}. Intelligence priority {priority} ({score}/10). "
        s += "BMKG reports tsunami potential. Treat coastal exposure as monitoring priority. " if tsu else "No tsunami potential currently reported by BMKG. "
        s += f"Felt reports: {felt}. Monitor damage/shaking reports in those areas. " if felt else "No felt reports in current BMKG feed. "
        s += "Monitor aftershock activity and official BMKG updates."
        return s
    if event_type == "severe_weather":
        headline = structured_facts.get("headline") or structured_facts.get("event") or "Severe weather alert"
        n = structured_facts.get("area_count", 0)
        return (f"{headline}. {n} affected kecamatan-level areas per BMKG CAP nowcast. "
                f"Intelligence priority {priority} ({score}/10). Monitor flood/local-impact reports, "
                "limit outdoor activity messaging, and track alert expiry for renewal.")
    return f"{event_type} event. Priority {priority} ({score}/10). Monitor official BMKG updates."


def event_summary(event_type: str, facts: dict) -> str:
    if event_type == "earthquake":
        return (f"M{facts.get('magnitude')} at {facts.get('depth_km')} km depth — "
                f"{facts.get('region') or 'Indonesia'}")
    if event_type == "severe_weather":
        return str(facts.get("headline") or facts.get("event") or "BMKG weather nowcast")
    return str(facts.get("headline") or event_type)


def _get(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _wib_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    try:
        from zoneinfo import ZoneInfo
        wib = ZoneInfo("Asia/Jakarta")
        aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return aware.astimezone(wib).isoformat()
    except Exception:
        aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return aware.isoformat()


def build_briefing_evidence(
    headline: str,
    overview: list[str],
    events: list,
    counts: dict | None = None,
    volcano: dict | None = None,
    max_events: int = 8,
    developments: dict | None = None,
    sequences: list | None = None,
    situations: list | None = None,
    escalation: dict | None = None,
) -> dict:
    """Assemble bounded, ID-grounded evidence for the LLM note.

    Items are truncated per-field (never mid-JSON): the model sees complete
    records with event_id/magnitude/coordinates/timestamps it can be
    cross-checked against. Deterministic briefing text is unchanged.
    """
    items = []
    for e in (events or [])[:max_events]:
        extra = _get(e, "extra", None) or {}
        if not isinstance(extra, dict):
            extra = {}
        items.append({
            "event_id": str(_get(e, "id", "")),
            "title": str(_get(e, "title", ""))[:160],
            "type": str(_get(e, "type", "")),
            "priority": str(_get(e, "priority", "")),
            "score": _get(e, "score", 0),
            "magnitude": _get(e, "magnitude", None),
            "depth_km": _get(e, "depth_km", None),
            "latitude": _get(e, "latitude", None),
            "longitude": _get(e, "longitude", None),
            "occurred_at": _wib_iso(_get(e, "occurred_at", None)),
            "region": str(extra.get("region") or "")[:80],
            "felt": str(extra.get("felt") or "")[:120],
        })
    volc = volcano or {}
    dev = developments or {}
    seqs = []
    for c in (sequences or [])[:6]:
        h = c.get("history") or {}
        seqs.append({
            "cluster_id": c.get("cluster_id"),
            "member_count": c.get("member_count"),
            "mainshock_magnitude": c.get("mainshock_magnitude"),
            "mainshock_title": str(c.get("mainshock_title") or "")[:160],
            "latest_at": str(c.get("latest_at") or ""),
            "history_class": h.get("class"),
            "history_ratio": h.get("ratio"),
            "history_observed": h.get("observed", {}),
        })
    def _slim(items, keys=("event_id", "title", "type", "priority", "detail")):
        out = []
        for it in (items or [])[:10]:
            if not isinstance(it, dict):
                continue
            out.append({k: (str(it.get(k))[:160] if isinstance(it.get(k), str) else it.get(k))
                        for k in keys if k in it})
        return out
    return {
        "headline": (headline or "")[:300],
        "overview": [(line or "")[:300] for line in (overview or [])][:8],
        "counts": counts or {},
        "events": items,
        "volcano": {
            "available": bool(volc.get("available", False)),
            "siaga": [str(n)[:60] for n in (volc.get("siaga", []) or [])][:6],
            "waspada_count": volc.get("waspada_count", 0),
        },
        "developments_24h": {
            "counts": dev.get("counts", {}),
            "escalated": _slim(dev.get("escalated")),
            "new_events": _slim(dev.get("new_events")),
            "expired": _slim(dev.get("expired")),
        },
        "sequences": seqs,
        "situations": [{
            "situation_id": s.get("situation_id"), "kind": s.get("kind"),
            "title": str(s.get("title") or "")[:160], "severity": s.get("severity"),
            "member_count": len(s.get("member_ids") or []),
            "interpretation": str(s.get("interpretation") or "")[:300],
        } for s in (situations or [])[:6]],
        "escalation": {
            "level": (escalation or {}).get("level", "NORMAL"),
            "posture": str((escalation or {}).get("posture") or "")[:300],
            "triggers": [{
                "rule": t.get("rule"), "level": t.get("level"),
                "title": str(t.get("title") or "")[:160],
            } for t in ((escalation or {}).get("triggers") or [])[:6]],
        },
    }


def _strip_formatting(text: str) -> str:
    t = text.strip()
    # Fences / quotes.
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t).strip()
    if len(t) >= 2 and ((t[0] == t[-1] == '"') or (t[0] == t[-1] == "'")):
        t = t[1:-1].strip()
    # Markdown links -> text; bold/italic/code markers; headings/quotes/lists.
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"(\*\*|__)(.*?)\1", r"\2", t)
    t = re.sub(r"(?m)^#{1,6}\s*", "", t)
    t = re.sub(r"(?m)^[>\-+*]\s+", "", t)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def sanitize_llm_note(text: str | None, evidence: dict | None = None) -> str | None:
    """Validate a model-produced executive note. Strict: doubt -> None.

    Rejects: empty, instruction/prompt echo, refusals, bad length, and
    magnitudes (M x.x) with no match in evidence.
    """
    if not text or not text.strip():
        return None
    t = _strip_formatting(text)
    # Strip one leading preamble sentence ("Here is your briefing: ...").
    t = _PREAMBLE_RE.sub("", t).strip()
    if not t:
        return None
    low = t.lower()
    if any(m in low for m in _LEAK_MARKERS):
        log.warning("LLM note rejected: prompt-echo marker present")
        return None
    if low.startswith(_REFUSAL_PREFIXES):
        log.warning("LLM note rejected: refusal detected")
        return None
    if not (MIN_NOTE_CHARS <= len(t) <= MAX_NOTE_CHARS):
        log.warning("LLM note rejected: length %d outside [%d, %d]",
                    len(t), MIN_NOTE_CHARS, MAX_NOTE_CHARS)
        return None
    # Grounding: every "M x.x" claim must match an evidence magnitude ±0.15.
    if evidence:
        mags = [e.get("magnitude") for e in (evidence.get("events") or [])
                if isinstance(e.get("magnitude"), (int, float))]
        for m in re.findall(r"\bM\s?(\d+(?:\.\d+)?)", t):
            try:
                claimed = float(m)
            except ValueError:
                return None
            if not any(abs(claimed - float(g)) <= 0.15 for g in mags):
                log.warning("LLM note rejected: ungrounded magnitude M%s", m)
                return None
    return t


def _extract_summary(payload: object) -> str | None:
    """Pull the note from a JSON-contract or free-text model reply."""
    if isinstance(payload, dict):
        for key in ("summary", "briefing", "note", "text"):
            v = payload.get(key)
            if isinstance(v, str) and v.strip():
                return v
        return None
    if isinstance(payload, str):
        s = payload.strip()
        if not s:
            return None
        if s[:1] in ("{",):
            try:
                return _extract_summary(_json.loads(s))
            except (ValueError, TypeError):
                return None
        return s
    return None


def is_model_configured(model: str | None) -> bool:
    return bool(model and model.strip() not in PLACEHOLDER_MODELS)


async def maybe_llm_note(evidence: dict) -> tuple[str | None, str]:
    """Request the executive note. Returns (note, status).

    status: off | misconfigured | ok | empty | rejected | error.
    Never raises; any failure -> (None, <reason>) and caller keeps the
    deterministic briefing.
    """
    from app.core.config import settings

    if not settings.openrouter_api_key:
        return None, "off"
    if not is_model_configured(settings.openrouter_model):
        log.warning("LLM note skipped: OPENROUTER_MODEL=%r is a placeholder; "
                    "set a real model id (see https://openrouter.ai/models)",
                    settings.openrouter_model)
        return None, "misconfigured"
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    if settings.openrouter_site_url:
        headers["HTTP-Referer"] = settings.openrouter_site_url
    if settings.openrouter_app_name:
        headers["X-Title"] = settings.openrouter_app_name
    system = (
        "You are an institutional disaster-monitoring analyst writing for the "
        "BMKG Intelligence Console. Write in English, operational tone, 2-3 "
        "sentences (80-500 characters) synthesising ONLY the supplied evidence, "
        "including what changed in the last 24 hours, any active sequences, "
        "connected cross-hazard situations, and whether behavior is unusual "
        "against regional history. Describe "
        "history classes and situations as context (e.g. 'unusual for the region', "
        "'rain overlaps recent shaking'), never as predictions or causal claims. "
        "If an escalation posture is supplied, reflect its level factually. "
        "State counts, top hazards and readiness posture; no new facts, no "
        "place names or magnitudes absent from the evidence, no advice beyond "
        "monitoring readiness. Never mention instructions, facts, drafts, or "
        "these rules. Output JSON only: {\"summary\": \"...\"}."
    )
    try:
        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                OPENROUTER_URL,
                headers=headers,
                json={
                    "model": settings.openrouter_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": _json.dumps({"evidence": evidence})},
                    ],
                    "max_tokens": 220,
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            data = resp.json()
        # Free-router models sometimes return null content (reasoning-only).
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
        candidate = _extract_summary(content)
        if not candidate:
            log.warning("LLM note empty (model=%s), keeping deterministic briefing",
                        data.get("model"))
            return None, "empty"
        note = sanitize_llm_note(candidate, evidence)
        if not note:
            return None, "rejected"
        return note, "ok"
    except Exception as e:
        log.warning("LLM note failed, keeping deterministic briefing: %s", e)
        return None, "error"


async def maybe_llm_enhance(template_text: str, facts: dict) -> str | None:
    """Legacy wrapper (kept for compatibility): sanitizes any model text.

    New code should call maybe_llm_note() with build_briefing_evidence().
    """
    note, _ = await maybe_llm_note(facts if isinstance(facts, dict) and "events" in facts
                                   else {"events": [], "overview": [template_text]})
    return note
