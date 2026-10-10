import json

import boto3
import pytest
from moto import mock_aws

from conftest import FIXED_NOW, make_hours
from saans import data, store
from saans.alerts import run_alert_check, subscribe, verdict_fingerprint

TABLE = "saans-test"


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    with mock_aws():
        ddb = boto3.resource("dynamodb")
        ddb.create_table(
            TableName=TABLE,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                  {"AttributeName": "sk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                       {"AttributeName": "sk", "KeyType": "RANGE"}],
        )
        sns = boto3.client("sns")
        topic = sns.create_topic(Name="alerts")["TopicArn"]
        yield store.DynamoStore(TABLE, ddb), sns, topic


class Recorder:
    """Wraps the moto SNS client and remembers what was published."""

    def __init__(self, sns, fail_for=()):
        self.sns, self.fail_for, self.published = sns, set(fail_for), []

    def publish(self, **kwargs):
        zone = kwargs["MessageAttributes"]["zone"]["StringValue"]
        if zone in self.fail_for:
            raise RuntimeError("SNS down")
        self.published.append(kwargs)
        return self.sns.publish(**kwargs)


def test_sends_once_then_only_on_change(aws, live_fetcher):
    ddb_store, sns, topic = aws
    rec = Recorder(sns)
    results, errors = run_alert_check("today", ddb_store, rec, topic, now=FIXED_NOW, fetcher=live_fetcher,
                                      site_url="https://x.example")
    assert errors == []
    assert {r["status"] for r in results} == {"sent"}
    assert len(rec.published) == len(data.AREAS)
    first = rec.published[0]
    assert first["MessageAttributes"]["zone"] == {"DataType": "String", "StringValue": "anand-vihar"}
    assert len(first["Subject"]) <= 100
    assert "https://x.example/plan?area=anand-vihar&day=today" in first["Message"]

    # Same air, second run: nothing sent.
    rec.published.clear()
    results, _ = run_alert_check("today", ddb_store, rec, topic, now=FIXED_NOW, fetcher=live_fetcher)
    assert {r["status"] for r in results} == {"unchanged"} and rec.published == []

    # Much cleaner air for one area later: that area changes.
    clean = make_hours([20] * 24)

    def fetch(area):
        return clean if area.id == "lodhi-road" else live_fetcher(area)

    later = FIXED_NOW.replace(hour=11)  # past the 30-minute cache
    results, _ = run_alert_check("today", ddb_store, rec, topic, now=later, fetcher=fetch)
    sent = [r["area"] for r in results if r["status"] == "sent"]
    assert sent == ["lodhi-road"]


def test_failed_publish_is_retried_next_run(aws, live_fetcher):
    ddb_store, sns, topic = aws
    rec = Recorder(sns, fail_for={"ito"})
    results, errors = run_alert_check("today", ddb_store, rec, topic, now=FIXED_NOW, fetcher=live_fetcher)
    assert errors == ["ito"]
    assert ddb_store.get_alert_state("ito", "today") is None

    rec.fail_for.clear()
    rec.published.clear()
    results, errors = run_alert_check("today", ddb_store, rec, topic, now=FIXED_NOW, fetcher=live_fetcher)
    assert errors == [] and [p["MessageAttributes"]["zone"]["StringValue"] for p in rec.published] == ["ito"]


def test_no_forecast_never_emails(aws, failing_fetcher):
    ddb_store, sns, topic = aws
    rec = Recorder(sns)
    results, errors = run_alert_check("tomorrow", ddb_store, rec, topic, now=FIXED_NOW, fetcher=failing_fetcher)
    assert rec.published == [] and errors == []
    assert {r["status"] for r in results} == {"skipped_no_forecast"}


def test_stale_forecast_never_emails(aws, live_fetcher, failing_fetcher):
    from datetime import timedelta
    ddb_store, sns, topic = aws
    rec = Recorder(sns)
    run_alert_check("today", ddb_store, rec, topic, now=FIXED_NOW, fetcher=live_fetcher)
    rec.published.clear()
    later = FIXED_NOW + timedelta(hours=2)
    results, _ = run_alert_check("today", ddb_store, rec, topic, now=later, fetcher=failing_fetcher)
    assert rec.published == [] and {r["status"] for r in results} == {"skipped_stale_forecast"}


def test_bad_run_rejected(aws):
    ddb_store, sns, topic = aws
    with pytest.raises(ValueError):
        run_alert_check("yesterday", ddb_store, sns, topic)


def test_fingerprint_ignores_small_aqi_changes():
    plan = {"stage": {"stage": 2}, "persona": {"id": "school"}, "verdict": "limit",
            "best_window": {"start": "13:00", "avg_aqi": 150}, "rules": []}
    wobble = json.loads(json.dumps(plan))
    wobble["best_window"]["avg_aqi"] = 158
    assert verdict_fingerprint([plan]) == verdict_fingerprint([wobble])
    wobble["verdict"] = "stay_in"
    assert verdict_fingerprint([plan]) != verdict_fingerprint([wobble])


def test_subscribe_validates_email(aws):
    _, sns, topic = aws
    with pytest.raises(ValueError):
        subscribe(sns, topic, "x" * 250 + "@a.co", "ito")


def test_alert_handler_raises_when_an_area_fails(aws, live_fetcher, monkeypatch):
    ddb_store, sns, topic = aws
    monkeypatch.setenv("TOPIC_ARN", topic)
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    store.set_store(ddb_store)
    from saans import alert_handler
    monkeypatch.setattr(alert_handler, "_sns", Recorder(sns, fail_for={"okhla"}))
    try:
        with pytest.raises(RuntimeError, match="okhla"):
            alert_handler.handler({"run": "today"}, None)
        assert ddb_store.get_alert_state("ito", "today") is not None
    finally:
        store.set_store(None)
