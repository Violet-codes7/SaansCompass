"""Plain-language summary of a plan, written by Claude on Amazon Bedrock,
and read aloud by Amazon Polly.

Claude only rephrases. Every rule decision, stage and time window comes from
the plan, which the page shows unchanged next to the summary. If Bedrock is
not set up, fails or declines, the page simply shows no summary.
"""
import base64
import hashlib
import json
import logging
import os

log = logging.getLogger(__name__)

DEFAULT_MODEL = "anthropic.claude-opus-5-5"
LANGUAGES = {"en": "English", "hi": "Hindi"}

SYSTEM = """You rewrite an air-quality plan for one Delhi resident in plain, friendly {language}.
Write exactly two short sentences. Use only the facts in the JSON you are given.
Rules:
- Never add, remove or soften a GRAP rule decision. If any rule says "Not allowed" or "Advised against", mention the most important one.
- Do not invent numbers, times, places or health claims that are not in the JSON.
- This is advice, not a diagnosis: do not give medical instructions beyond the plan.
- No greeting, no markdown, no lists."""

_client = None


def enabled():
    return bool(os.environ.get("BEDROCK_MODEL"))


def _bedrock():
    global _client
    if _client is None:
        from anthropic import AnthropicBedrockMantle

        _client = AnthropicBedrockMantle(
            aws_region=os.environ.get("BEDROCK_REGION") or os.environ.get("AWS_REGION"),
            timeout=20.0,
            max_retries=1,
        )
    return _client


def plan_facts(plan):
    """The small, decision-level slice of the plan Claude is allowed to use."""
    return {
        "who": plan["persona"]["label"],
        "area": plan["area"]["name"],
        "date": plan["date"],
        "grap_stage": plan["stage"]["label"],
        "stage_source": plan["stage"]["source"],
        "verdict": plan["verdict_label"],
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
        "demo_data": plan["is_demo"],
    }


def cache_key(plan, lang):
    facts = json.dumps(plan_facts(plan), sort_keys=True, ensure_ascii=False)
    return "AI#" + hashlib.sha256(f"{lang}|{facts}".encode()).hexdigest()


def summarize(plan, lang="en", client=None):
    """Two-sentence summary, or None when it cannot be produced."""
    if lang not in LANGUAGES:
        raise ValueError("lang must be en or hi")
    import anthropic

    client = client or _bedrock()
    try:
        message = client.messages.create(
            model=os.environ.get("BEDROCK_MODEL") or DEFAULT_MODEL,
            max_tokens=2000,
            output_config={"effort": "low"},
            system=SYSTEM.format(language=LANGUAGES[lang]),
            messages=[{
                "role": "user",
                "content": json.dumps(plan_facts(plan), ensure_ascii=False),
            }],
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


_polly = None

# Kajal is Polly's neural voice for Indian English and Hindi.
VOICES = {"en": ("Kajal", "en-IN"), "hi": ("Kajal", "hi-IN")}


def speak(text, lang="en", client=None):
    """MP3 of `text` as a data: URL, or None if Polly fails."""
    global _polly
    if client is None:
        if _polly is None:
            import boto3

            _polly = boto3.client("polly")
        client = _polly
    voice, code = VOICES[lang]
    try:
        resp = client.synthesize_speech(
            Text=text[:1500], OutputFormat="mp3", VoiceId=voice, LanguageCode=code, Engine="neural",
        )
        audio = resp["AudioStream"].read()
    except Exception as exc:  # botocore errors and missing permissions alike
        log.warning("polly failed: %s", exc)
        return None
    return "data:audio/mpeg;base64," + base64.b64encode(audio).decode()
