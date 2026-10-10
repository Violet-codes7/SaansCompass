"""Flask routes: picker, plan page, JSON API, poster, subscribe, health check."""
import logging
import os
from datetime import timedelta
from urllib.parse import urlencode

from flask import Flask, jsonify, redirect, render_template, request, url_for

from . import ai, data, i18n
from .alerts import subscribe as sns_subscribe
from .personas import PERSONAS
from . import gauges, weather
from .aqi import category as aqi_category
from .explain import STAGES
from .profile import COMMUTE_MODES, CONDITION_GROUPS, CONDITIONS, WORK, clean_job, guess_work, parse_profile
from .service import air_now
from .service import get_plan
from .stage import ROMAN
from .store import get_store

log = logging.getLogger(__name__)

_sns = None


def _sns_client():
    global _sns
    if _sns is None:
        import boto3

        _sns = boto3.client("sns")
    return _sns


_work_cache = {}


def _read_work(job):
    """Which persona fits someone's own words: Claude first, then keywords.
    Cached in this Lambda's memory only, never stored."""
    hit = _work_cache.get(job)
    if hit:
        return hit
    out = ai.classify_work(job)
    if out:
        out = {**out, "how": "ai"}
    else:
        guess = guess_work(job)
        out = {"persona": guess or "commuter", "start_hour": None, "end_hour": None,
               "how": "keywords" if guess else "default"}
    if len(_work_cache) >= 256:
        _work_cache.pop(next(iter(_work_cache)))
    _work_cache[job] = out
    return out


def _persona_id():
    if request.args.get("persona"):
        return request.args["persona"]
    job = clean_job(request.args.get("job"))
    return _read_work(job)["persona"] if job else "school"


def _plan_args():
    return {
        "persona_id": _persona_id(),
        "area_id": request.args.get("area", "anand-vihar"),
        "stage": request.args.get("stage"),
        "day": request.args.get("day") or None,  # empty means pick today/tomorrow from the clock
    }


def _build_plan():
    """The plan for this request, personalised when profile fields are present.
    The profile is used for this request only: never stored or logged."""
    args = _plan_args()
    profile = parse_profile(request.args, args["persona_id"])
    return get_plan(**args, profile=profile)


def _log_plan(plan):
    log.info(
        "plan persona=%s area=%s stage=%s source=%s demo=%s",
        plan["persona"]["id"], plan["area"]["id"], plan["stage"]["label"],
        plan["stage"]["source"], plan["is_demo"],
    )


_personal_cache = {}


def _plan_link(**changes):
    """This plan page's URL with some arguments changed; an empty value removes one."""
    args = request.args.to_dict(flat=False)
    for key, value in changes.items():
        if value in (None, ""):
            args.pop(key, None)
        else:
            args[key] = [value]
    return url_for("plan_page") + "?" + urlencode(args, doseq=True)


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    @app.context_processor
    def globals_():
        return {"personas": PERSONAS, "areas": data.AREAS, "roman": ROMAN, "ai_enabled": ai.enabled(),
                "work": WORK, "conditions": CONDITIONS, "commute_modes": COMMUTE_MODES, "plan_link": _plan_link,
                "aqi_gauge": gauges.aqi_gauge, "simple_gauge": gauges.simple_gauge,
                "condition_groups": CONDITION_GROUPS, "stages": STAGES}

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    @app.get("/")
    def index():
        # A live dashboard for central Delhi (ITO) above the form.
        area = data.AREAS["ito"]
        store = get_store()
        now = data.now_ist()
        forecast = data.get_forecast(area, store, now=now)
        tomorrow = data.day_aqi(forecast, now.date() + timedelta(days=1))
        dash = {"area": area.name, "air_now": air_now(forecast, now), "is_demo": forecast["is_demo"],
                "air_tomorrow": {"aqi": tomorrow, "category": aqi_category(tomorrow)}}
        return render_template("index.html", dash=dash, weather=weather.get_weather(area, store))

    @app.get("/plan")
    def plan_page():
        job = clean_job(request.args.get("job"))
        if job and not request.args.get("persona"):
            # Read the description once, then keep the answer in the link so
            # the summary, poster and voice all use the same reading.
            reading = _read_work(job)
            changes = {"persona": reading["persona"], "read": reading["how"]}
            if reading["start_hour"] is not None and not (request.args.get("start") or request.args.get("end")):
                changes.update(start=str(reading["start_hour"]), end=str(reading["end_hour"]))
            return redirect(_plan_link(**changes))
        args = _plan_args()
        try:
            plan = _build_plan()
        except ValueError as exc:
            return render_template("error.html", message=str(exc)), 400
        _log_plan(plan)
        wx = weather.get_weather(data.get_area(plan["area"]["id"]), get_store())
        return render_template("plan.html", plan=plan, args=args, weather=wx)

    @app.get("/poster")
    def poster():
        args = _plan_args()
        try:
            plan = _build_plan()
        except ValueError as exc:
            return render_template("error.html", message=str(exc)), 400
        return render_template("poster.html", plan=plan, args=args)

    @app.get("/api/plan")
    def api_plan():
        try:
            plan = _build_plan()
        except ValueError as exc:
            return jsonify({
                "error": str(exc),
                "allowed": {
                    "persona": list(PERSONAS),
                    "area": list(data.AREAS),
                    "stage": ["0", "I", "II", "III", "IV"],
                    "day": ["today", "tomorrow"],
                },
            }), 400
        _log_plan(plan)
        return jsonify(plan)

    def _summary(plan, lang):
        key = ai.cache_key(plan, lang)
        if plan.get("profile"):
            # Personal advice may mention health details: keep it in this
            # Lambda's memory only, never in DynamoDB.
            text = _personal_cache.get(key)
            if text is None:
                text = ai.summarize(plan, lang)
                if text:
                    if len(_personal_cache) >= 128:
                        _personal_cache.pop(next(iter(_personal_cache)))
                    _personal_cache[key] = text
            return text
        store = get_store()
        text = store.get_text(key)
        if text is None:
            text = ai.summarize(plan, lang)
            if text:
                store.put_text(key, text)
        return text

    @app.get("/api/summary")
    def api_summary():
        if not ai.enabled():
            return jsonify({"error": "AI summary is not set up here."}), 503
        lang = request.args.get("lang", "en")
        try:
            if lang not in ai.LANGUAGES:
                raise ValueError("lang must be en or hi")
            plan = _build_plan()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        text = _summary(plan, lang)
        if not text:
            return jsonify({"error": "No summary right now."}), 502
        return jsonify({"summary": text, "lang": lang, "by": "Claude on Amazon Bedrock"})

    @app.get("/api/speak")
    def api_speak():
        if not ai.enabled():
            return jsonify({"error": "Voice is not set up here."}), 503
        lang = request.args.get("lang", "en")
        try:
            if lang not in ai.LANGUAGES:
                raise ValueError("lang must be en or hi")
            plan = _build_plan()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        text = _summary(plan, lang)
        audio = ai.speak(text, lang) if text else None
        if not audio:
            return jsonify({"error": "No audio right now."}), 502
        return jsonify({"audio": audio, "text": text})

    @app.post("/api/translate")
    def api_translate():
        body = request.get_json(silent=True) or {}
        texts = body.get("texts")
        if body.get("to") != "hi" or not isinstance(texts, list) or len(texts) > i18n.MAX_TEXTS \
                or not all(isinstance(t, str) and len(t) <= i18n.MAX_CHARS for t in texts):
            return jsonify({"error": f"send to=hi and up to {i18n.MAX_TEXTS} strings"}), 400
        out, complete = i18n.to_hindi(texts)
        return jsonify({"texts": out, "complete": complete})

    @app.post("/subscribe")
    def subscribe():
        topic = os.environ.get("TOPIC_ARN")
        email = request.form.get("email", "")
        area_id = request.form.get("area", "")
        if not topic:
            return render_template("error.html", message="Email alerts are not set up in this environment."), 503
        try:
            area = sns_subscribe(_sns_client(), topic, email, area_id)
        except ValueError as exc:
            return render_template("error.html", message=str(exc)), 400
        except Exception:
            log.exception("subscribe failed")
            return render_template("error.html", message="Could not subscribe right now. Please try again."), 502
        return render_template("subscribed.html", area=area)

    @app.get("/favicon.ico")
    def favicon():
        return redirect(url_for("static", filename="favicon.svg"), 301)

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "alerts_configured": bool(os.environ.get("TOPIC_ARN")),
                        "cache": "dynamodb" if os.environ.get("TABLE") else "memory"})

    return app
