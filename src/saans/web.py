"""Flask routes: picker, plan page, JSON API, poster, subscribe, health check."""
import logging
import os

from flask import Flask, jsonify, redirect, render_template, request, url_for

from . import ai, data
from .alerts import subscribe as sns_subscribe
from .personas import PERSONAS
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


def _plan_args():
    return {
        "persona_id": request.args.get("persona", "school"),
        "area_id": request.args.get("area", "anand-vihar"),
        "stage": request.args.get("stage"),
        "day": request.args.get("day", "today"),
    }


def _log_plan(plan):
    log.info(
        "plan persona=%s area=%s stage=%s source=%s demo=%s",
        plan["persona"]["id"], plan["area"]["id"], plan["stage"]["label"],
        plan["stage"]["source"], plan["is_demo"],
    )


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    @app.context_processor
    def globals_():
        return {"personas": PERSONAS, "areas": data.AREAS, "roman": ROMAN, "ai_enabled": ai.enabled()}

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/plan")
    def plan_page():
        args = _plan_args()
        try:
            plan = get_plan(**args)
        except ValueError as exc:
            return render_template("error.html", message=str(exc)), 400
        _log_plan(plan)
        return render_template("plan.html", plan=plan, args=args)

    @app.get("/poster")
    def poster():
        args = _plan_args()
        try:
            plan = get_plan(**args)
        except ValueError as exc:
            return render_template("error.html", message=str(exc)), 400
        return render_template("poster.html", plan=plan, args=args)

    @app.get("/api/plan")
    def api_plan():
        try:
            plan = get_plan(**_plan_args())
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
        store = get_store()
        key = ai.cache_key(plan, lang)
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
            plan = get_plan(**_plan_args())
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
            plan = get_plan(**_plan_args())
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        text = _summary(plan, lang)
        audio = ai.speak(text, lang) if text else None
        if not audio:
            return jsonify({"error": "No audio right now."}), 502
        return jsonify({"audio": audio, "text": text})

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
