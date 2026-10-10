# Saans Compass

Saans Compass tells a Delhi resident two things on a bad-air day: what the official GRAP rules say, and what makes sense for their own body and routine. It is our entry for the Air track of Environmental Hacks (Bharat Builds Tour, WeMakeDevs x AWS, 8–11 Oct 2026).

- **Rules first.** The GRAP stage (the stage CAQM declared, the one you set, or an estimate from AQI) is checked against rules written as [Cedar](https://www.cedarpolicy.com/) policies. Every answer names the policy behind it. An activity no verified rule covers says **"Check the official order"**, never "Allowed".
- **Your profile, in your own words.** Write what you do ("I deliver food on a scooter at night"). Google Gemini reads it into the closest kind of day (school, delivery rider, outdoor or construction worker, office commuter, retired, runner) and any hours it mentions; without an AI key a keyword match does the same. The plan says "We read you as: …" and lets you correct it. Then add age, 16 air-related health conditions (asthma, COPD, bronchitis, TB, COVID, allergies, sinusitis, sore eyes, heart, stroke, anaemia, diabetes, kidney disease, weak immunity, pregnancy, smoking), how you travel, your outdoor hours and whether you have an N95. Each condition sets how much stricter your thresholds are, whether GRAP's Stage IV charter for sensitive groups applies to you, and its own "why, what to do, watch for" advice. Without an account the profile lives in the page link only and nothing is stored.
- **Your daily trip.** Instead of one area, say where you start, where you go and how you travel, in your own words ("Mayur Vihar Phase 1", "DPS R K Puram", "Metro, then an e-rickshaw"). Gemini turns the places into approximate coordinates and the words into ways of travelling; without an AI key, area names, well-known localities and travel words are matched instead. "Use my live location" asks the browser for your position and picks the nearest area we cover; the coordinates are used for that one answer and never saved, logged or put in a link. The hour-by-hour plan uses the air where you spend the day, and "Your trips" shows the air at the start, at the areas near the way, and at the destination, when you leave and when you come back, with a warning when a trip is above your limit.
- **Accounts (optional).** Sign up with email and password (Amazon Cognito, with an email code), save your name, age, work, health conditions, area, travel and an "About me" note once, and the plan, poster and home page open with them every time. Gemini reads "About me" to fit the advice to your life. The saved profile is stored in DynamoDB under your account only, never put in a link, QR code or log, and is deleted with your account from the profile page.
- **Automatic day and stage.** The plan opens on today, or on tomorrow after 8 PM IST, with both as tabs. The GRAP stage is the one CAQM declared (Parameter Store) or else an estimate from the PM2.5/PM10 forecast; "Try Stage III / IV" shows a bad-air day for demos.
- **One AQI everywhere.** The area's AQI on the plan, the poster, the stage box and the air dials is the same figure: the last 24 hours today (as CPCB reports it), or the forecast day average for tomorrow. The only other number is Delhi's average, labelled as the figure GRAP is set on.
- **GRAP rules fitted to you.** Your commute is judged by how you travel (metro and bus are never restricted; two-wheelers, autos, walking and cycling not before Stage IV), and "Your own vehicle" keeps only the rule for your car or goods vehicle, by fuel and BS level, for any kind of day. The section lists what it was fitted to, and says when GRAP's Stage IV indoor advice is meant for you.
- **GRAP stage for all of Delhi.** The stage follows Delhi's average AQI, not one neighbourhood. The GRAP section shows where Delhi stands on the stage scale, the cleanest and worst areas, how many points to the next stage, what tomorrow's forecast points to, the main actions of each stage (from the 29 Sep 2026 revision), how CAQM decides a stage and how accurate our estimate is.
- **Rules in plain words.** Each GRAP answer says what it means for you, why the rule exists and what to do instead, with a ladder showing where today's stage sits. The official clause and Cedar policy id stay one click away.
- **Health plan second.** The hourly Open-Meteo forecast becomes a plan: verdict and what it means, best and worst hours, commute AQI, tomorrow compared with today, your limits, a rough breath dose and a cigarette-equivalent. "Your day, hour by hour" draws a bar chart against your own limits and gives each hour a verdict in your persona's words ("Keep children indoors", "Short rides only"), tagged with your activities, the best or break window and the worst hour. Every bar is a button: tap an hour (or use the arrow keys) to open that hour's own card, with its AQI and your verdict, PM2.5 against the WHO guideline, PM10 and the main pollutant, that hour's temperature, humidity, wind and mixing height, which of your plans fall in it and how the GRAP rules treat them, what to do right now, and why the air is like that. The page opens on the current hour. The "Please read" notes fold into one line you can open.
- **Air and weather you can read.** The home page and plan show three AQI dials: the last 24 hours (the way CPCB reports AQI), this hour and tomorrow, each with its category, plus PM2.5 and PM10 in µg/m³ and how many times the WHO guideline they are. The weather dials are coloured by band: temperature with feels-like, humidity with dew point, wind with gusts and the direction it blows from, and mixing height (how high the air can mix; a low lid traps smoke near the ground). "Why it matters" says in one line what today's weather does to the air, including the north-west wind that carries crop-stubble smoke in October and November.
- **PM2.5 and PM10 explained.** A section explains each particle: today's level against the WHO and Indian limits, its size next to a human hair, how far it gets in the body, where it comes from, what it does within hours and over years, and how to protect yourself, with links to the WHO 2021 guidelines and the CPCB standards.
- **At a glance, for your area.** One panel leads with your area's AQI, your verdict, what shapes the air there and how it compares with Delhi's average, then your key times (best, worst, when you set out, tomorrow) and what to do, grouped into GRAP rules, timing, getting around, protecting your lungs, home and health. The AI's personal advice sits in the same panel. Signed in, the plan is headed with your name.
- **Your health, in depth.** What today's air means for you, your limits on a scale with your area's AQI marked, each condition's why, what to do and what to watch for, today's dose, a three-step "if you feel unwell" guide and everyday protection.
- **Daily poster.** One printable A4 page (or PDF) per area and persona: verdict, AQI dial, GRAP stage, best and worst time, hour strip, today's rules and actions, your health tips, in English or Hindi, with a QR code to the live plan. The QR link carries only the persona and area, never health details.
- **Personal advice and Hindi.** Google Gemini writes four short lines of personal advice (Claude or Amazon Nova on Amazon Bedrock is a one-parameter switch), and Amazon Polly reads them aloud. The model only rephrases: every rule decision stays on the page, unchanged. "Ask Saans" is a chat on the plan page, with "Ask about …" buttons on the GRAP rules, your health, each hour and the advice: it answers questions about your own plan in English or Hindi, using only the plan's facts, never changes a GRAP rule, sends people with emergency symptoms to 112, and saves nothing. The English / हिंदी switch at the top converts the whole page with Amazon Translate, falling back to a built-in dictionary for headings and labels.
- **Alerts.** Subscribe by email for an area. At 06:00 and 19:00 IST a scheduled Lambda checks every area and emails only where the plan changed.

Advisory only. Not medical advice and not an official order; CAQM declares the GRAP stage.

## Architecture

| Piece | AWS service |
|---|---|
| Website and JSON API | Lambda (Flask via `apig-wsgi`) behind API Gateway HTTP API, throttled |
| Scheduled checks | EventBridge Scheduler, `Asia/Kolkata` 06:00 (today) and 19:00 (tomorrow), invoking the Alert Lambda |
| Email alerts | SNS topic; each subscription filters on `zone` = area |
| Forecast cache, last alert sent, saved profiles | DynamoDB, one on-demand table, TTL |
| Sign-up and sign-in | Amazon Cognito user pool (email code, password reset); tokens in HttpOnly cookies |
| Declared GRAP stage | SSM Parameter Store, `/saans-compass/official-stage` |
| Personal advice, reading your work | Google Gemini API (key in Parameter Store as a SecureString); or, with `AiProvider=bedrock`, Amazon Bedrock: Claude Opus 5.5 through the Anthropic Messages API, or another Bedrock model such as Amazon Nova through the Converse API |
| Voice | Amazon Polly (Kajal, en-IN and hi-IN) |
| Hindi page | Amazon Translate (`translate:TranslateText`), cached in Lambda memory only |
| Packaging | SAM / CloudFormation, code in the SAM-managed S3 bucket |
| Ops | X-Ray tracing, a CloudWatch dashboard, CloudWatch logs (14 days), alarm on Alert Lambda errors, `StaleForecast` and `ForecastUnavailable` metrics, optional $1 budget |

```
src/saans/
  aqi.py        CPCB-style AQI from PM2.5/PM10 (hourly = estimate)
  stage.py      GRAP stage: your override, CAQM's declared stage (Parameter Store), or estimate
  rules.py      Cedar evaluation -> Allowed / Not allowed / Check the official order
  rules/        schema.cedarschema + one .cedar file per persona
  personas.py   school, rider, older adult: hours, activities, effort
  dose.py       PM2.5 x breathing rate x minutes
  advisor.py    hour-by-hour plan, best window, verdict
  data.py       Open-Meteo fetch, last-real-forecast fallback, honest "unavailable"
  store.py      DynamoDB (or in-memory locally)
  service.py    the pipeline shared by web and alerts
  alerts.py     per-area change detection, SNS publish and subscribe
  ai.py         advice and work reading (Gemini, or Amazon Bedrock), Polly voice
  profile.py    age, conditions, travel, hours; keyword fallback for "what do you do"
  explain.py    plain-language text for every GRAP rule, stage and AQI category
  i18n.py       English to Hindi: built-in dictionary, then Amazon Translate
  web.py        routes; lambda_handler.py and alert_handler.py are the entry points
  route.py      start, destination and travel: AI or keyword reading, nearest area, trips
  accounts.py   Amazon Cognito sign-up and sign-in; web_accounts.py has the account pages
  settings.py   reads config/; any setting can be overridden by an environment variable
  config/       settings.json plus the content: areas, AQI bands, personas, conditions,
                rule explanations, plan sentences, AI prompts, Hindi words
```

Routes: `/`, `/plan`, `/api/plan`, `/api/summary`, `/api/speak`, `POST /api/translate`, `/poster`, `POST /subscribe`, `/healthz`, and `/account` (sign up, confirm, sign in, reset) and `/account/profile`. Trip: `from`, `to`, `travel` (typed words, read once into `area`, `to_area`, `commute`, `modes`); `POST /api/locate` maps a browser location to the nearest area. Query: `job` (your own words) or `persona` (school, rider, worker, commuter, older, athlete), `area`, `stage` (0, I–IV, optional), `day` (today, tomorrow); `lang` (en, hi) for the summary routes.

## Which GRAP stage is used

1. The stage you pick on the page (`stage=`), shown as "What-if: set by you".
2. For today, the stage stored in Parameter Store, shown as "Declared by CAQM". When CAQM announces a stage, one command updates every page and the next alert run:
   ```bash
   aws ssm put-parameter --overwrite --name /saans-compass/official-stage --value III   # or unset
   ```
3. Otherwise an estimate from Delhi's city-wide AQI, shown as "Our estimate from Delhi's average AQI". Like CPCB's city AQI, it is the average of the 9 areas' 24-hour AQIs, so every area shows the same stage: GRAP is ordered for all of Delhi-NCR at once.

## Settings and content (no hardcoding)

Nothing the app says or decides with is buried in code. `src/saans/config/settings.json` holds the runtime settings (URLs, timeouts, cache times, default and dashboard area, alert personas and hours, AI model, Polly voice, time zone). Each key can be overridden by an environment variable of the same name in capitals, for example `DASHBOARD_AREA=dwarka`; `template.yaml` sets the main ones from deploy parameters (`DefaultArea`, `DashboardArea`, `AlertPersonas`, `MorningAlertHour`, `EveningAlertHour`, `AiProvider`, `GeminiModel`, `BedrockModel`, `Accounts`). The other files in `config/` hold the content: the 9 areas, CPCB AQI breakpoints, the 19 kinds of day (personas) and their hour-by-hour advice, health conditions, plain-language GRAP text, the plan's sentences and notes, the weather bands and wind directions, the PM2.5/PM10 limits, the AI prompts and the Hindi dictionary. Edit a file and redeploy; no Python changes needed.

## AI summary

`ai.py` sends the model only a small JSON of the plan's decisions (persona, area, stage, verdict, best window, each rule's decision, actions, and the profile picked on the form). The system prompt tells it to write four short lines, never soften a rule, and invent nothing. Advice without a profile is cached in DynamoDB for 6 hours; personal advice stays in Lambda memory only. If the model is off, fails or declines, the page shows the plan without advice. `AiProvider` picks `gemini` (default; key in the SecureString parameter `/<stack>/gemini-api-key`), `bedrock` or `off`. On Bedrock, `BedrockModel` picks the model: Claude ids (`anthropic.*`) go through the Anthropic Messages API on Bedrock with structured outputs; any other Bedrock model goes through the Converse API with the JSON schema in its prompt, and every answer is checked before use. Bedrock needs no API key: the Lambda's IAM role signs each call.

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

Without AWS variables the app uses an in-memory cache, the subscribe form says alerts are not set up, and the AI panel is hidden. To try the summary locally with your own AWS sign-in, set `BEDROCK_MODEL=anthropic.claude-opus-5-5` and `BEDROCK_REGION=ap-south-1` before `flask run`. If the forecast cannot be reached, the app uses the last real forecast it fetched (up to 48 hours old) with an **Older forecast** banner; with none, it says the forecast is unavailable instead of showing made-up numbers. Alerts are never sent from an old or missing forecast.

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

- The main AQI dial is a 24-hour average built from the last 24 forecast hours, as CPCB defines it; the "this hour" dial is an estimate, because CPCB breakpoints are defined on 24-hour averages. If fewer than 16 of those hours are known, the dial falls back to today's forecast average and says so.
- Weather and mixing height come from the Open-Meteo weather model, not a local station.
- The forecast is a model (Open-Meteo), not a ground station.
- The GRAP stage shown is an estimate unless you set it or the declared stage is stored in Parameter Store.
- The summary is written by a language model from the plan's facts; the rules table beside it is the source of truth.
- Activity thresholds and breath dose are our own heuristics, not medical advice.
- Rules follow the GRAP schedule; the stage actually in force is declared by CAQM, and Delhi departments may issue extra orders.

## Credits

Advice by risk group from Canada's AQHI; cleaner-time idea from London's Clean Air Routes; school flags from the US school Air Quality Flag Program; policy as code with Cedar; forecast from [Open-Meteo](https://open-meteo.com/) (CC BY 4.0).

## License

MIT
