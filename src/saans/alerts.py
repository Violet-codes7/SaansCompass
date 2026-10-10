"""Area alerts: build each area's plans, and email subscribers only when they change.

Each SNS email subscription has a filter policy on `zone`, and messages are
published with a `zone` attribute, so people only get their own area.
"""
import hashlib
import json
import logging
import re

from . import data, settings
# Area alerts cover the three original personas; the email stays short.
from .service import get_plan

log = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def verdict_fingerprint(plans):
    """Hash of what matters to a reader: stage, verdicts, rule decisions, best window.
    Hourly AQI wobble alone does not trigger an email."""
    key = {
        "stage": plans[0]["stage"]["stage"] if plans else None,
        "personas": [
            {
                "persona": p["persona"]["id"],
                "verdict": p["verdict"],
                "window": (p["best_window"] or {}).get("start"),
                "rules": [(r["activity_id"], r["decision"]) for r in p["rules"]],
            }
            for p in plans
        ],
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()


def compose(area, run, plans, site_url=None):
    first = plans[0]
    when = "Today" if run == "today" else "Tomorrow"
    stage = first["stage"]
    if not first.get("grap_applies", True):  # GRAP switched off: the area's own air
        stage_text = f"AQI about {first['air']['day_aqi']}" if first["air"].get("day_aqi") is not None else "no AQI yet"
    else:
        stage_text = (f"GRAP Stage {stage['label']} ({stage['source']})" if stage["stage"]
                      else f"No GRAP stage ({stage['source']})")
        if stage.get("day_aqi") is not None:
            stage_text += f", Delhi AQI about {stage['day_aqi']}"
    subject = f"Saans Compass: {area.name}, {when.lower()} {first['date']}"
    lines = [
        f"{when} in {area.name} ({first['date']}): {stage_text}.",
        "",
    ]
    for p in plans:
        line = f"- {p['persona']['label']}: {p['verdict_label']}"
        if p["best_window"]:
            line += f". {p['best_window_title']}: {p['best_window']['start']} to {p['best_window']['end']}"
        lines.append(line + ".")
        not_allowed = [r for r in p["rules"] if r["decision"] == "not_allowed"]
        for r in not_allowed:
            lines.append(f"    Not allowed: {r['activity_id']} ({r['policy_id']})")
    lines += [
        "",
        "Rules first: GRAP rules always apply before this advice.",
        "Estimates from a forecast model, not medical advice and not an official order.",
    ]
    if site_url:
        lines.append(f"Full plan: {site_url.rstrip('/')}/plan?area={area.id}&day={run}")
    return subject[:100], "\n".join(lines)


def run_alert_check(run, store, sns, topic_arn, now=None, site_url=None, fetcher=None):
    """Check every area; publish where the plan changed. Returns per-area results.

    The new hash is saved only after a successful publish, so a failed publish
    is retried on the next run instead of being silently marked as sent.
    """
    if run not in ("today", "tomorrow"):
        raise ValueError("run must be today or tomorrow")
    now = now or data.now_ist()
    results = []
    errors = []
    for area in data.AREAS.values():
        try:
            try:
                plans = [
                    get_plan(pid, area.id, day=run, now=now, store=store, fetcher=fetcher)
                    for pid in settings.get_list("alert_personas")
                ]
            except data.ForecastUnavailable:
                results.append({"area": area.id, "status": "skipped_no_forecast"})
                continue
            if any(p["is_stale"] for p in plans):
                # Only email from a fresh forecast.
                results.append({"area": area.id, "status": "skipped_stale_forecast"})
                continue
            fingerprint = verdict_fingerprint(plans)
            last = store.get_alert_state(area.id, run)
            if last and last["verdict_hash"] == fingerprint:
                results.append({"area": area.id, "status": "unchanged"})
                continue
            subject, message = compose(area, run, plans, site_url)
            sns.publish(
                TopicArn=topic_arn,
                Subject=subject,
                Message=message,
                MessageAttributes={"zone": {"DataType": "String", "StringValue": area.id}},
            )
            store.put_alert_state(area.id, run, fingerprint, message[:1000], now.isoformat())
            results.append({"area": area.id, "status": "sent"})
        except Exception as exc:
            log.exception("alert check failed for %s", area.id)
            errors.append(area.id)
            results.append({"area": area.id, "status": "error", "error": str(exc)})
    return results, errors


def subscribe(sns, topic_arn, email, area_id):
    """Create an email subscription filtered to one area. SNS sends the confirm email."""
    email = (email or "").strip()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address.")
    area = data.get_area(area_id)
    if area.id not in data.AREAS:  # the alert run checks Delhi's areas only
        raise ValueError(settings.load("layout")["alerts"]["areas_only"])
    sns.subscribe(
        TopicArn=topic_arn,
        Protocol="email",
        Endpoint=email,
        Attributes={"FilterPolicy": json.dumps({"zone": [area.id]})},
    )
    return area
