import pytest

from saans import accounts, ai, data, web
from saans.web_accounts import ACCESS_COOKIE, REFRESH_COOKIE


class CognitoError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeCognito:
    """Just enough of the cognito-idp API for the web flows."""

    def __init__(self):
        self.users, self.tokens, self.calls = {}, {}, []

    def sign_up(self, ClientId, Username, Password, UserAttributes):
        assert ClientId == "client-123"
        if Username in self.users:
            raise CognitoError("UsernameExistsException")
        if len(Password) < 8:
            raise CognitoError("InvalidPasswordException")
        attrs = {a["Name"]: a["Value"] for a in UserAttributes}
        self.users[Username] = {"password": Password, "confirmed": False, "sub": f"sub-{len(self.users)}", **attrs}
        return {"UserSub": self.users[Username]["sub"]}

    def confirm_sign_up(self, ClientId, Username, ConfirmationCode):
        if ConfirmationCode != "123456":
            raise CognitoError("CodeMismatchException")
        self.users[Username]["confirmed"] = True

    def resend_confirmation_code(self, ClientId, Username):
        self.calls.append(("resend", Username))

    def initiate_auth(self, ClientId, AuthFlow, AuthParameters):
        if AuthFlow == "REFRESH_TOKEN_AUTH":
            email = self.tokens.get(AuthParameters["REFRESH_TOKEN"])
            if not email:
                raise CognitoError("NotAuthorizedException")
            return {"AuthenticationResult": {"AccessToken": self._token(email, "at2")}}
        u = self.users.get(AuthParameters["USERNAME"])
        if not u or u["password"] != AuthParameters["PASSWORD"]:
            raise CognitoError("NotAuthorizedException")
        if not u["confirmed"]:
            raise CognitoError("UserNotConfirmedException")
        email = AuthParameters["USERNAME"]
        return {"AuthenticationResult": {"AccessToken": self._token(email, "at"), "RefreshToken": self._token(email, "rt")}}

    def _token(self, email, kind):
        token = f"{kind}-{email}-{len(self.tokens)}"
        self.tokens[token] = email
        return token

    def get_user(self, AccessToken):
        email = self.tokens.get(AccessToken)
        if not email or not AccessToken.startswith("at"):
            raise CognitoError("NotAuthorizedException")
        u = self.users[email]
        return {"Username": u["sub"], "UserAttributes": [
            {"Name": "sub", "Value": u["sub"]}, {"Name": "email", "Value": email}, {"Name": "name", "Value": u["name"]}]}

    def global_sign_out(self, AccessToken):
        email = self.tokens.get(AccessToken)
        self.tokens = {t: e for t, e in self.tokens.items() if e != email}

    def delete_user(self, AccessToken):
        email = self.tokens.pop(AccessToken)
        del self.users[email]

    def forgot_password(self, ClientId, Username):
        if Username not in self.users:
            raise CognitoError("UserNotFoundException")

    def confirm_forgot_password(self, ClientId, Username, ConfirmationCode, Password):
        if ConfirmationCode != "123456":
            raise CognitoError("CodeMismatchException")
        self.users[Username]["password"] = Password


@pytest.fixture
def cognito(monkeypatch):
    monkeypatch.setenv("USER_POOL_CLIENT_ID", "client-123")
    fake = FakeCognito()
    accounts.set_client(fake)
    yield fake
    accounts.set_client(None)


@pytest.fixture
def client(mem_store, monkeypatch, live_fetcher, cognito):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    monkeypatch.setattr(web, "_work_cache", {})
    return web.create_app().test_client()


PROFILE = {"name": "Asha", "job": "I deliver food on a scooter", "age": "66", "cond": ["asthma", "heart"],
           "from": "Rohini Sector 9", "to": "Connaught Place", "travel": "scooter", "area": "",
           "start": "", "end": "", "persona": "",
           "about": "I look after my grandson after school and ride past the Rohini landfill."}


def sign_up_and_in(client, email="asha@example.com", password="secret123"):
    client.post("/account/signup", data={"name": "Asha", "email": email, "password": password})
    client.post("/account/confirm", data={"email": email, "code": "123456"})
    return client.post("/account/signin", data={"email": email, "password": password})


def test_accounts_are_off_without_a_client_id(mem_store, monkeypatch):
    monkeypatch.delenv("USER_POOL_CLIENT_ID", raising=False)
    c = web.create_app().test_client()
    assert c.get("/account").status_code == 404
    assert "Sign in" not in c.get("/").get_data(as_text=True)


def test_sign_up_confirm_and_sign_in(client, cognito):
    html = client.post("/account/signup", data={"name": "Asha", "email": "Asha@Example.com ", "password": "secret123"}
                       ).get_data(as_text=True)
    assert "We sent a 6-digit code to asha@example.com" in html
    bad = client.post("/account/confirm", data={"email": "asha@example.com", "code": "000000"})
    assert bad.status_code == 400 and "That code is not right" in bad.get_data(as_text=True)
    ok = client.post("/account/confirm", data={"email": "asha@example.com", "code": "123456"}).get_data(as_text=True)
    assert "Sign in to set up your profile" in ok
    wrong = client.post("/account/signin", data={"email": "asha@example.com", "password": "nope"})
    assert wrong.status_code == 400 and "Wrong email or password" in wrong.get_data(as_text=True)
    resp = client.post("/account/signin", data={"email": "asha@example.com", "password": "secret123"})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/account/profile")
    cookies = resp.headers.getlist("Set-Cookie")
    assert any(c.startswith(ACCESS_COOKIE) and "HttpOnly" in c and "SameSite=Lax" in c for c in cookies)
    assert any(c.startswith(REFRESH_COOKIE) for c in cookies)
    assert "Welcome, Asha" in client.get("/").get_data(as_text=True)


def test_unconfirmed_sign_in_asks_for_the_code(client):
    client.post("/account/signup", data={"name": "Ravi", "email": "ravi@example.com", "password": "secret123"})
    resp = client.post("/account/signin", data={"email": "ravi@example.com", "password": "secret123"})
    assert resp.status_code == 400 and "Code from the email" in resp.get_data(as_text=True)


def test_duplicate_and_weak_sign_ups_get_plain_errors(client):
    sign_up_and_in(client)
    dup = client.post("/account/signup", data={"name": "A", "email": "asha@example.com", "password": "secret123"})
    assert "already exists" in dup.get_data(as_text=True)
    weak = client.post("/account/signup", data={"name": "B", "email": "b@example.com", "password": "short"})
    assert weak.status_code == 400 and "at least 8 characters" in weak.get_data(as_text=True)


def test_saved_profile_drives_plan_and_poster_without_link_details(client, mem_store):
    sign_up_and_in(client)
    resp = client.post("/account/profile", data=PROFILE)
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/plan")
    saved = mem_store.get_user_profile("sub-0")
    assert saved["persona"] == "rider" and saved["read"] == "keywords" and saved["area"] == "rohini"
    assert saved["to_area"] == "ito" and saved["commute"] == "two_wheeler"
    html = client.get("/plan").get_data(as_text=True)
    assert "Edit profile" in html and "Your trips" in html and "Rohini" in html
    assert "We read you as" not in html and 'name="persona"' not in html
    assert '<h1 translate="no">Asha</h1>' in html  # the person's name, not the persona
    assert "Air quality at ITO" in html  # the day is spent at the destination
    assert "Asthma" in html and "Age 66" in html
    poster = client.get("/poster").get_data(as_text=True)
    assert "Asha" in poster and "Your health" in poster
    url = poster.split('class="url"', 1)[1].split("</p>", 1)[0]
    assert "asthma" not in url and "66" not in url
    assert "grandson" not in poster  # About me is for the AI only
    # The profile page shows what was saved.
    form = client.get("/account/profile").get_data(as_text=True)
    assert 'value="asthma" checked' in form and "grandson" in form and 'value="Rohini Sector 9"' in form and 'name="area" value="rohini"' in form
    # A link that names someone else still works as before.
    other = client.get("/plan?persona=school&area=ito").get_data(as_text=True)
    assert "From your saved profile" not in other


def test_about_me_reaches_the_ai_facts_only_for_the_signed_in_person(client, monkeypatch):
    sign_up_and_in(client)
    client.post("/account/profile", data=PROFILE)
    seen = {}
    monkeypatch.setattr(ai, "enabled", lambda: True)
    monkeypatch.setattr(ai, "summarize", lambda plan, lang="en": seen.setdefault("facts", ai.plan_facts(plan)) and "ok")
    assert client.get("/api/summary").get_json()["summary"] == "ok"
    assert "grandson" in seen["facts"]["profile"]["about_me"]


def test_about_me_is_not_logged(client, caplog):
    caplog.set_level("INFO")
    sign_up_and_in(client)
    client.post("/account/profile", data=PROFILE)
    client.get("/plan")
    assert "grandson" not in caplog.text and "asthma" not in caplog.text


def test_profile_needs_sign_in_and_valid_fields(client):
    assert client.get("/account/profile").headers["Location"].endswith("/account")
    sign_up_and_in(client)
    bad = client.post("/account/profile", data={**PROFILE, "job": ""})
    assert bad.status_code == 400 and "Tell us what you do" in bad.get_data(as_text=True)
    bad = client.post("/account/profile", data={**PROFILE, "age": "200"})
    assert bad.status_code == 400 and "Age must be between 1 and 110" in bad.get_data(as_text=True)
    picked = client.post("/account/profile", data={**PROFILE, "persona": "older"})
    assert picked.status_code == 302


def test_expired_access_token_is_refreshed(client, cognito):
    sign_up_and_in(client)
    client.post("/account/profile", data=PROFILE)
    cognito.tokens = {t: e for t, e in cognito.tokens.items() if not t.startswith("at-")}  # access token expired
    accounts.set_client(cognito)  # drop the cached user
    resp = client.get("/plan")
    assert '<h1 translate="no">Asha</h1>' in resp.get_data(as_text=True)
    assert any(c.startswith(ACCESS_COOKIE + "=at2") for c in resp.headers.getlist("Set-Cookie"))


def test_sign_out_and_delete(client, cognito, mem_store):
    sign_up_and_in(client)
    client.post("/account/profile", data=PROFILE)
    resp = client.post("/account/signout")
    assert any(c.startswith(ACCESS_COOKIE + "=;") for c in resp.headers.getlist("Set-Cookie"))
    assert "Welcome" not in client.get("/").get_data(as_text=True)
    sign_up_and_in(client)
    html = client.post("/account/delete").get_data(as_text=True)
    assert "account and saved profile are deleted" in html
    assert mem_store.get_user_profile("sub-0") is None and "asha@example.com" not in cognito.users


def test_password_reset(client, cognito):
    sign_up_and_in(client)
    html = client.post("/account/forgot", data={"email": "nobody@example.com"}).get_data(as_text=True)
    assert "If an account exists" in html  # never says whether the account exists
    client.post("/account/reset", data={"email": "asha@example.com", "code": "123456", "password": "newpass123"})
    assert cognito.users["asha@example.com"]["password"] == "newpass123"


def test_home_asks_nothing_the_saved_profile_has(client, mem_store):
    guest = client.get("/").get_data(as_text=True)
    assert 'name="job"' in guest and 'action="/plan"' in guest and "data-draft>" in guest
    sign_up_and_in(client)
    new = client.get("/").get_data(as_text=True)  # signed in, no profile: the form saves it
    assert 'method="post" action="/account/profile"' in new and "Save and show my plan" in new
    assert "Answer these once" in new and "data-draft>" not in new
    client.post("/account/profile", data=PROFILE)
    html = client.get("/").get_data(as_text=True)
    assert 'name="job"' not in html and 'name="age"' not in html and 'name="cond"' not in html
    assert "Welcome back, Asha." in html and "Age 66" in html and "Delivery or gig rider" in html
    # today's trip stays editable, prefilled from the profile
    assert "Today&#39;s trip" in html and 'value="Rohini Sector 9"' in html and 'name="to_area" value="ito"' in html
    assert "Tell us a little about you" not in html


def test_profile_page_shows_the_sign_up_name_folded(client):
    sign_up_and_in(client)
    html = client.get("/account/profile").get_data(as_text=True)
    assert "Shown as Asha" in html and 'value="Asha"' in html and "<details class=\"fix name-fix\">" in html
    assert "saans-draft" in html  # fills in what the home page form was told in this tab


def test_todays_trip_changes_the_plan_not_the_profile(client, mem_store):
    sign_up_and_in(client)
    client.post("/account/profile", data=PROFILE)
    html = client.get("/plan?from=Dwarka&area=&to=Connaught+Place&to_area=ito&travel=scooter&commute=two_wheeler"
                      "&modes=two_wheeler", follow_redirects=True).get_data(as_text=True)
    assert "Dwarka → ITO" in html and '<h1 translate="no">Asha</h1>' in html  # still the saved person
    assert mem_store.get_user_profile("sub-0")["area"] == "rohini"


def test_poster_shows_the_name_only(client):
    sign_up_and_in(client)
    client.post("/account/profile", data=PROFILE)
    html = client.get("/poster").get_data(as_text=True)
    assert '<b translate="no">Asha</b></p>' in html and "<small" not in html.split('class="who"')[1].split("</p>")[0]


def test_plan_header_has_no_occupation_text(client):
    sign_up_and_in(client)
    client.post("/account/profile", data=PROFILE)
    html = client.get("/plan").get_data(as_text=True)
    head = html[html.index('<section class="summary">'):html.index("</section>", html.index('<section class="summary">'))]
    assert "Asha" in head and "Rohini → ITO" in head and "Edit profile" in head
    assert "Delivery or gig rider" not in head and "I deliver food" not in head and 'class="role"' not in head


TOWNS = {"gurgaon": (28.4595, 77.0266, "Gurugram"), "rewari": (28.1928, 76.6191, "Rewari")}


def test_todays_trip_outside_our_areas_is_used_as_typed(client, mem_store, monkeypatch):
    monkeypatch.setattr(data, "geocode", lambda text, session=None: TOWNS.get(text.strip().lower()))
    sign_up_and_in(client)
    client.post("/account/profile", data=PROFILE)  # saved: Rohini -> Connaught Place by scooter
    resp = client.get("/plan?from=gurgaon&area=&to=rewari&to_area=&travel=bus&commute=&modes=")
    loc = resp.headers["Location"]
    assert resp.status_code == 302 and "area=p-" in loc and "to_area=p-" in loc and "commute=bus" in loc
    html = client.get(loc).get_data(as_text=True)
    head = html[html.index('<section class="summary">'):html.index('<div class="stage-box')]
    assert "Gurugram → Rewari · Bus" in head and "Rohini" not in head and "Air quality at Rewari" in html
    assert mem_store.get_user_profile("sub-0")["area"] == "rohini"  # the profile is not changed
    assert "28.19" not in loc and "76.6" not in loc  # no coordinates in the link


def test_a_place_that_cannot_be_found_is_said_not_replaced(client, mem_store):
    sign_up_and_in(client)
    client.post("/account/profile", data=PROFILE)
    html = client.get("/plan?from=Rohini+Sector+9&area=rohini&to=Atlantis&to_area=&travel=bus&commute=bus&modes=bus",
                      follow_redirects=True).get_data(as_text=True)
    assert "We could not find &#34;Atlantis&#34; in India" in html and "Connaught Place" not in html
    assert "Air quality at Rohini" in html  # no destination today: the start's air


def test_a_day_in_one_place_has_no_trip(client, mem_store):
    sign_up_and_in(client)
    client.post("/account/profile", data={**PROFILE, "stay": "1"})
    saved = mem_store.get_user_profile("sub-0")
    assert saved["stay"] and saved["commute"] == "none" and not saved["to_area"] and not saved["to"]
    html = client.get("/plan").get_data(as_text=True)
    assert "All day at Rohini" in html and "Your trips" not in html and "When you set out" not in html
    home = client.get("/").get_data(as_text=True)
    assert 'name="stay" value="1" checked' in home and "Where you are all day" in home
    # Today's trip can still go somewhere, for this plan only.
    trip = client.get("/plan?from=Rohini+Sector+9&area=rohini&to=ITO&to_area=ito&travel=bus&commute=bus&route_read=picked")
    assert "Your trips" in trip.get_data(as_text=True)


def test_diary_keeps_a_week_under_the_account(client, mem_store):
    assert "Sign in to keep a weekly diary" in client.get("/plan?persona=school&area=ito").get_data(as_text=True)
    sign_up_and_in(client)
    client.post("/account/profile", data=PROFILE)
    html = client.get("/plan").get_data(as_text=True)
    assert "Did you follow today&#39;s plan?" in html and "Answer each day" in html
    resp = client.post("/diary?route_read=picked", data={"followed": "yes"})
    assert resp.status_code == 302 and "#health" in resp.headers["Location"]
    diary = mem_store.get_diary("sub-0")
    assert list(diary.values())[0]["followed"] == "yes"
    page = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "followed your plan on 1 of the last 7 days" in page and "Saved for" in page
    assert client.post("/diary", data={"followed": "maybe"}).status_code == 302
    assert len(mem_store.get_diary("sub-0")) == 1
    client.post("/account/delete")
    assert mem_store.get_diary("sub-0") == {}
