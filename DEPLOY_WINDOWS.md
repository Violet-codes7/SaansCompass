# Deploy Saans Compass from Windows

About 20 minutes the first time. Run every command in **PowerShell** from the project folder. Never paste keys or passwords into chat.

## 0. AWS account and student credits (once)
1. Create an AWS account at https://aws.amazon.com (a card is required even with credits).
2. Turn on MFA for the root user: account menu → Security credentials → Assign MFA device.
3. Apply your credits: in AWS Builder Center open your student rewards and copy the credit code, then in the console go to Billing and Cost Management → Credits → **Redeem credit**, paste it and submit. The credit then shows in that list with its expiry date and eligible services.
4. Create your everyday user: IAM → Users → Create user `violet-admin`, tick "Provide access to the AWS Management Console", attach **AdministratorAccess**, create. Copy the sign-in URL it shows.
5. Sign out and sign back in at that URL as `violet-admin`. Use this user from now on, not root.

Credits do not always cover every service. Check the "Eligible services" on the credit. The Gemini API is billed by Google, not AWS, and its free tier is enough for this app. If you use Bedrock instead, Amazon Nova is billed by AWS itself, while Claude may be billed through AWS Marketplace, which credits often do not cover. The optional BudgetEmail at deploy warns you before spend passes $1.

## 1. Install the tools (once)
1. **AWS CLI v2**: download and run https://awscli.amazonaws.com/AWSCLIV2.msi
2. **SAM CLI**: download and run the 64-bit installer from https://github.com/aws/aws-sam-cli/releases/latest/download/AWS_SAM_CLI_64_PY3.msi
3. Close PowerShell and open a new one so both are on PATH. Check:
   ```powershell
   aws --version
   sam --version
   ```

## 2. Get the latest code
```powershell
cd <your AirCompass folder>
git pull
py -3.12 -m venv C:\venv312          # once; needs Python 3.12 from python.org (see below)
C:\venv312\Scripts\Activate.ps1
python --version                      # must say 3.12.x
pip install -r requirements-dev.txt
```
The Lambda runs Python 3.12, so `sam build` needs 3.12 on PATH. A venv made from the Microsoft Store's Python 3.13 will not work. Get 3.12 from https://www.python.org/downloads/windows/ (the latest "Python 3.12" Windows installer, 64-bit), tick "Add python.exe to PATH" and keep the "py launcher" option. You can keep 3.13 installed alongside it.
If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

## 3. Sign in to AWS
```powershell
aws login --region ap-south-1
```
A browser opens; sign in with your normal AWS console user (not root if you can avoid it). Then check:
```powershell
aws sts get-caller-identity
```
It should print your account number. If your CLI says `login` is not a command, update the CLI (step 1.1), or use `aws configure sso`.

## 4. Amazon Bedrock with Amazon Nova (the default, about 2 minutes)
Personal advice, the Ask Saans chat and reading the "What do you do?" box run on Amazon Nova Lite through Amazon Bedrock, paid from your AWS credits. There is no API key: the Lambda uses its own IAM role, and Nova needs no Anthropic form, so it works on the Free plan.

1. Console → **Amazon Bedrock**, region **Asia Pacific (Mumbai)** → **Model catalog** → search "Nova" → open **Amazon Nova Lite** → **Open in playground**, type `hello` and send. A reply means your account can use it.
2. Deploy (step 5). The defaults are `AiProvider=bedrock` and `BedrockModel=apac.amazon.nova-lite-v1:0`.
3. Test: open `<SiteUrl>api/summary?persona=rider&area=ito`. You should see `"by": "Amazon Nova on Bedrock"`.

For longer, richer advice use **Amazon Nova Pro**: try it in the playground, then deploy with `sam deploy --parameter-overrides BedrockModel=apac.amazon.nova-pro-v1:0`. To use Claude instead, your account needs a paid plan and Anthropic's use-case form; then pass its model ID the same way.

**If it says not available**, run `sam logs -n WebFunction --stack-name saans-compass --start-time "10min ago"` and look for:
- `AccessDeniedException`: the account cannot use that model yet. Open it in the playground once (step 1).
- `ValidationException` or `ResourceNotFoundException`: the model ID is wrong or not offered in Mumbai. Copy the ID from the model page's **Cross-region inference** tab.
- `ThrottlingException`: wait a minute; answers are cached after the first one.

What is sent: the plan's decisions, the age and health conditions picked, and the "What do you do?" text. No names or emails. Bedrock does not use it to train models.

## 4b. Or use Google Gemini (optional)
Google Gemini powers the Personal advice panel and reads the "What do you do?" box. The site works without it: a keyword match reads the box and the advice panel stays hidden.

1. Open https://aistudio.google.com/apikey and sign in with any Google account.
2. Click **Create API key** (pick or create any project when asked) and copy the key. Never paste it into chat or into a file in the repo.
3. In PowerShell, store it in AWS as an encrypted parameter. The first line asks you to paste the key, so it never lands in your command history:
   ```powershell
   $k = Read-Host "Paste your Gemini API key"
   aws ssm put-parameter --name /saans-compass/gemini-api-key --type SecureString --value $k --overwrite --region ap-south-1
   Remove-Variable k
   ```
   It prints a `Version` number when it worked.
4. Deploy (step 5) with `sam deploy --parameter-overrides AiProvider=gemini`. The site reads the key from that parameter.
5. Test it: open `<SiteUrl>api/summary?persona=rider&area=ito`. You should see `{"summary": ..., "by": "Google Gemini"}`. If the site was already running, allow 5 minutes for it to pick up a new key.

**If it says not available**, run `sam logs -n WebFunction --stack-name saans-compass --start-time "10min ago"` and look for:
- `gemini key not available`: step 3 did not run, or used a different name or region.
- `gemini returned 400` with "API key not valid": copy the key again and repeat step 3.
- `gemini returned 404`: the model name changed. Run `sam deploy --guided`, press Enter through everything, and set **Parameter GeminiModel** to a current model id from AI Studio.
- `gemini returned 429`: every Gemini model in `gemini_model` and `gemini_fallback_models` is out of free quota. A model that hits its quota is skipped for a minute and the next one answers; answers are cached after the first one.

Gemini's free tier lets Google use what is sent to improve its products. The app sends no names or emails, only the plan, the age and health conditions picked, and the "What do you do?" text.

## 4c. Turn on CPCB's official AQI (once, about 5 minutes)
With this, "AQI now" is CPCB's live reading from the nearest monitoring station, the same number the CPCB AQI dashboard and the Sameer app show for that station, and Delhi's GRAP average uses every CPCB station in Delhi. Without it the site uses the forecast model. Websites like IQAir use the US AQI scale, so their numbers are higher and won't match.

1. Sign up at https://data.gov.in (**Sign Up**, top right), verify your email and log in.
2. Open **My Account** and copy your **API key**. Never paste it into chat or into a file in the repo.
3. In PowerShell:
   ```powershell
   $k = Read-Host "Paste your data.gov.in API key"
   aws ssm put-parameter --name /saans-compass/datagov-api-key --type SecureString --value $k --overwrite --region ap-south-1
   Remove-Variable k
   ```
   It prints a `Version` number when it worked.
4. Deploy (step 5). Readings refresh every 10 minutes; CPCB itself updates each station once an hour.

## 4d. Backup for CPCB readings: aqicn.org (optional, about 2 minutes)
When data.gov.in is down (`cpcb feed failed: ConnectionError` in the logs), the site can read the same CPCB station through aqicn.org instead and convert it to India's AQI scale. aqicn.org gives each pollutant on the US scale, not the raw µg/m³, so the site turns PM2.5 and PM10 back into µg/m³ and works out India's AQI from them. It uses the station's latest hourly reading, while CPCB and Sameer show a 24-hour average, so it will not match Sameer exactly: it is usually in the same AQI category, and can be further off when the air is changing fast.

1. Get a free token at https://aqicn.org/data-platform/token (enter your email and name, then confirm the email).
2. Copy the token from the email, then in PowerShell:
   ```powershell
   $t = (Get-Clipboard).Trim()
   aws ssm put-parameter --name /saans-compass/waqi-token --type SecureString --value $t --overwrite --region ap-south-1
   Remove-Variable t
   ```
3. Deploy (step 5). The "Now" dial then says "CPCB, ITO station · 19:00 IST · aqicn".

## 4e. Pollution map and Cleaner route (nothing to do)
`sam deploy` creates an Amazon Location Service API key for the base map (`saans-compass-map`) and lets the web Lambda ask Amazon Location for routes. Both use the aqicn.org token from 4d for station readings. To turn either off, deploy with `--parameter-overrides AirMap=off` or `CleanRoute=off` (add them to the other overrides you use).

## 5. Build and deploy
Keep the `C:\venv312` venv active (sam build uses the Python 3.12 on PATH).
```powershell
sam build
sam deploy --guided
```
Answer the questions like this:

| Question | Answer |
|---|---|
| Stack Name | `saans-compass` (press Enter) |
| AWS Region | `ap-south-1` (press Enter) |
| Parameter BudgetEmail | your email (gets a warning if spend passes $0.80), or Enter to skip |
| Parameter AlarmEmail | your email, or Enter to skip |
| Parameter AiProvider | press Enter (keeps `bedrock`), or `gemini` if you did step 4b |
| Parameter GeminiModel | press Enter (keeps `gemini-flash-latest`) |
| Parameter BedrockModel | press Enter (keeps `apac.amazon.nova-lite-v1:0`), or another model ID |
| Parameter BedrockRegion | press Enter (`ap-south-1`) |
| Confirm changes before deploy | `y` |
| Allow SAM CLI IAM role creation | `y` |
| Disable rollback | `n` |
| WebFunction has no authentication. Is this okay? | `y` (it is a public website; asked once per route) |
| Save arguments to configuration file | `y`, then Enter for the defaults |

When it shows the change set, type `y`. At the end it prints **Outputs**. Copy `SiteUrl` and send it in the thread.

Next time you only need `sam build` and `sam deploy` (no `--guided`).

## 6. Test the alert
1. Open the `SiteUrl`, open a plan, enter your email under alerts and subscribe.
2. Click the confirmation link in the email from AWS Notifications.
3. Send an alert now:
   ```powershell
   sam remote invoke AlertFunction --stack-name saans-compass --event-file events/today.json
   ```
   An area only emails when its plan changed since the last run, so the first run always sends.

## If something fails
- **`sam build` fails on a long path:** make sure LongPathsEnabled is on (we did this for pip), or move the project to a short folder like `C:\ac`.
- **`sam build` says Python 3.12 not found:** activate the venv first (step 2).
- **Deploy fails with "not authorized":** your AWS user needs admin rights for the deploy.
- **Personal advice says "not available":** Bedrock access (step 4) is not on, or the Gemini key (step 4b) is missing; follow "If it says not available" there.
- Anything else: paste the last 20 lines of the error in the thread (no keys).

## Remove everything after the hackathon
```powershell
sam delete --stack-name saans-compass
```
