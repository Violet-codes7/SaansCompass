import re
import json

import boto3
import pytest
from moto import mock_aws

from saans import data
from saans.web import create_app


@pytest.fixture
def client(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    monkeypatch.delenv("TOPIC_ARN", raising=False)
    return create_app().test_client()


def test_index_asks_for_the_daily_trip(client):
    html = client.get("/").get_data(as_text=True)
    assert 'name="job"' in html and 'name="persona"' not in html
    for part in ('name="from"', 'name="to"', 'name="travel"', "Use my live location", 'name="area" value=""'):
        assert part in html
    assert 'name="commute"' not in html


@pytest.mark.parametrize("persona", ["school", "rider", "older"])
def test_plan_page_shows_rules_first(client, persona):
    resp = client.get(f"/plan?persona={persona}&area=ito")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    body = html[html.index("</nav>", html.index('class="sections"')):]  # after the section bar
    assert body.index("GRAP rules for you") < body.index("At a glance") < body.index("Your health")
    assert "Check the official order" in html
    assert "Not medical advice" in html or "not medical advice" in html


def test_api_plan_json(client):
    body = client.get("/api/plan?persona=rider&area=okhla&stage=III&day=tomorrow").get_json()
    assert body["persona"]["id"] == "rider" and body["stage"]["source"] == "official"
    assert body["stage"]["label"] == "III" and body["day"] == "tomorrow"
    assert {"rules", "activities", "hours", "dose", "best_window", "warnings"} <= body.keys()


@pytest.mark.parametrize("query", ["persona=pilot&area=ito", "persona=school&area=mars", "stage=9", "day=yesterday"])
def test_api_bad_input_is_400_with_allowed_values(client, query):
    resp = client.get(f"/api/plan?{query}")
    assert resp.status_code == 400
    assert "allowed" in resp.get_json()


def test_bad_input_page_is_400_and_escaped(client):
    resp = client.get("/plan?persona=<script>alert(1)</script>")
    assert resp.status_code == 400
    assert "<script>alert" not in resp.get_data(as_text=True)


def test_poster(client):
    html = client.get("/poster?persona=older&area=rohini").get_data(as_text=True)
    assert "Rohini" in html and "not an official order" in html
    for part in ("Today for you", "Your day, hour by hour", 'class="strip"', "Rules", "Do this today",
                 "Scan for the live plan", "<svg", "i18n.js"):
        assert part in html
    assert re.search(r"(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day \d\d \w+ 20\d\d", html)


def test_poster_qr_leaves_out_health_and_what_if(client):
    html = client.get("/poster?persona=rider&area=ito&stage=IV&age=70&cond=asthma").get_data(as_text=True)
    assert "Your health" in html  # the person asked for their own poster
    assert "/plan?persona=rider&amp;area=ito<" in html
    url = html.split('class="url"', 1)[1].split("</p>", 1)[0]
    assert "asthma" not in url and "age" not in url and "stage" not in url


def test_poster_lists_day_actions_not_rule_repeats(client):
    html = client.get("/poster?persona=rider&area=ito&stage=IV").get_data(as_text=True)
    todo = html.split('class="todo"', 1)[1].split("</section>", 1)[0]
    assert "Not allowed at this GRAP stage" not in todo and "<li>" in todo


def test_healthz(client):
    assert client.get("/healthz").get_json()["ok"] is True


def test_security_headers(client):
    resp = client.get("/")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_subscribe_without_topic_is_503(client):
    assert client.post("/subscribe", data={"email": "a@b.co", "area": "ito"}).status_code == 503


@mock_aws
def test_subscribe_creates_filtered_subscription(mem_store, monkeypatch):
    sns = boto3.client("sns", region_name="ap-south-1")
    topic = sns.create_topic(Name="alerts")["TopicArn"]
    monkeypatch.setenv("TOPIC_ARN", topic)
    monkeypatch.setattr("saans.web._sns", sns)
    client = create_app().test_client()

    resp = client.post("/subscribe", data={"email": "parent@example.com", "area": "rk-puram"})
    assert resp.status_code == 200 and "Check your inbox" in resp.get_data(as_text=True)
    subs = sns.list_subscriptions_by_topic(TopicArn=topic)["Subscriptions"]
    assert [s["Endpoint"] for s in subs] == ["parent@example.com"]
    attrs = sns.get_subscription_attributes(SubscriptionArn=subs[0]["SubscriptionArn"])["Attributes"]
    assert json.loads(attrs["FilterPolicy"]) == {"zone": ["rk-puram"]}

    assert client.post("/subscribe", data={"email": "not-an-email", "area": "ito"}).status_code == 400
    assert client.post("/subscribe", data={"email": "a@b.co", "area": "nowhere"}).status_code == 400


def test_lambda_handler_serves_http_api_v2_event(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    from saans.lambda_handler import handler
    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": "/api/plan",
        "rawQueryString": "persona=school&area=ito",
        "headers": {"host": "example.execute-api.ap-south-1.amazonaws.com"},
        "queryStringParameters": {"persona": "school", "area": "ito"},
        "requestContext": {
            "http": {"method": "GET", "path": "/api/plan", "protocol": "HTTP/1.1",
                     "sourceIp": "1.2.3.4", "userAgent": "test"},
            "stage": "$default",
        },
        "isBase64Encoded": False,
    }
    resp = handler(event, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["area"]["id"] == "ito"


def test_stage_links_poster_order_and_favicon(client):
    html = client.get("/plan?persona=school&area=ito&stage=0").get_data(as_text=True)
    assert "Try Stage IV" in html and "Not covered by GRAP at any stage" in html
    assert 'class="pill check_official_order"' not in html
    hard = client.get("/plan?persona=school&area=ito&stage=IV").get_data(as_text=True)
    assert "Try Stage IV" not in hard and "Set by the GRAP rules at Stage IV" in hard
    poster = client.get("/poster?persona=rider&area=ito&stage=IV").get_data(as_text=True)
    rules = poster[poster.index('class="rules"'):]
    assert rules.index("Not allowed") < rules.index("</ul>")
    calm = client.get("/poster?persona=school&area=ito&stage=0").get_data(as_text=True)
    assert "No GRAP stage today" in calm and "Check the official order" not in calm
    assert client.get("/favicon.ico").status_code == 301
    assert client.get("/static/favicon.svg").status_code == 200


def test_profile_page_and_personal_plan(client):
    index = client.get("/").get_data(as_text=True)
    assert 'name="age"' in index and 'name="cond"' in index and 'name="job"' in index and "Kidney disease" in index
    assert 'name="stage"' not in index and 'name="day"' not in index
    html = client.get("/plan?persona=school&area=ito&age=9&cond=asthma&commute=bus&stage=IV").get_data(as_text=True)
    assert "child, asthma" in html and "Keep your reliever inhaler" in html
    assert "Tomorrow" in html and "Back to the real stage" in html
    assert client.get("/plan?persona=school&area=ito&age=abc").status_code == 400


def test_personal_ai_advice_is_not_stored(client, monkeypatch, mem_store):
    from saans import ai
    monkeypatch.setenv("BEDROCK_MODEL", "anthropic.claude-opus-5-5")
    monkeypatch.setattr(ai, "summarize", lambda plan, lang: "Today: fine.")
    body = client.get("/api/summary?persona=rider&area=ito&cond=asthma").get_json()
    assert body["summary"] == "Today: fine."
    assert not any(sk == "TEXT" for _, sk in mem_store.items)
