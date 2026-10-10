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
        "delhi_aqi": plan["stage"].get("day_aqi"),
        "stage_outlook_tomorrow": (plan["stage"].get("outlook") or {}).get("label"),
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
        "trips": _trip_facts(plan.get("route")),
        "stale_forecast": plan["is_stale"],
    }


def _trip_facts(route):
    """Where the person goes and the worst air on each trip, without coordinates."""
    if not route:
        return None
    return {"from": route["from"]["name"], "to": route["to"]["name"], "travel": route["modes"],
            "legs": [{"trip": leg["label"], "time": leg["time"],
                      "worst": {"area": leg["worst"]["name"], "aqi": leg["worst"]["aqi"]} if leg["worst"] else None}
                     for leg in route["legs"]]}


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


def _structured(system, user, schema, gemini_schema, client=None, session=None):
    """The model's JSON answer as text, or None when the model is off or fails."""
    if client is None and not enabled():
        return None
    if client is None and provider() == "gemini":
        return gemini(system, user, max_tokens=2048, schema=gemini_schema, session=session)
    import anthropic

    client = client or _bedrock()
    try:
        message = client.messages.create(
            model=settings.get("bedrock_model"),
            max_tokens=1000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIError as exc:
        log.warning("bedrock could not read the form: %s", type(exc).__name__)
        return None
    if message.stop_reason == "refusal":
        return None
    return "".join(b.text for b in message.content if b.type == "text")


def _json(raw):
    """A JSON object from the model's answer, or None."""
    if not raw:
        return None
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        out = json.loads(raw)
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def classify_work(text, client=None, session=None):
    """{"persona", "start_hour", "end_hour"} read from someone's own words by
    the AI model, or None when it is off or fails (the caller falls back to
    keywords). Hours are None unless the text gives them."""
    if not text:
        return None
    return _work_reading(_structured(WORK_SYSTEM, text[:200], WORK_SCHEMA, GEMINI_WORK_SCHEMA, client, session))


def _work_reading(raw):
    """Check the model's JSON answer; None if it is not a valid reading."""
    out = _json(raw)
    if not out or out.get("persona") not in WORK_SCHEMA["properties"]["persona"]["enum"]:
        return None
    hours = [out.get("start_hour"), out.get("end_hour")]
    if not all(isinstance(h, int) and 0 <= h <= 23 for h in hours) or hours[0] == hours[1]:
        hours = [None, None]
    return {"persona": out["persona"], "start_hour": hours[0], "end_hour": hours[1]}


ROUTE_SYSTEM = _PROMPTS["route_system"]
TRAVEL_MODES = list(settings.load("profile")["commute_modes"])
_PLACE = {"type": "object", "properties": {"found": {"type": "boolean"}, "lat": {"type": "number"},
                                           "lon": {"type": "number"}},
          "required": ["found", "lat", "lon"], "additionalProperties": False}
ROUTE_SCHEMA = {
    "type": "object",
    "properties": {"start": _PLACE, "destination": _PLACE,
                   "modes": {"type": "array", "items": {"type": "string", "enum": TRAVEL_MODES}}},
    "required": ["start", "destination", "modes"],
    "additionalProperties": False,
}
_GEMINI_PLACE = {"type": "OBJECT", "properties": {"found": {"type": "BOOLEAN"}, "lat": {"type": "NUMBER"},
                                                  "lon": {"type": "NUMBER"}},
                 "required": ["found", "lat", "lon"]}
GEMINI_ROUTE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"start": _GEMINI_PLACE, "destination": _GEMINI_PLACE,
                   "modes": {"type": "ARRAY", "items": {"type": "STRING", "enum": TRAVEL_MODES}}},
    "required": ["start", "destination", "modes"],
}


def read_route(start, destination, travel, client=None, session=None):
    """{"start": (lat, lon) | None, "destination": ..., "modes": [...]} read
    from what someone typed, or None when the model is off or fails."""
    if not (start or destination or travel):
        return None
    user = json.dumps({"start": start or "", "destination": destination or "", "travel": travel or ""},
                      ensure_ascii=False)
    out = _json(_structured(ROUTE_SYSTEM, user, ROUTE_SCHEMA, GEMINI_ROUTE_SCHEMA, client, session))
    if not out:
        return None

    def place(key, text):
        p = out.get(key)
        if not text or not isinstance(p, dict) or not p.get("found"):
            return None
        lat, lon = p.get("lat"), p.get("lon")
        if not all(isinstance(v, (int, float)) for v in (lat, lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return (float(lat), float(lon))

    modes = [m for m in out.get("modes") or [] if m in TRAVEL_MODES] if travel else []
    return {"start": place("start", start), "destination": place("destination", destination),
            "modes": list(dict.fromkeys(modes))}


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
