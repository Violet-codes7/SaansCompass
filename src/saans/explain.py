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


def _restricts(rule, stage):
    """True when a rule answer changes something in the day: an order or
    advice against it, or "check the official order" where it may (a draft
    rule matched, or Stage III and up, when states add their own orders)."""
    if rule["decision"] in (NOT_ALLOWED, ADVISED_AGAINST):
        return True
    return rule["decision"] == CHECK and bool(stage) and (bool(rule.get("policy_id")) or stage >= GRAP["check_from_stage"])


def rules_for_you(activities, stage, day="today"):
    """Marks each activity whose rule changes something in the day (`restricts`,
    shown as its own card) and returns one line for all the rest, or None:
    what is allowed, and what GRAP has no rule on. With no stage on, GRAP
    restricts nothing."""
    allowed, uncovered = [], []
    for a in activities:
        a["restricts"] = bool(a["rule"]) and _restricts(a["rule"], stage)
        if a["rule"] and not a["restricts"]:
            (uncovered if stage and a["rule"]["decision"] == CHECK else allowed).append(a["label"])
    if not (allowed or uncovered):
        return None
    words, join = GRAP["day_words"][day], GRAP["list_joiner"].join
    cards = any(a["restricts"] for a in activities)
    if not stage:
        return GRAP["rest_free" if cards else "all_free"].format(day=words, activities=join(allowed))
    parts = [GRAP["no_rule"].format(activities=join(uncovered))] if uncovered else []
    if allowed:
        parts.append(GRAP["rest_allowed" if cards or uncovered else "all_allowed"].format(day=words, activities=join(allowed)))
    return " ".join(parts)
