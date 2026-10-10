"""Settings and content, read from the files in config/.

settings.json holds runtime settings; each key can be overridden by an
environment variable of the same name in upper case, which is how the SAM
template sets per-deploy values. The other files hold content tables (areas,
personas, conditions, rule explanations, Hindi words, AI prompts).
"""
import json
import os
from datetime import timedelta, timezone
from functools import lru_cache
from pathlib import Path

CONFIG_DIR = Path(__file__).parent / "config"


@lru_cache(maxsize=None)
def load(name):
    """A content file from config/, parsed."""
    return json.loads((CONFIG_DIR / f"{name}.json").read_text(encoding="utf-8"))


def get(key):
    defaults = load("settings")
    if key not in defaults:
        raise KeyError(f"unknown setting {key}")
    default = defaults[key]
    raw = os.environ.get(key.upper())
    if raw is None or raw == "":
        return default
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "on", "yes")
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, (list, dict)):
        return json.loads(raw)
    return raw


def get_list(key):
    """A comma-separated setting as a list."""
    return [part.strip() for part in str(get(key)).split(",") if part.strip()]


def tz():
    return timezone(timedelta(minutes=get("utc_offset_minutes")), get("timezone_label"))
