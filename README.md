# Saans Compass

Saans Compass tells a Delhi resident two things on a bad-air day: what the official GRAP rules say, and what makes sense for their own body and routine. It is our entry for the Air track of Environmental Hacks (Bharat Builds Tour, WeMakeDevs x AWS, 8–11 Oct 2026).

- **Rules first.** The GRAP stage (the stage CAQM declared, the one you set, or an estimate from AQI) is checked against rules written as [Cedar](https://www.cedarpolicy.com/) policies. Every answer names the policy behind it. An activity no verified rule covers says **"Check the official order"**, never "Allowed".
- **Your profile, in your own words.** Write what you do ("I deliver food on a scooter at night"). Google Gemini reads it into the closest kind of day (school, delivery rider, outdoor or construction worker, office commuter, retired, runner) and any hours it mentions; without an AI key a keyword match does the same. The plan says "We read you as: …" and lets you correct it. Then add age, 16 air-related health conditions (asthma, COPD, bronchitis, TB, COVID, allergies, sinusitis, sore eyes, heart, stroke, anaemia, diabetes, kidney disease, weak immunity, pregnancy, smoking), how you travel, your outdoor hours and whether you have an N95. Each condition sets how much stricter your thresholds are, whether GRAP's Stage IV charter for sensitive groups applies to you, and its own "why, what to do, watch for" advice. The profile lives in the page link only: nothing is stored.
- **Automatic day and stage.** The plan opens on today, or on tomorrow after 8 PM IST, with both as tabs. The GRAP stage is the one CAQM declared (Parameter Store) or else an estimate from the PM2.5/PM10 forecast; "Try Stage III / IV" shows a bad-air day for demos.
- **Rules in plain words.** Each GRAP answer says what it means for you, why the rule exists and what to do instead, with a ladder showing where today's stage sits. The official clause and Cedar policy id stay one click away.
- **Health plan second.** The hourly Open-Meteo forecast becomes a plan: verdict and what it means, best and worst hours, commute AQI, tomorrow compared with today, your limits, a rough breath dose and a cigarette-equivalent.
- **Personal advice and Hindi.** Google Gemini writes four short lines of personal advice (Claude on Amazon Bedrock is a one-parameter switch), and Amazon Polly reads them aloud. The model only rephrases: every rule decision stays on the page, unchanged. The English / हिंदी switch at the top converts the whole page with Amazon Translate, falling back to a built-in dictionary for headings and labels.
- **Alerts.** Subscribe by email for an area. At 06:00 and 19:00 IST a scheduled Lambda checks every area and emails only where the plan changed.

Advisory only. Not medical advice and not an official order; CAQM declares the GRAP stage.

## Architecture

| Piece | AWS service |
|---|---|
| Website and JSON API | Lambda (Flask via `apig-wsgi`) behind API Gateway HTTP API, throttled |
| Scheduled checks | EventBridge Scheduler, `Asia/Kolkata` 06:00 (today) and 19:00 (tomorrow), invoking the Alert Lambda |
| Email alerts | SNS topic; each subscription filters on `zone` = area |
| Forecast cache, last alert sent | DynamoDB, one on-demand table, TTL |
| Declared GRAP stage | SSM Parameter Store, `/saans-compass/official-stage` |
| Personal advice, reading your work | Google Gemini API (key in Parameter Store as a SecureString); Amazon Bedrock (Claude Opus 5.5) when `AiProvider=bedrock` |
| Voice | Amazon Polly (Kajal, en-IN and hi-IN) |
| Hindi page | Amazon Translate (`translate:TranslateText`), cached in Lambda memory only |
| Packaging | SAM / CloudFormation, code in the SAM-managed S3 bucket |
| Ops | X-Ray tracing, a CloudWatch dashboard, CloudWatch logs (14 days), alarm on Alert Lambda errors, `DemoDataFallback` metric, optional $1 budget |

```
src/saans/
  aqi.py        CPCB-style AQI from PM2.5/PM10 (hourly = estimate)
  stage.py      GRAP stage: your override, CAQM's declared stage (Parameter Store), or estimate
  rules.py      Cedar evaluation -> Allowed / Not allowed / Check the official order
  rules/        schema.cedarschema + one .cedar file per persona
  personas.py   school, rider, older adult: hours, activities, effort
  dose.py       PM2.5 x breathing rate x minutes
  advisor.py    hour-by-hour plan, best window, verdict
  data.py       9 Delhi areas, Open-Meteo fetch (3 s timeout), demo fallback
  store.py      DynamoDB (or in-memory locally)
  service.py    the pipeline shared by web and alerts
  alerts.py     per-area change detection, SNS publish and subscribe
  ai.py         advice and work reading (Gemini, or Claude on Bedrock), Polly voice
  profile.py    age, conditions, travel, hours; keyword fallback for "what do you do"
  explain.py    plain-language text for every GRAP rule, stage and AQI category
  i18n.py       English to Hindi: built-in dictionary, then Amazon Translate
  web.py        routes; lambda_handler.py and alert_handler.py are the entry points
```

Routes: `/`, `/plan`, `/api/plan`, `/api/summary`, `/api/speak`, `POST /api/translate`, `/poster`, `POST /subscribe`, `/healthz`. Query: `job` (your own words) or `persona` (school, rider, worker, commuter, older, athlete), `area`, `stage` (0, I–IV, optional), `day` (today, tomorrow); `lang` (en, hi) for the summary routes.

## Which GRAP stage is used

1. The stage you pick on the page (`stage=`), shown as "Official (you set it)".
2. For today, the stage stored in Parameter Store, shown as "Declared by CAQM". When CAQM announces a stage, one command updates every page and the next alert run:
   ```bash
   aws ssm put-parameter --overwrite --name /saans-compass/official-stage --value III   # or unset
   ```
3. Otherwise an estimate from the day's AQI, shown as "Estimate from AQI".

## AI summary

`ai.py` sends the model only a small JSON of the plan's decisions (persona, area, stage, verdict, best window, each rule's decision, actions, and the profile picked on the form). The system prompt tells it to write four short lines, never soften a rule, and invent nothing. Advice without a profile is cached in DynamoDB for 6 hours; personal advice stays in Lambda memory only. If the model is off, fails or declines, the page shows the plan without advice. `AiProvider` picks `gemini` (default; key in the SecureString parameter `/<stack>/gemini-api-key`), `bedrock` or `off`.

## Where the rules come from

The Cedar policies in `src/saans/rules/` are written from CAQM's GRAP schedule for NCR, **Revision 29.09.2026**. Each policy carries `@clause` (stage and item number) and `@status("verified")`. Stages are cumulative, as the schedule's paragraph 4 says, so a Stage III rule is `context.stage >= 3`.

- Schedule actions become **Not allowed** (forbid) or **Allowed** (permit where no action at that stage restricts the activity).
- Citizen-charter advice, such as Stage IV's "children and the elderly avoid outdoor activities", becomes **Advised against** (`@kind("advisory")`), because it advises but does not restrict.
- Anything the schedule does not cover says **Check the official order**. Examples are the school commute, and a rider's shift at Stage IV, where item 5 lets states add measures such as odd-even.
- A policy marked `@status("draft")` also shows "Check the official order".

When CAQM revises GRAP, edit the policies and their tests in `tests/test_rules.py`. The code does not change.

## Run locally

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                                   # unit tests, AWS mocked with moto
cd src && flask --app "saans.web:create_app()" run   # http://127.0.0.1:5000
```

Without AWS variables the app uses an in-memory cache, the subscribe form says alerts are not set up, and the AI panel is hidden. To try the summary locally with your own AWS sign-in, set `BEDROCK_MODEL=anthropic.claude-opus-5-5` and `BEDROCK_REGION=ap-south-1` before `flask run`. If the forecast cannot be reached, pages show a **Demo data** banner, and the alert run never emails demo data.

## Deploy (region ap-south-1)

Needs the AWS CLI, SAM CLI and Python 3.12. On Windows, follow [DEPLOY_WINDOWS.md](DEPLOY_WINDOWS.md).

```bash
aws configure sso          # or any credentials for the deploying user
sam build
sam deploy --guided        # stack saans-compass, ap-south-1; optional BudgetEmail and AlarmEmail
```

The `SiteUrl` output is the public URL. To send an alert on demand (for the demo):

```bash
sam remote invoke AlertFunction --stack-name saans-compass --event-file events/today.json
```

An area only emails when its plan changed since the last run for that day type. Subscribers must click the SNS confirmation email first.

GitHub Actions runs the tests and `cfn-lint` on every push. Deploys from `main` switch on once the repository variable `AWS_DEPLOY_ROLE_ARN` points at an IAM role that trusts GitHub's OIDC provider; no AWS keys are stored in GitHub.

## Honest limits

- Hourly AQI is an estimate: CPCB breakpoints are defined on 24-hour averages.
- The forecast is a model (Open-Meteo), not a ground station.
- The GRAP stage shown is an estimate unless you set it or the declared stage is stored in Parameter Store.
- The summary is written by a language model from the plan's facts; the rules table beside it is the source of truth.
- Activity thresholds and breath dose are our own heuristics, not medical advice.
- Rules follow the GRAP schedule; the stage actually in force is declared by CAQM, and Delhi departments may issue extra orders.

## Credits

Advice by risk group from Canada's AQHI; cleaner-time idea from London's Clean Air Routes; school flags from the US school Air Quality Flag Program; policy as code with Cedar; forecast from [Open-Meteo](https://open-meteo.com/) (CC BY 4.0).

## License

MIT
