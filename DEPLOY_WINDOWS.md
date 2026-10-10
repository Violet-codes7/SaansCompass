# Deploy Saans Compass from Windows

About 20 minutes the first time. Run every command in **PowerShell** from the project folder. Never paste keys or passwords into chat.

## 0. AWS account and student credits (once)
1. Create an AWS account at https://aws.amazon.com (a card is required even with credits).
2. Turn on MFA for the root user: account menu → Security credentials → Assign MFA device.
3. Apply your credits: in AWS Builder Center open your student rewards and copy the credit code, then in the console go to Billing and Cost Management → Credits → **Redeem credit**, paste it and submit. The credit then shows in that list with its expiry date and eligible services.
4. Create your everyday user: IAM → Users → Create user `violet-admin`, tick "Provide access to the AWS Management Console", attach **AdministratorAccess**, create. Copy the sign-in URL it shows.
5. Sign out and sign back in at that URL as `violet-admin`. Use this user from now on, not root.

Credits do not always cover every service. Check the "Eligible services" on the credit. The Gemini API is billed by Google, not AWS, and its free tier is enough for this app. The optional BudgetEmail at deploy warns you before spend passes $1.

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

## 4. Turn on Gemini (once, about 3 minutes)
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
4. Deploy (step 5). The site reads the key from that parameter; there is nothing else to set.
5. Test it: open `<SiteUrl>api/summary?persona=rider&area=ito`. You should see `{"summary": ..., "by": "Google Gemini"}`. If the site was already running, allow 5 minutes for it to pick up a new key.

**If it says not available**, run `sam logs -n WebFunction --stack-name saans-compass --start-time "10min ago"` and look for:
- `gemini key not available`: step 3 did not run, or used a different name or region.
- `gemini returned 400` with "API key not valid": copy the key again and repeat step 3.
- `gemini returned 404`: the model name changed. Run `sam deploy --guided`, press Enter through everything, and set **Parameter GeminiModel** to a current model id from AI Studio.
- `gemini returned 429`: the free tier's per-minute limit. Wait a minute; answers are cached after the first one.

Gemini's free tier lets Google use what is sent to improve its products. The app sends no names or emails, only the plan, the age and health conditions picked, and the "What do you do?" text.

**Back to Claude on Bedrock later:** once AWS approves the Anthropic form, run `sam deploy --guided` and set **Parameter AiProvider** to `bedrock`.

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
| Parameter AiProvider | press Enter (keeps `gemini`) |
| Parameter GeminiModel | press Enter (keeps `gemini-flash-latest`) |
| Parameter BedrockModel | press Enter (only used when AiProvider is `bedrock`) |
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
- **Personal advice says "not available":** the Gemini key (step 4) is missing or wrong; follow "If it says not available" there.
- Anything else: paste the last 20 lines of the error in the thread (no keys).

## Remove everything after the hackathon
```powershell
sam delete --stack-name saans-compass
```
