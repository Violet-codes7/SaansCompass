"""Storage for the forecast cache and the last alert sent per area.

One DynamoDB table with a generic pk/sk holds both item types:

    pk AREA#<area>  sk FCST#<date>         hours (JSON), fetched_at, ttl
    pk AREA#<area>  sk FCST#LAST           the last real forecast, kept longer
    pk AREA#<area>  sk LAST#today|tomorrow verdict_hash, summary, sent_at

When the TABLE environment variable is not set (local runs and tests without
moto), an in-memory store with the same interface is used.
"""
import json
import os
import time

from . import settings


class MemoryStore:
    def __init__(self):
        self.items = {}

    def _get(self, pk, sk):
        return self.items.get((pk, sk))

    def _put(self, item):
        self.items[(item["pk"], item["sk"])] = item

    # forecast cache
    def _get_hours(self, area_id, sk, now):
        item = self._get(f"AREA#{area_id}", sk)
        now = now if now is not None else time.time()
        # DynamoDB deletes expired items lazily, so expiry is checked on read too.
        if not item or int(item["ttl"]) <= now:
            return None
        return {"hours": json.loads(item["hours"]), "is_stale": False, "fetched_at": item["fetched_at"]}

    def _put_hours(self, area_id, sk, forecast, ttl_seconds, now):
        now = now if now is not None else time.time()
        self._put({
            "pk": f"AREA#{area_id}",
            "sk": sk,
            "hours": json.dumps(forecast["hours"]),
            "fetched_at": forecast["fetched_at"],
            "ttl": int(now) + ttl_seconds,
        })

    def get_forecast(self, area_id, date_key, now=None):
        return self._get_hours(area_id, f"FCST#{date_key}", now)

    def put_forecast(self, area_id, date_key, forecast, now=None):
        self._put_hours(area_id, f"FCST#{date_key}", forecast, settings.get("forecast_cache_minutes") * 60, now)

    def get_last_forecast(self, area_id, now=None):
        """The last real forecast, for when the live source is down."""
        return self._get_hours(area_id, "FCST#LAST", now)

    def put_last_forecast(self, area_id, forecast, now=None):
        self._put_hours(area_id, "FCST#LAST", forecast, settings.get("last_forecast_hours") * 3600, now)

    # small text cache (AI summaries), keyed by content hash
    def get_text(self, key, now=None):
        item = self._get(key, "TEXT")
        now = now if now is not None else time.time()
        if not item or int(item["ttl"]) <= now:
            return None
        return item["text"]

    def put_text(self, key, text, ttl_seconds=None, now=None):
        now = now if now is not None else time.time()
        ttl_seconds = ttl_seconds if ttl_seconds is not None else settings.get("advice_cache_hours") * 3600
        self._put({"pk": key, "sk": "TEXT", "text": text, "ttl": int(now) + ttl_seconds})

    # alert state
    def get_alert_state(self, area_id, run):
        item = self._get(f"AREA#{area_id}", f"LAST#{run}")
        if not item:
            return None
        return {"verdict_hash": item["verdict_hash"], "summary": item["summary"], "sent_at": item["sent_at"]}

    def put_alert_state(self, area_id, run, verdict_hash, summary, sent_at):
        self._put({
            "pk": f"AREA#{area_id}",
            "sk": f"LAST#{run}",
            "verdict_hash": verdict_hash,
            "summary": summary,
            "sent_at": sent_at,
        })


class DynamoStore(MemoryStore):
    def __init__(self, table_name, resource=None):
        import boto3

        resource = resource or boto3.resource("dynamodb")
        self.table = resource.Table(table_name)

    def _get(self, pk, sk):
        return self.table.get_item(Key={"pk": pk, "sk": sk}).get("Item")

    def _put(self, item):
        self.table.put_item(Item=item)


_store = None


def get_store():
    global _store
    if _store is None:
        table = os.environ.get("TABLE")
        _store = DynamoStore(table) if table else MemoryStore()
    return _store


def set_store(store):
    """Replace the process-wide store (used by tests)."""
    global _store
    _store = store
