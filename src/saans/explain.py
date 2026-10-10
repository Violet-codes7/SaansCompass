"""Plain-language explanations: GRAP rules, stages and AQI categories.

Each rule answer keeps its official clause and Cedar policy id; this module
only adds what it means for the person, why the rule exists, and what to do.
It never changes a decision. The text lives in config/explain.json.
"""
from . import settings
from .rules import CHECK

_CONFIG = settings.load("explain")

# What each GRAP stage is, in the AQI bands GRAP is defined on.
STAGES = {int(k): v for k, v in _CONFIG["stages"].items()}
# CPCB's own description of each AQI category's health impact.
CATEGORY_IMPACT = _CONFIG["category_impact"]
POLLUTANTS = _CONFIG["pollutants"]
VERDICT_MEANING = _CONFIG["verdict_meaning"]
UNCOVERED = _CONFIG["uncovered"]
STAGE_SOURCES = _CONFIG["stage_sources"]
_HEADLINES = _CONFIG["headlines"]
_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV"}


def _policy(policy_id):
    text = _CONFIG["policy"].get(policy_id)
    while text and "same_as" in text:
        text = _CONFIG["policy"].get(text["same_as"])
    return text


POLICY = {pid: _policy(pid) for pid in _CONFIG["policy"]}


def stage_headline(stage, day_aqi, category):
    """The big line in the stage box: never a bare "None"."""
    h = _HEADLINES
    if stage is None:
        return dict(h["unknown"])
    if stage == 0:
        if category in h["okay_categories"]:
            sub = h["none_okay"].format(category=category)
        elif category == "Moderate":
            sub = h["none_moderate"].format(stage1_min=STAGES[1]["min_aqi"])
        else:
            sub = h["none_other"].format(category=category)
        return {"title": h["none_title"], "sub": sub}
    info = STAGES[stage]
    return {"title": h["stage_title"].format(roman=_ROMAN[stage], name=info["name"]), "sub": info["about"]}


def rule_text(activity_id, rule):
    """{means, why, do} for one rule answer (a RuleResult dict)."""
    if rule["decision"] == CHECK:
        if rule.get("policy_id"):  # only a draft rule matched
            return {**_CONFIG["draft_rule"], "do": _CONFIG["uncovered_default"]["do"]}
        return UNCOVERED.get(activity_id, _CONFIG["uncovered_default"])
    return POLICY.get(rule["policy_id"]) or {"means": rule.get("clause"), "why": None, "do": None}
