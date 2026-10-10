"""Personal advice and reading the "what do you do" box, written by an AI
model (Google Gemini by default, or Claude on Amazon Bedrock), and read aloud
by Amazon Polly.

The model only rephrases. Every rule decision, stage and time window comes
from the plan, which the page shows unchanged next to the advice. If the
model is not set up, fails or declines, the page simply shows no advice and
the work box falls back to keywords.

AI_PROVIDER picks the model: "gemini", "bedrock" or "off". Gemini's API key
is read from Parameter Store (GEMINI_KEY_PARAM, a SecureString) or, for
local runs, GEMINI_API_KEY. It is never logged.
"""
import base64
import hashlib
import json
import logging
import os
import time

import requests

from . import settings

log = logging.getLogger(__name__)

_PROMPTS = settings.load("prompts")
LANGUAGES = _PROMPTS["languages"]
SYSTEM = _PROMPTS["advice_system"]
HEADINGS = _PROMPTS["advice_headings"]

_client = None


LABELS = {"gemini": "Google Gemini", "bedrock": "Claude on Amazon Bedrock"}


def provider():
    """"gemini", "bedrock" or None (off)."""
    chosen = str(settings.get("ai_provider")).strip().lower()
    if chosen in ("gemini", "bedrock"):
        return chosen
    if chosen == "off":
        return None
    return "bedrock" if os.environ.get("BEDROCK_MODEL") else None


def label():
    return LABELS.get(provider(), "AI")


_key_cache = {"at": -1e9, "value": None}


def _gemini_key(ssm=None, now=None):
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    name = os.environ.get("GEMINI_KEY_PARAM")
    if not name:
        return None
    now = now if now is not None else time.time()
    if ssm is None and now - _key_cache["at"] < settings.get("ai_key_cache_seconds"):
        return _key_cache["value"]
    try:
        if ssm is None:
            import boto3

            ssm = boto3.client("ssm")
        value = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"].strip() or None
    except Exception as exc:  # not created yet, or no permission
        log.warning("gemini key not available: %s", type(exc).__name__)
        value = None
    _key_cache.update(at=now, value=value)
    return value


def enabled():
    chosen = provider()
    if chosen == "bedrock":
        return bool(os.environ.get("BEDROCK_MODEL"))
    if chosen == "gemini":
        return bool(_gemini_key())
    return False


def gemini(system, user, max_tokens=4096, schema=None, session=None):
    """Text from Gemini, or None on any failure or block."""
    key = _gemini_key()
    if not key:
        return None
    config = {"maxOutputTokens": max_tokens, "temperature": 0.4}
    if schema:
        config.update(responseMimeType="application/json", responseSchema=schema)
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": config,
    }
    url = settings.get("gemini_url").format(model=settings.get("gemini_model"))
    try:
        resp = (session or requests).post(url, json=body, headers={"x-goog-api-key": key},
                                          timeout=settings.get("ai_timeout_seconds"))
    except requests.RequestException as exc:
        log.warning("gemini unreachable: %s", type(exc).__name__)
        return None
    if resp.status_code != 200:
        log.warning("gemini returned %s: %s", resp.status_code, resp.text[:300])
        return None
    candidates = resp.json().get("candidates") or []
    if not candidates or candidates[0].get("finishReason") not in (None, "STOP"):
        log.warning("gemini gave no answer: %s", candidates[0].get("finishReason") if candidates else "blocked")
        return None
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    return text or None


def _bedrock():
    global _client
    if _client is None:
        from anthropic import AnthropicBedrockMantle

        _client = AnthropicBedrockMantle(
            aws_region=settings.get("bedrock_region") or os.environ.get("AWS_REGION"),
            timeout=float(settings.get("ai_timeout_seconds")),
            max_retries=1,
        )
    return _client


def plan_facts(plan):
    """The small, decision-level slice of the plan Claude is allowed to use."""
    return {
        "who": plan["persona"]["label"],
        "area": plan["area"]["name"],
        "date": plan["date"],
        "grap_stage": plan["stage"]["headline"]["title"],
        "stage_source": plan["stage"]["source"],
        "verdict": plan["verdict_label"],
        "day_aqi_category": plan.get("air", {}).get("category"),
        "best_time": (
            {"what": plan["best_window_title"], "from": plan["best_window"]["start"],
             "to": plan["best_window"]["end"], "aqi": plan["best_window"]["avg_aqi"]}
            if plan["best_window"] else None
        ),
        "rules": [
            {"activity": a["label"], "decision": a["rule"]["label"]}
            for a in plan["activities"] if a["rule"]
        ],
        "breath_dose_vs_clean_air": plan["dose"]["ratio"],
        "main_pollutant": plan.get("dominant"),
        "commute": plan.get("commute"),
        "actions": plan.get("actions", []),
        "profile": plan.get("profile"),
        "stale_forecast": plan["is_stale"],
    }


def cache_key(plan, lang):
    facts = json.dumps(plan_facts(plan), sort_keys=True, ensure_ascii=False)
    return "AI#" + hashlib.sha256(f"{lang}|{facts}".encode()).hexdigest()


def summarize(plan, lang="en", client=None, session=None):
    """Two-sentence summary, or None when it cannot be produced."""
    if lang not in LANGUAGES:
        raise ValueError("lang must be en or hi")
    system = SYSTEM.format(language=LANGUAGES[lang], headings=", ".join(HEADINGS[lang]))
    facts = json.dumps(plan_facts(plan), ensure_ascii=False)
    if client is None and provider() == "gemini":
        return gemini(system, facts, session=session)
    import anthropic

    client = client or _bedrock()
    try:
        message = client.messages.create(
            model=settings.get("bedrock_model"),
            max_tokens=2000,
            output_config={"effort": "low"},
            system=system,
            messages=[{"role": "user", "content": facts}],
        )
    except anthropic.RateLimitError:
        log.warning("bedrock rate limited")
        return None
    except anthropic.APIStatusError as exc:
        log.warning("bedrock returned %s: %s", exc.status_code, exc.message)
        return None
    except anthropic.APIConnectionError as exc:
        log.warning("bedrock unreachable: %s", exc)
        return None
    if message.stop_reason == "refusal":
        log.warning("bedrock declined the summary")
        return None
    text = "".join(b.text for b in message.content if b.type == "text").strip()
    return text or None


WORK_SYSTEM = _PROMPTS["work_system"]

WORK_SCHEMA = {
    "type": "object",
    "properties": {
        "persona": {"type": "string", "enum": ["school", "rider", "worker", "commuter", "older", "athlete"]},
        "start_hour": {"type": "integer", "description": "0-23, or -1 if not stated"},
        "end_hour": {"type": "integer", "description": "0-23, or -1 if not stated"},
    },
    "required": ["persona", "start_hour", "end_hour"],
    "additionalProperties": False,
}


GEMINI_WORK_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "persona": {"type": "STRING", "enum": WORK_SCHEMA["properties"]["persona"]["enum"]},
        "start_hour": {"type": "INTEGER"},
        "end_hour": {"type": "INTEGER"},
    },
    "required": ["persona", "start_hour", "end_hour"],
}


def classify_work(text, client=None, session=None):
    """{"persona", "start_hour", "end_hour"} read from someone's own words by
    the AI model, or None when it is off or fails (the caller falls back to
    keywords). Hours are None unless the text gives them."""
    if not text or (client is None and not enabled()):
        return None
    if client is None and provider() == "gemini":
        raw = gemini(WORK_SYSTEM, text[:200], max_tokens=2048, schema=GEMINI_WORK_SCHEMA, session=session)
        return _work_reading(raw)
    import anthropic

    client = client or _bedrock()
    try:
        message = client.messages.create(
            model=settings.get("bedrock_model"),
            max_tokens=1000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": WORK_SCHEMA}},
            system=WORK_SYSTEM,
            messages=[{"role": "user", "content": text[:200]}],
        )
    except anthropic.APIError as exc:
        log.warning("bedrock could not read the work description: %s", type(exc).__name__)
        return None
    if message.stop_reason == "refusal":
        return None
    return _work_reading("".join(b.text for b in message.content if b.type == "text"))


def _work_reading(raw):
    """Check the model's JSON answer; None if it is not a valid reading."""
    if not raw:
        return None
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        out = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(out, dict):
        return None
    if out.get("persona") not in WORK_SCHEMA["properties"]["persona"]["enum"]:
        return None
    hours = [out.get("start_hour"), out.get("end_hour")]
    if not all(isinstance(h, int) and 0 <= h <= 23 for h in hours) or hours[0] == hours[1]:
        hours = [None, None]
    return {"persona": out["persona"], "start_hour": hours[0], "end_hour": hours[1]}


_polly = None

# Kajal is Polly's neural voice for Indian English and Hindi.
VOICES = {"en": "en-IN", "hi": "hi-IN"}


def speak(text, lang="en", client=None):
    """MP3 of `text` as a data: URL, or None if Polly fails."""
    global _polly
    if client is None:
        if _polly is None:
            import boto3

            _polly = boto3.client("polly")
        client = _polly
    voice, code = settings.get("polly_voice"), VOICES[lang]
    try:
        resp = client.synthesize_speech(
            Text=text[:1500], OutputFormat="mp3", VoiceId=voice, LanguageCode=code, Engine="neural",
        )
        audio = resp["AudioStream"].read()
    except Exception as exc:  # botocore errors and missing permissions alike
        log.warning("polly failed: %s", exc)
        return None
    return "data:audio/mpeg;base64," + base64.b64encode(audio).decode()
