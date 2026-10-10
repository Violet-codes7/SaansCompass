"""English to Hindi for the whole page.

The browser sends the page's visible text; each string is looked up in a
built-in dictionary (headings, labels, buttons) and anything else goes to
Amazon Translate. Without Translate, the built-in words still switch and the
rest stays in English. Translations are cached in this Lambda's memory only:
page text can carry health details, so it is never written to DynamoDB.
"""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from . import settings

log = logging.getLogger(__name__)

MAX_TEXTS = settings.get("translate_max_texts")
MAX_CHARS = settings.get("translate_max_chars")
CHUNK_BYTES = 4500  # TranslateText takes up to 10,000 bytes per call
PAUSE_AFTER_FAILURE = 600

HI = settings.load("hindi")["phrases"]


def _core(text):
    """Split off leading and trailing punctuation so " · Moderate" finds "Moderate"."""
    strip = " ·:,()–-•"
    start = len(text) - len(text.lstrip(strip))
    end = len(text.rstrip(strip))
    return text[:start], text[start:end], text[end:]


def builtin(text):
    """The dictionary's Hindi for `text`, or None."""
    if text in HI:
        return HI[text]
    head, core, tail = _core(text)
    if core in HI:
        return head + HI[core] + tail
    if core + ":" in HI:
        return head + HI[core + ":"].rstrip(":") + tail
    return None


_cache = {}
_state = {"paused_until": 0.0}
_client = None


def translate_enabled():
    return str(settings.get("translate")).lower() in ("on", "1", "true")


def _translate_client():
    global _client
    if _client is None:
        import boto3

        _client = boto3.client("translate")
    return _client


def _remember(src, dst):
    if len(_cache) >= 5000:
        _cache.pop(next(iter(_cache)))
    _cache[src] = dst


def _translate_chunk(client, chunk):
    """Translate a list of strings in one call, joined by newlines; per string
    if the line count does not come back the same."""
    resp = client.translate_text(Text="\n".join(chunk), SourceLanguageCode="en", TargetLanguageCode="hi")
    lines = resp["TranslatedText"].split("\n")
    if len(lines) == len(chunk):
        return lines
    return [client.translate_text(Text=t, SourceLanguageCode="en", TargetLanguageCode="hi")["TranslatedText"]
            for t in chunk]


def _chunks(texts):
    chunk, size = [], 0
    for t in texts:
        n = len(t.encode()) + 1
        if chunk and size + n > CHUNK_BYTES:
            yield chunk
            chunk, size = [], 0
        chunk.append(t)
        size += n
    if chunk:
        yield chunk


def to_hindi(texts, client=None, now=None):
    """Hindi for each string, in order. Returns (texts, complete): complete is
    False when some strings had to stay in English."""
    out = list(texts)
    todo = []
    texts = [" ".join(t.split()) for t in texts]  # one line each, for the newline batching
    for i, t in enumerate(texts):
        hit = builtin(t) or _cache.get(t)
        if hit is not None:
            out[i] = hit
        else:
            todo.append(i)
    now = now if now is not None else time.time()
    if not todo:
        return out, True
    if not (client or translate_enabled()) or now < _state["paused_until"]:
        return out, False
    unique = list(dict.fromkeys(texts[i] for i in todo))
    client = client or _translate_client()
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            parts = list(pool.map(lambda c: (c, _translate_chunk(client, c)), _chunks(unique)))
    except Exception as exc:  # missing permission, throttling, network
        log.warning("amazon translate failed: %s", type(exc).__name__)
        _state["paused_until"] = now + PAUSE_AFTER_FAILURE
        return out, False
    for src, dst in parts:
        for a, b in zip(src, dst):
            _remember(a, b)
    for i in todo:
        out[i] = _cache.get(texts[i], texts[i])
    return out, True
