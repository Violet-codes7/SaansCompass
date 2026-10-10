"""Flask routes: picker, plan page, JSON API, poster, subscribe, health check."""
import logging
import os
from datetime import datetime, timedelta
from urllib.parse import urlencode

from flask import Flask, jsonify, redirect, render_template, request, url_for

from . import ai, data, guide, i18n, route, settings, web_accounts
from .alerts import subscribe as sns_subscribe
from .personas import PERSONAS
from . import gauges, weather
from .aqi import category as aqi_category
from .advisor import TEXT as ADVICE_TEXT
from .explain import GRAP, STAGE_SOURCES, STAGES
from .profile import COMMUTE_MODES, CONDITION_GROUPS, CONDITIONS, VEHICLE_LABELS, VEHICLES, WORK, clean_job, clean_text, guess_work, parse_profile
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
        out = {"persona": guess or settings.get("fallback_persona"), "start_hour": None, "end_hour": None,
               "how": "keywords" if guess else "default"}
    if len(_work_cache) >= settings.get("work_cache_size"):
        _work_cache.pop(next(iter(_work_cache)))
    _work_cache[job] = out
    return out


PARTICLES = settings.load("particles")
CHAT_TEXT = settings.load("chat")

_route_cache = {}


def _read_route(start, destination, travel):
    """Areas and travel modes from typed places, cached in this Lambda's
    memory only (never stored or logged)."""
    key = (start, destination, travel)
    hit = _route_cache.get(key)
    if hit:
        return hit
    out = route.read_route(start, destination, travel)
    if len(_route_cache) >= settings.get("work_cache_size"):
        _route_cache.pop(next(iter(_route_cache)))
    _route_cache[key] = out
    return out


def route_texts(args):
    """The typed start, destination and travel, trimmed."""
    limit = settings.get("place_max_chars")
    return {k: clean_text(args.get(k), limit) for k in ("from", "to", "travel")}


def resolve_route(args):
    """Fill in area, to_area, commute and modes from the typed route where the
    link or form does not already give them (a live location sets area)."""
    texts = route_texts(args)
    need = {"start": texts["from"] if not args.get("area") else None,
            "destination": texts["to"] if not args.get("to_area") else None,
            "travel": texts["travel"] if not args.get("commute") else None}
    if not any(need.values()):
        return {}
    reading = _read_route(need["start"], need["destination"], need["travel"])
    out = {"route_read": reading["how"]}
    if need["start"] and reading["area"]:
        out["area"] = reading["area"]
    if need["destination"] and reading["to_area"]:
        out["to_area"] = reading["to_area"]
    if need["travel"] and reading["commute"]:
        out.update(commute=reading["commute"], modes=",".join(reading["modes"]))
    return out


def _modes(raw):
    return [m for m in str(raw or "").split(",") if m in COMMUTE_MODES]


def _saved():
    """The signed-in person's saved profile when this link names no one else."""
    if request.args.get("persona") or request.args.get("job"):
        return None
    return web_accounts.saved_profile()


def _persona_id():
    if request.args.get("persona"):
        return request.args["persona"]
    job = clean_job(request.args.get("job"))
    if job:
        return _read_work(job)["persona"]
    saved = _saved()
    return saved["persona"] if saved else settings.get("default_persona")


def _plan_args():
    saved = _saved()
    source = saved if saved else request.args
    modes = _modes(request.args.get("modes") or source.get("modes"))
    commute = request.args.get("commute") or source.get("commute")
    if commute in COMMUTE_MODES and commute not in modes:  # picked by hand on the plan page
        modes = [commute]
    return {
        "persona_id": _persona_id(),
        "area_id": request.args.get("area") or (saved and saved.get("area")) or settings.get("default_area"),
        "to_area_id": request.args.get("to_area") or source.get("to_area") or None,
        "modes": modes,
        "stage": request.args.get("stage"),
        "day": request.args.get("day") or None,  # empty means pick today/tomorrow from the clock
    }


def _build_plan():
    """The plan for this request, personalised from the link's profile fields
    or, for a signed-in person, their saved profile. Never logged."""
    args = _plan_args()
    saved = _saved()
    if saved:
        profile = web_accounts.profile_from_saved(saved, args["persona_id"])
    else:
        profile = parse_profile(request.args, args["persona_id"])
    return get_plan(**args, profile=profile)


def _log_plan(plan):
    log.info(
        "plan persona=%s area=%s stage=%s source=%s stale=%s",
        plan["persona"]["id"], plan["area"]["id"], plan["stage"]["label"],
        plan["stage"]["source"], plan["is_stale"],
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
    web_accounts.register(app, _read_work, resolve_route)

    @app.context_processor
    def globals_():
        return {"personas": PERSONAS, "areas": data.AREAS, "roman": ROMAN, "ai_enabled": ai.enabled(), "ai_label": ai.label(),
                "work": WORK, "conditions": CONDITIONS, "commute_modes": COMMUTE_MODES, "plan_link": _plan_link,
                "aqi_gauge": gauges.aqi_gauge, "simple_gauge": gauges.simple_gauge, "band_gauge": gauges.band_gauge,
                "weather_dials": weather.DIALS, "weather_text": weather.TEXT["explain"], "particles": PARTICLES,
                "condition_groups": CONDITION_GROUPS, "stages": STAGES, "stage_sources": STAGE_SOURCES, "grap": GRAP, "glance_text": guide.TEXT, "chat_text": CHAT_TEXT, "chat_max_chars": settings.get("chat_max_chars"), "aqi_category": aqi_category, "vehicles": VEHICLES, "vehicle_labels": VEHICLE_LABELS,
                "hour_labels": ADVICE_TEXT["hour_verdict_labels"], "hour_tags": ADVICE_TEXT["hour_tags"],
                "source_links": settings.get("source_links"), "route_messages": route.TEXT["messages"],
                "alert_hours": (settings.get("alert_morning_hour"), settings.get("alert_evening_hour")), "grap_revision": settings.get("grap_revision")}

    @app.errorhandler(data.ForecastUnavailable)
    def no_forecast(exc):
        if request.path.startswith("/api/"):
            return jsonify({"error": str(exc)}), 503
        return render_template("error.html", message=str(exc)), 503

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    @app.get("/")
    def index():
        # A live dashboard above the form: the signed-in person's area, else dashboard_area.
        saved = web_accounts.saved_profile()
        area = data.get_area((saved and saved.get("area")) or settings.get("dashboard_area"))
        store = get_store()
        now = data.now_ist()
        try:
            forecast = data.get_forecast(area, store, now=now)
        except data.ForecastUnavailable:
            dash = None
        else:
            tomorrow = data.day_aqi(forecast, now.date() + timedelta(days=1))
            dash = {"area": area.name, "air_now": air_now(forecast, now), "is_stale": forecast["is_stale"],
                    "fetched_at": forecast["fetched_at"],
                    "air_tomorrow": {"aqi": tomorrow, "category": aqi_category(tomorrow)}}
        return render_template("index.html", dash=dash, dash_area=area.name, weather=weather.get_weather(area, store))

    @app.get("/plan")
    def plan_page():
        # Read the work description and the typed route once, then keep the
        # answers in the link so the summary, poster and voice all use them.
        changes = {}
        job = clean_job(request.args.get("job"))
        if job and not request.args.get("persona"):
            reading = _read_work(job)
            changes = {"persona": reading["persona"], "read": reading["how"]}
            if reading["start_hour"] is not None and not (request.args.get("start") or request.args.get("end")):
                changes.update(start=str(reading["start_hour"]), end=str(reading["end_hour"]))
        if not request.args.get("route_read"):
            changes.update(resolve_route(request.args))
        if changes:
            return redirect(_plan_link(**changes))
        args = _plan_args()
        try:
            plan = _build_plan()
        except ValueError as exc:
            return render_template("error.html", message=str(exc)), 400
        _log_plan(plan)
        wx = weather.get_weather(data.get_area(plan["area"]["id"]), get_store())
        plan["hour_details"] = guide.hour_details(plan, wx)
        saved = _saved()
        texts = route_texts(saved or request.args)
        return render_template("plan.html", plan=plan, args=args, weather=wx, using_saved=bool(saved),
                               route_texts=texts, route_text=route.TEXT,
                               display_name=saved.get("name") if saved else None)

    @app.get("/poster")
    def poster():
        args = _plan_args()
        try:
            plan = _build_plan()
        except ValueError as exc:
            return render_template("error.html", message=str(exc)), 400
        # The QR code opens the live plan for this persona and area only: no
        # health details or what-if stage on a poster pinned to a wall.
        public = request.url_root.rstrip("/") + url_for("plan_page") + "?" + urlencode(
            {"persona": plan["persona"]["id"], "area": plan["area"]["id"]})
        day = datetime.fromisoformat(plan["date"])
        saved = _saved()
        return render_template("poster.html", plan=plan, args=args, public_url=public,
                               name=saved.get("name") if saved else None,
                               qr=gauges.qr_code(public, "QR code for the live plan"),
                               date_label=day.strftime("%A %d %B %Y"))

    @app.post("/api/locate")
    def api_locate():
        """The nearest area to the browser's location. The coordinates are
        used for this answer only: never stored, logged or put in a link."""
        body = request.get_json(silent=True) or {}
        try:
            lat, lon = float(body["lat"]), float(body["lon"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "send lat and lon"}), 400
        area, km = route.nearest_area(lat, lon)
        if area is None:
            return jsonify({"error": route.TEXT["messages"]["outside"], "km": km}), 404
        return jsonify({"area": area.id, "name": area.name, "km": km,
                        "label": route.TEXT["messages"]["located"].format(name=area.name)})

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
                    if len(_personal_cache) >= settings.get("personal_cache_size"):
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
            return jsonify({"error": "No summary right now.", "reason": ai.last_error()}), 502
        return jsonify({"summary": text, "lang": lang, "by": ai.label()})

    @app.post("/api/chat")
    def api_chat():
        """One question about the plan in the link. The question, the chat so
        far and the answer are sent to the model only: never logged or stored."""
        if not ai.enabled():
            return jsonify({"error": CHAT_TEXT["errors"]["off"]}), 503
        body = request.get_json(silent=True) or {}
        lang = body.get("lang", "en")
        try:
            if lang not in ai.LANGUAGES:
                raise ValueError("lang must be en or hi")
            if not isinstance(body.get("question"), str) or not body["question"].strip():
                raise ValueError(CHAT_TEXT["errors"]["empty"])
            plan = _build_plan()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        answer = ai.chat(plan, body["question"], body.get("history"), lang)
        if not answer:
            return jsonify({"error": CHAT_TEXT["errors"]["failed"], "reason": ai.last_error()}), 502
        return jsonify({"answer": answer, "by": ai.label()})

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
