# Saans Compass

Saans Compass tells a Delhi resident two things on a bad-air day: what the official GRAP rules say, and what makes sense for their own body and routine. It is our entry for the Air track of Environmental Hacks (Bharat Builds Tour, WeMakeDevs x AWS, 8–11 Oct 2026).

- **Rules first.** The GRAP stage (estimated from AQI, or the official stage you set) is checked against rules written as [Cedar](https://www.cedarpolicy.com/) policies. Every answer names the policy behind it. An activity no verified rule covers says **"Check the official order"**, never "Allowed".
- **Health plan second.** Pick a persona (school, delivery rider, older adult) and an area. The hourly Open-Meteo forecast becomes a plan: verdict, best time window, commute AQI and a rough breath dose.
- **Alerts.** Subscribe by email for an area. At 06:00 and 19:00 IST a scheduled Lambda checks every area and emails only where the plan changed.

Advisory only. Not medical advice and not an official order; CAQM declares the GRAP stage.

## Architecture

| Piece | AWS service |
|---|---|
| Website and JSON API | Lambda (Flask via `apig-wsgi`) behind API Gateway HTTP API, throttled |
| Scheduled checks | EventBridge Scheduler, `Asia/Kolkata` 06:00 (today) and 19:00 (tomorrow), invoking the Alert Lambda |
| Email alerts | SNS topic; each subscription filters on `zone` = area |
| Forecast cache, last alert sent | DynamoDB, one on-demand table, TTL |
| Packaging | SAM / CloudFormation, code in the SAM-managed S3 bucket |
| Ops | CloudWatch logs (14 days), alarm on Alert Lambda errors, `DemoDataFallback` metric, optional $1 budget |

```
src/saans/
  aqi.py        CPCB-style AQI from PM2.5/PM10 (hourly = estimate)
  stage.py      GRAP stage estimate and official override
  rules.py      Cedar evaluation -> Allowed / Not allowed / Check the official order
  rules/        schema.cedarschema + one .cedar file per persona
  personas.py   school, rider, older adult: hours, activities, effort
  dose.py       PM2.5 x breathing rate x minutes
  advisor.py    hour-by-hour plan, best window, verdict
  data.py       9 Delhi areas, Open-Meteo fetch (3 s timeout), demo fallback
  store.py      DynamoDB (or in-memory locally)
  service.py    the pipeline shared by web and alerts
  alerts.py     per-area change detection, SNS publish and subscribe
  web.py        routes; lambda_handler.py and alert_handler.py are the entry points
```

Routes: `/`, `/plan`, `/api/plan`, `/poster`, `POST /subscribe`, `/healthz`. Query: `persona` (school, rider, older), `area`, `stage` (0, I–IV, optional), `day` (today, tomorrow).

## The rules are drafts until checked against the CAQM order

Every policy in `src/saans/rules/` is `@status("draft")`: written from the structure of GRAP but not yet checked against the latest order from caqm.nic.in. The app shows "Check the official order" for any draft rule, while still citing it. To verify a rule, read its clause in the order, fill in `@clause` with the stage, item number and order date, and change it to `@status("verified")`. Tests fail if a policy is missing `@id` or `@clause`, or does not match the schema.

## Run locally

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                                   # unit tests, AWS mocked with moto
cd src && flask --app "saans.web:create_app()" run   # http://127.0.0.1:5000
```

Without AWS variables the app uses an in-memory cache and the subscribe form says alerts are not set up. If the forecast cannot be reached, pages show a **Demo data** banner, and the alert run never emails demo data.

## Deploy (region ap-south-1)

Needs the AWS CLI, SAM CLI and Python 3.12.

```bash
aws configure sso          # or any credentials for the deploying user
sam build
sam deploy --guided        # stack saans-compass, ap-south-1; optional BudgetEmail and AlarmEmail
```

The `SiteUrl` output is the public URL. To send an alert on demand (for the demo):

```bash
sam remote invoke AlertFunction --stack-name saans-compass --event '{"run": "today"}'
```

An area only emails when its plan changed since the last run for that day type. Subscribers must click the SNS confirmation email first.

GitHub Actions runs the tests and `cfn-lint` on every push. Deploys from `main` switch on once the repository variable `AWS_DEPLOY_ROLE_ARN` points at an IAM role that trusts GitHub's OIDC provider; no AWS keys are stored in GitHub.

## Honest limits

- Hourly AQI is an estimate: CPCB breakpoints are defined on 24-hour averages.
- The forecast is a model (Open-Meteo), not a ground station.
- The GRAP stage shown is an estimate unless you set the official one.
- Activity thresholds and breath dose are our own heuristics, not medical advice.
- Rules are drafts until checked against the official order (see above).

## Credits

Advice by risk group from Canada's AQHI; cleaner-time idea from London's Clean Air Routes; school flags from the US school Air Quality Flag Program; policy as code with Cedar; forecast from [Open-Meteo](https://open-meteo.com/) (CC BY 4.0).

## License

MIT
