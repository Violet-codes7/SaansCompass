"""Personal advice and reading the "what do you do" box, written by a model
on Amazon Bedrock, and read aloud by Amazon Polly.

The model only rephrases. Every rule decision, stage and time window comes
from the plan, which the page shows unchanged next to the advice. If the
model is not set up, fails or declines, the page simply shows no advice and
the work box falls back to keywords.

BEDROCK_MODEL picks the model; AI_PROVIDER=off turns the AI off. Claude
models (ids containing settings "bedrock_messages_marker") are called through
the Anthropic Messages API on Bedrock; any other Bedrock model, such as Amazon
Nova, through Bedrock's Converse API. Both sign with the Lambda's IAM role, so
there is no API key.
"""
import base64
import hashlib
import json
import logging
import os

from . import settings

log = logging.getLogger(__name__)

_PROMPTS = settings.load("prompts")
LANGUAGES = _PROMPTS["languages"]
SYSTEM = _PROMPTS["advice_system"]
HEADINGS = _PROMPTS["advice_headings"]

_client = None
_runtime = None


def model():
    """The Bedrock model id, or None when the AI is off."""
    if str(settings.get("ai_provider")).strip().lower() == "off":
        return None
    return os.environ.get("BEDROCK_MODEL") or None


def provider():
    """"bedrock" or None (off)."""
    return "bedrock" if model() else None


def uses_messages_api(model_id=None):
    """True for Claude models, which take the Anthropic Messages API."""
    return settings.get("bedrock_messages_marker") in (model_id or settings.get("bedrock_model"))


def label():
    """Who wrote the advice, for the page: from settings "ai_labels" by model id."""
    labels = settings.get("ai_labels")
    chosen = model() or ""
    return next((name for marker, name in labels.items() if marker != "default" and marker in chosen),
                labels["default"])


def enabled():
    return provider() is not None


def _region():
    return settings.get("bedrock_region") or os.environ.get("AWS_REGION")


def _bedrock():
    global _client
    if _client is None:
        from anthropic import AnthropicBedrockMantle

        _client = AnthropicBedrockMantle(
            aws_region=_region(),
            timeout=float(settings.get("ai_timeout_seconds")),
            max_retries=1,
        )
    return _client


def _bedrock_runtime():
    global _runtime
    if _runtime is None:
        import boto3
        from botocore.config import Config

        timeout = settings.get("ai_timeout_seconds")
        _runtime = boto3.client("bedrock-runtime", region_name=_region(),
                                config=Config(read_timeout=timeout, connect_timeout=timeout,
                                              retries={"max_attempts": 2}))
    return _runtime


def converse(system, user, max_tokens, runtime=None):
    """Text from a non-Claude Bedrock model through the Converse API, or None
    on any failure, block or cut-off answer."""
    runtime = runtime or _bedrock_runtime()
    try:
        resp = runtime.converse(
            modelId=settings.get("bedrock_model"),
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": settings.get("ai_temperature")},
        )
    except Exception as exc:  # botocore ClientError, timeouts and missing permissions alike
        log.warning("bedrock converse failed: %s", type(exc).__name__)
        return None
    if resp.get("stopReason") not in ("end_turn", "stop_sequence"):
        log.warning("bedrock converse gave no answer: %s", resp.get("stopReason"))
        return None
    parts = resp.get("output", {}).get("message", {}).get("content", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    return text or None


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


def summarize(plan, lang="en", client=None, runtime=None):
    """Two-sentence summary, or None when it cannot be produced."""
    if lang not in LANGUAGES:
        raise ValueError("lang must be en or hi")
    system = SYSTEM.format(language=LANGUAGES[lang], headings=", ".join(HEADINGS[lang]))
    facts = json.dumps(plan_facts(plan), ensure_ascii=False)
    if client is None and (runtime is not None or not uses_messages_api()):
        return converse(system, facts, max_tokens=settings.get("ai_max_tokens"), runtime=runtime)
    import anthropic

    client = client or _bedrock()
    try:
        message = client.messages.create(
            model=settings.get("bedrock_model"),
            max_tokens=settings.get("ai_max_tokens"),
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



def _structured(system, user, schema, client=None, runtime=None):
    """The model's JSON answer as text, or None when the model is off or fails.
    Claude is held to the schema by structured outputs; other Bedrock models
    get the schema in the system prompt and their answer is checked after."""
    if client is None and runtime is None and not enabled():
        return None
    if client is None and (runtime is not None or not uses_messages_api()):
        system = system + "\n\n" + _PROMPTS["json_instruction"].format(schema=json.dumps(schema))
        return converse(system, user, max_tokens=settings.get("ai_max_tokens"), runtime=runtime)
    import anthropic

    client = client or _bedrock()
    try:
        message = client.messages.create(
            model=settings.get("bedrock_model"),
            max_tokens=settings.get("ai_max_tokens"),
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


def classify_work(text, client=None, runtime=None):
    """{"persona", "start_hour", "end_hour"} read from someone's own words by
    the AI model, or None when it is off or fails (the caller falls back to
    keywords). Hours are None unless the text gives them."""
    if not text:
        return None
    return _work_reading(_structured(WORK_SYSTEM, text[:200], WORK_SCHEMA, client, runtime))


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


def read_route(start, destination, travel, client=None, runtime=None):
    """{"start": (lat, lon) | None, "destination": ..., "modes": [...]} read
    from what someone typed, or None when the model is off or fails."""
    if not (start or destination or travel):
        return None
    user = json.dumps({"start": start or "", "destination": destination or "", "travel": travel or ""},
                      ensure_ascii=False)
    out = _json(_structured(ROUTE_SYSTEM, user, ROUTE_SCHEMA, client, runtime))
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
