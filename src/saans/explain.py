"""Plain-language explanations: GRAP rules, stages and AQI categories.

Each rule answer keeps its official clause and Cedar policy id; this module
only adds what it means for the person, why the rule exists, and what to do.
It never changes a decision. The text lives in config/explain.json.
"""
from . import settings
from .rules import ADVISED_AGAINST, CHECK, NOT_ALLOWED

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


def stage_headline(stage, day_aqi, category, day="today", outside=None):
    """The big line in the stage box: never a bare "None". `outside` is the
    name of a place outside Delhi-NCR, where GRAP does not apply."""
    h = _HEADLINES
    if outside:
        return {"title": h["outside_title"].format(area=outside), "sub": h["outside_sub"]}
    if stage is None:
        return dict(h["unknown"])
    if stage == 0:
        stage1 = STAGES[1]["min_aqi"]
        if day_aqi is None:
            sub = ""
        elif category in h["okay_categories"]:
            sub = h["none_okay"].format(category=category, aqi=day_aqi, stage1_min=stage1)
        elif day_aqi < stage1:
            sub = h["none_moderate"].format(category=category, aqi=day_aqi, gap=stage1 - day_aqi, stage1_min=stage1)
        else:
            sub = h["none_other"].format(category=category, aqi=day_aqi)
        return {"title": h["none_title"].format(day=h["days"].get(day, day)), "sub": sub}
    info = STAGES[stage]
    return {"title": h["stage_title"].format(roman=_ROMAN[stage], name=info["name"]), "sub": info["about"]}


GRAP = _CONFIG["grap"]


def rule_text(activity_id, rule):
    """{means, why, do} for one rule answer (a RuleResult dict)."""
    if rule["decision"] == CHECK:
        if rule.get("policy_id"):  # only a draft rule matched
            return {**_CONFIG["draft_rule"], "do": _CONFIG["uncovered_default"]["do"]}
        return UNCOVERED.get(activity_id, _CONFIG["uncovered_default"])
    return POLICY.get(rule["policy_id"]) or {"means": rule.get("clause"), "why": None, "do": None}


def rules_for_you(activities, stage, day="today"):
    """Marks each activity whose rule changes something in the day (`restricts`,
    shown as its own card) and returns one line naming all the rest, or None.
    With no GRAP stage on, "check the official order" restricts nothing."""
    restricting = {NOT_ALLOWED, ADVISED_AGAINST} | ({CHECK} if stage else set())
    rest = []
    for a in activities:
        a["restricts"] = bool(a["rule"]) and a["rule"]["decision"] in restricting
        if a["rule"] and not a["restricts"]:
            rest.append(a["label"])
    if not rest:
        return None
    key = ("rest_free" if not stage else "rest_allowed") if any(a["restricts"] for a in activities) else (
        "all_free" if not stage else "all_allowed")
    return GRAP[key].format(day=GRAP["day_words"][day], activities=GRAP["list_joiner"].join(rest))
