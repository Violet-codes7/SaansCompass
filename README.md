# Saans Compass

Saans Compass turns the air where you are into a plan for your own day. It shows the air now, this hour and tomorrow, the best and worst hours for you, what your health means on a bad-air day and, in Delhi-NCR, what the GRAP rules allow. It is our entry for the Air track of Environmental Hacks (Bharat Builds Tour, WeMakeDevs x AWS, 8–11 Oct 2026).

Advisory only. Not medical advice and not an official order. In an emergency, call 112.

## What it does

- **Any place in India.** Type where you start, where you go and how you travel, in your own words ("Mayur Vihar Phase 1", "DPS R K Puram", "Metro, then an e-rickshaw", "Lalbagh, Lucknow"). The AI model turns the places into approximate coordinates and the words into ways of travelling; without the AI, known areas, towns and the Open-Meteo geocoder do it. As you type, the box suggests places with their state ("Aurangabad, Maharashtra" or "Aurangabad, Bihar"), and "Town, State" picks the right one. A typed place is kept under a short id: its coordinates never go in a link or a log. "Use my live location" picks the nearest Delhi area for that one answer and saves nothing.
- **The air from the best source available.** "Now" is the live reading of the nearest CPCB station (data.gov.in feed). When that feed is down, the same CPCB stations come through aqicn.org, converted back to India's AQI. Otherwise the dials use the Open-Meteo forecast model: the last 24 hours (the way CPCB reports AQI), this hour and tomorrow, with PM2.5 and PM10 against the WHO guideline. Implausible model dust (PM10 far above PM2.5) is held back so a model spike does not read as Severe.
- **Your place first.** Signed in, the air and weather section opens on the place in your profile. "Change place" switches it to where you are today, for that plan only, without touching the profile.
- **Your profile, in your own words.** Write what you do ("I deliver food on a scooter at night"). The AI reads it into the closest of 19 kinds of day (student, teacher, office worker, delivery rider, auto driver, street vendor, pregnant, retired and more) and the hours it mentions; a keyword match does the same without the AI. Add age, 16 air-related health conditions (asthma, COPD, heart disease, pregnancy, smoking and more), how you travel, your outdoor hours and whether you have an N95. Each condition makes your limits stricter and adds its own "why, what to do, watch for" advice.
- **A plan for your day.** At a glance: your area's AQI and verdict, your key times (best, worst, when you set out, tomorrow) and what to do, grouped by timing, getting around, protecting your lungs, home and health. "Your day, hour by hour" charts each hour against your own limits; tap an hour for its AQI, PM2.5, PM10, weather, your plans in it and what to do. "Your trips" shows the air at the start, on the way and at the destination, out and back. The plan opens on today, with tomorrow one tab away.
- **GRAP rules in Delhi-NCR.** For places in Delhi-NCR, the plan shows the GRAP stage (declared by CAQM, or estimated from Delhi's average AQI) and what it means for your activities, vehicle and way of travelling. Each answer is decided by a [Cedar](https://www.cedarpolicy.com/) policy and names its clause; anything no verified rule covers says **"Check the official order"**, never "Allowed". Outside Delhi-NCR there is no GRAP stage, so none is shown.
- **Ask Saans.** A chat on the plan page answers questions about your air and your day ("When is the best time for a run tomorrow?", "Can I take my car out?") from your plan's hourly figures and rules, and general questions on any other topic too. It never changes a rule decision, never diagnoses, sends emergency symptoms to 112, and saves nothing.
- **Personal advice, Hindi and voice.** The AI writes four short lines of advice fitted to your profile and "About me". The English / हिंदी switch converts the whole page (Amazon Translate, with a built-in dictionary for headings), and Amazon Polly reads the advice aloud.
- **Accounts (optional).** Sign up with email and password (Amazon Cognito). Your name, profile, places and "About me" are saved once in DynamoDB under your account only, never in a link, QR code or log, and are deleted with your account.
- **Daily poster and alerts.** A printable A4 poster (or PDF) per plan, with a QR code that carries only the kind of day and area. Email alerts for Delhi's areas: at 06:00 and 19:00 IST a scheduled Lambda checks each area and emails only where the plan changed.

## Architecture

| Piece | AWS service |
|---|---|
| Website and JSON API | Lambda (Flask via `apig-wsgi`) behind API Gateway HTTP API, throttled |
| Scheduled checks | EventBridge Scheduler, `Asia/Kolkata` 06:00 (today) and 19:00 (tomorrow), invoking the Alert Lambda |
| Email alerts | SNS topic; each subscription filters on `zone` = area |
| Forecast and station caches, typed places, last alert sent, saved profiles | DynamoDB, one on-demand table with TTL |
| Sign-up and sign-in | Amazon Cognito user pool (email code, password reset); tokens in HttpOnly cookies |
| Keys and the declared GRAP stage | SSM Parameter Store: `/saans-compass/gemini-api-key`, `/datagov-api-key`, `/waqi-token` (SecureStrings) and `/official-stage` |
| Personal advice, chat, reading your words | Google Gemini, or Amazon Bedrock (Amazon Nova through the Converse API, or Claude through the Messages API) |
| Voice and Hindi | Amazon Polly (Kajal, en-IN and hi-IN), Amazon Translate |
| Packaging | SAM / CloudFormation |
| Ops | X-Ray tracing, a CloudWatch dashboard, logs (14 days), alarm on Alert Lambda errors, forecast fallback metrics, optional budget |

Outside data: [Open-Meteo](https://open-meteo.com/) air quality, weather and geocoding (no key); CPCB station readings from [data.gov.in](https://data.gov.in/); [aqicn.org](https://aqicn.org/) as the station backup.

```
src/saans/
  web.py        routes; lambda_handler.py and alert_handler.py are the entry points
  service.py    the pipeline: forecast -> AQI -> stage -> rules -> plan
  data.py       Open-Meteo forecast and geocoding, typed places, last-real-forecast fallback
  cpcb.py       CPCB station AQI from data.gov.in; waqi.py is the aqicn.org backup
  aqi.py        India's AQI from PM2.5/PM10
  stage.py      GRAP stage: declared, set, estimated, or none outside Delhi-NCR
  rules.py      Cedar evaluation -> Allowed / Not allowed / Advised against / Check the official order
  rules/        schema.cedarschema and the .cedar policies
  advisor.py    hour-by-hour plan, best window, verdict; guide.py builds "At a glance"
  personas.py   the 19 kinds of day; profile.py has age, conditions, travel and hours
  route.py      start, destination and travel: AI, known places or geocoder; trips
  ai.py         advice, chat and reading your words (Gemini or Bedrock), Polly voice
  weather.py    weather dials and what the weather does to the air
  alerts.py     per-area change detection, SNS publish and subscribe
  accounts.py   Cognito sign-up and sign-in; web_accounts.py has the account pages
  i18n.py       English to Hindi: built-in dictionary, then Amazon Translate
  settings.py   reads config/; any setting can be overridden by an environment variable
  config/       settings.json plus all the content: areas, AQI bands, personas,
                conditions, rule explanations, plan sentences, AI prompts, Hindi words
```

Pages and API: `/`, `/plan`, `/poster`, `/account`, `/account/profile`, `GET /api/plan`, `GET /api/summary`, `POST /api/chat`, `GET /api/speak`, `POST /api/translate`, `GET /api/places` (place suggestions), `POST /api/locate`, `POST /subscribe`, `/healthz`.

## Settings and content (no hardcoding)

Nothing the app says or decides with is buried in code. `src/saans/config/settings.json` holds the runtime settings (sources, timeouts, cache times, which places are covered, when GRAP applies, AI models, alert hours). Each key can be overridden by an environment variable of the same name in capitals, for example `PLACE_REGION_KM=150` to cover only Delhi-NCR. The other files in `config/` hold the content. Edit a file and redeploy; no Python changes are needed.

Deploy parameters in `template.yaml`:

| Parameter | Default | What it does |
|---|---|---|
| `AiProvider` | `bedrock` | `gemini`, `bedrock` or `off` |
| `GeminiModel` | `gemini-flash-latest` | falls back to a lighter Gemini model when the quota runs out |
| `BedrockModel`, `BedrockRegion` | `apac.amazon.nova-lite-v1:0`, `ap-south-1` | `anthropic.*` ids use the Messages API, others the Converse API |
| `Grap` | `on` | GRAP stage and rules for Delhi-NCR places |
| `Accounts` | `on` | Cognito sign-up and saved profiles |
| `DefaultArea`, `DashboardArea`, `AlertPersonas`, `MorningAlertHour`, `EveningAlertHour` | | defaults for pages and alerts |
| `BudgetEmail`, `AlarmEmail` | empty | optional cost budget and alarm emails |

## Which GRAP stage is used (Delhi-NCR places)

1. For today, the stage stored in Parameter Store, shown as "Declared by CAQM". When CAQM announces a stage, one command updates every page and the next alert run:
   ```bash
   aws ssm put-parameter --overwrite --name /saans-compass/official-stage --value III   # or unset
   ```
2. Otherwise an estimate from Delhi's city-wide AQI: CPCB's average of Delhi's stations when the feed is up, else the average of the 9 areas' forecasts. GRAP is ordered for all of Delhi-NCR at once, so every NCR place shows the same stage.

The Cedar policies in `src/saans/rules/` are written from CAQM's GRAP schedule for NCR, **Revision 29.09.2026**. Each carries `@clause` and `@status("verified")`. Schedule actions become **Not allowed** or **Allowed**; citizen-charter advice becomes **Advised against**; anything the schedule does not cover, or a draft rule, says **Check the official order**. When CAQM revises GRAP, edit the policies and their tests; the code does not change.

## Run locally

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                                   # unit tests, AWS mocked
cd src && flask --app "saans.web:create_app()" run   # http://127.0.0.1:5000
```

Without AWS variables the app uses an in-memory store, and the AI, accounts and alerts are off. If the forecast cannot be reached, the app uses the last real forecast it fetched (up to 48 hours old) with a banner; with none, it says the forecast is unavailable instead of showing made-up numbers.

## Deploy (region ap-south-1)

Needs the AWS CLI, SAM CLI and Python 3.12. On Windows, follow [DEPLOY_WINDOWS.md](DEPLOY_WINDOWS.md), which also shows how to store the API keys in Parameter Store without pasting them anywhere.

```bash
sam build
sam deploy --guided        # stack saans-compass, ap-south-1
```

The `SiteUrl` output is the public URL. To send an alert on demand:

```bash
sam remote invoke AlertFunction --stack-name saans-compass --event-file events/today.json
```

GitHub Actions runs the tests and `cfn-lint` on every push, and can deploy from `main` through an IAM role trusted by GitHub's OIDC provider (repository variable `AWS_DEPLOY_ROLE_ARN`); no AWS keys are stored in GitHub.

## Privacy

- Without an account, the profile lives in the page link only and nothing is stored. Signed in, it is saved under your account only. Health details and "About me" are also sent to the AI model for the advice, and are never logged or put in a QR code.
- Live-location coordinates are used for one answer only: never stored, logged or put in a link. Typed places are kept as rounded coordinates under a hashed id for 90 days.
- Chat questions are never logged. API keys live in Parameter Store as SecureStrings; provider error text stays in the logs.

## Honest limits

- When no station reading is available, the AQI comes from the Open-Meteo forecast model, which can be far from what a ground station measures, especially for dust (PM10).
- The "this hour" dial is an estimate, because India's AQI is defined on 24-hour averages.
- Weather and mixing height come from the weather model, not a local station.
- The GRAP stage is an estimate unless CAQM's declared stage is stored in Parameter Store; Delhi-NCR is taken as within 150 km of Delhi, which is close to but not the official boundary. Departments may issue extra orders.
- Advice and chat answers are written by a language model from the plan's facts; the rule decisions beside them are the source of truth.
- Activity thresholds and the breath dose are our own heuristics, not medical advice.

## Credits

Advice by risk group from Canada's AQHI; cleaner-time idea from London's Clean Air Routes; school flags from the US school Air Quality Flag Program; policy as code with Cedar; forecast, weather and geocoding from [Open-Meteo](https://open-meteo.com/) (CC BY 4.0); station data from CPCB via data.gov.in and the World Air Quality Index project.

## License

MIT
