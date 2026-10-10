"""Alert Lambda: invoked by EventBridge Scheduler with {"run": "today"} in the
morning and {"run": "tomorrow"} in the evening (hours set in template.yaml)."""
import json
import logging
import os

import boto3

from .alerts import run_alert_check
from .store import get_store

logging.getLogger().setLevel(logging.INFO)

_sns = None


def _client():
    global _sns
    if _sns is None:
        _sns = boto3.client("sns")
    return _sns


def handler(event, context):
    run = (event or {}).get("run", "today")
    results, errors = run_alert_check(
        run,
        store=get_store(),
        sns=_client(),
        topic_arn=os.environ["TOPIC_ARN"],
        site_url=os.environ.get("SITE_URL") or None,
    )
    print(json.dumps({"run": run, "results": results}))
    if errors:
        # Fail the invocation so the CloudWatch alarm on Errors fires.
        raise RuntimeError(f"alert check failed for: {', '.join(errors)}")
    return {"run": run, "results": results}
