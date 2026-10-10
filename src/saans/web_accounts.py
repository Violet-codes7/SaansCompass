"""Account pages: create an account, confirm the email, sign in and out,
reset a password, and the saved profile.

The saved profile holds the same fields as the form on the home page plus a
name and an "About me" note. It is stored in DynamoDB under the person's
Cognito id, read only for that signed-in person, never put in a link or a
log, and deleted with the account.
"""
from flask import g, make_response, redirect, render_template, request, url_for
from werkzeug.datastructures import MultiDict

from . import accounts, data, settings
from .profile import COMMUTE_MODES, WORK, clean_job, clean_text, parse_profile
from .store import get_store

ACCESS_COOKIE = "saans_at"
REFRESH_COOKIE = "saans_rt"
# Fields of a saved profile that parse_profile reads, in link-argument shape.
PROFILE_ARGS = ("age", "cond", "commute", "start", "end", "mask", "job")
FORM_ERRORS = accounts.TEXT["form_errors"]


def saved_profile():
    """The signed-in person's saved profile, or None."""
    if not g.get("user"):
        return None
    if "saved" not in g:
        g.saved = get_store().get_user_profile(g.user["sub"])
    return g.saved


def profile_from_saved(saved, persona_id):
    args = MultiDict([(k, v) for k in PROFILE_ARGS for v in (saved.get(k) if isinstance(saved.get(k), list)
                                                             else [saved.get(k)]) if v not in (None, "", False)])
    return parse_profile(args, persona_id, about=saved.get("about"))


def _set_cookie(resp, name, value, days):
    resp.set_cookie(name, value, max_age=days * 86400, httponly=True, secure=request.is_secure,
                    samesite="Lax", path="/")


def _clear_cookies(resp):
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        resp.delete_cookie(name, path="/")
    return resp


def _page(mode, status=200, **kw):
    return render_template("account.html", mode=mode, **kw), status


def register(app, read_work):
    @app.before_request
    def load_user():
        g.user = None
        if not accounts.enabled():
            return
        token = request.cookies.get(ACCESS_COOKIE)
        user = accounts.current_user(token) if token else None
        if user is None and request.cookies.get(REFRESH_COOKIE):
            token = accounts.refresh(request.cookies[REFRESH_COOKIE])
            user = accounts.current_user(token) if token else None
            if user:
                g.new_access = token
        g.user = user

    @app.after_request
    def keep_access_token(resp):
        if g.get("new_access"):
            _set_cookie(resp, ACCESS_COOKIE, g.new_access, settings.get("sign_in_days"))
        return resp

    @app.context_processor
    def account_globals():
        return {"accounts_on": accounts.enabled(), "user": g.get("user"), "saved": saved_profile()}

    @app.before_request
    def accounts_must_be_on():
        if request.endpoint and request.endpoint.startswith("account") and not accounts.enabled():
            return render_template("error.html", message=accounts.message("disabled")), 404

    @app.get("/account")
    def account():
        if g.user:
            return redirect(url_for("account_profile"))
        return _page(request.args.get("mode", "signin"))

    @app.post("/account/signup")
    def account_signup():
        email, name = request.form.get("email", ""), clean_text(request.form.get("name"), settings.get("name_max_chars"))
        if not name:
            return _page("signup", 400, error=FORM_ERRORS["name"], email=email)
        try:
            accounts.sign_up(email, request.form.get("password", ""), name)
        except accounts.AccountError as exc:
            return _page("signup", 400, error=str(exc), email=email, name=name)
        return _page("confirm", email=email, note=accounts.message("code_sent", email=email.strip().lower()))

    @app.post("/account/confirm")
    def account_confirm():
        email = request.form.get("email", "")
        try:
            accounts.confirm(email, request.form.get("code", ""))
        except accounts.AccountError as exc:
            return _page("confirm", 400, error=str(exc), email=email)
        return _page("signin", email=email, note=accounts.message("confirmed"))

    @app.post("/account/resend")
    def account_resend():
        email = request.form.get("email", "")
        try:
            accounts.resend(email)
        except accounts.AccountError as exc:
            return _page("confirm", 400, error=str(exc), email=email)
        return _page("confirm", email=email, note=accounts.message("code_sent", email=email.strip().lower()))

    @app.post("/account/signin")
    def account_signin():
        email = request.form.get("email", "")
        try:
            tokens = accounts.sign_in(email, request.form.get("password", ""))
        except accounts.AccountError as exc:
            mode = "confirm" if str(exc) == accounts.TEXT["errors"]["UserNotConfirmedException"] else "signin"
            return _page(mode, 400, error=str(exc), email=email)
        user = accounts.current_user(tokens["access"])
        has_profile = bool(user and get_store().get_user_profile(user["sub"]))
        resp = redirect(url_for("plan_page") if has_profile else url_for("account_profile"))
        days = settings.get("sign_in_days")
        _set_cookie(resp, ACCESS_COOKIE, tokens["access"], days)
        if tokens.get("refresh"):
            _set_cookie(resp, REFRESH_COOKIE, tokens["refresh"], days)
        return resp

    @app.post("/account/signout")
    def account_signout():
        token = request.cookies.get(ACCESS_COOKIE)
        if token:
            accounts.sign_out(token)
        return _clear_cookies(redirect(url_for("index")))

    @app.post("/account/forgot")
    def account_forgot():
        email = request.form.get("email", "")
        accounts.forgot(email)
        return _page("reset", email=email, note=accounts.message("reset_sent", email=email.strip().lower()))

    @app.post("/account/reset")
    def account_reset():
        email = request.form.get("email", "")
        try:
            accounts.reset(email, request.form.get("code", ""), request.form.get("password", ""))
        except accounts.AccountError as exc:
            return _page("reset", 400, error=str(exc), email=email)
        return _page("signin", email=email, note=accounts.message("password_changed"))

    @app.route("/account/profile", methods=["GET", "POST"])
    def account_profile():
        if not g.user:
            return redirect(url_for("account"))
        saved = saved_profile() or {}
        if request.method == "GET":
            return render_template("profile.html", p=saved, note=request.args.get("note"))
        form = request.form
        p = {
            "name": clean_text(form.get("name"), settings.get("name_max_chars")) or g.user["name"],
            "job": clean_job(form.get("job")),
            "age": form.get("age") or None,
            "cond": [c for c in form.getlist("cond") if c],
            "commute": form.get("commute") or None,
            "start": form.get("start") or None,
            "end": form.get("end") or None,
            "mask": form.get("mask") == "1",
            "area": form.get("area") or settings.get("default_area"),
            "about": clean_text(form.get("about"), settings.get("about_me_max_chars")),
            "persona": form.get("persona") or "",
        }
        error = None
        if not p["job"]:
            error = FORM_ERRORS["job"]
        elif p["area"] not in data.AREAS:
            error = FORM_ERRORS["area"]
        elif p["persona"] and p["persona"] not in WORK:
            error = FORM_ERRORS["persona"]
        elif p["commute"] and p["commute"] not in COMMUTE_MODES:
            error = FORM_ERRORS["commute"]
        if not error:
            if not p["persona"]:  # read the work description, as the home page does
                reading = read_work(p["job"])
                p["persona"], p["read"] = reading["persona"], reading["how"]
                if reading["start_hour"] is not None and not (p["start"] or p["end"]):
                    p["start"], p["end"] = str(reading["start_hour"]), str(reading["end_hour"])
            else:
                p["read"] = "picked"
            try:
                profile_from_saved(p, p["persona"])  # same checks as a plan link
            except ValueError as exc:
                error = str(exc)[0].upper() + str(exc)[1:] + "."
        if error:
            return render_template("profile.html", p=p, error=error), 400
        get_store().put_user_profile(g.user["sub"], p)
        return redirect(url_for("plan_page"))

    @app.post("/account/delete")
    def account_delete():
        if not g.user:
            return redirect(url_for("account"))
        get_store().delete_user_profile(g.user["sub"])
        try:
            accounts.delete(request.cookies.get(ACCESS_COOKIE, ""))
        except accounts.AccountError as exc:
            return render_template("error.html", message=str(exc)), 502
        return _clear_cookies(make_response(_page("signin", note=accounts.message("deleted"))))
