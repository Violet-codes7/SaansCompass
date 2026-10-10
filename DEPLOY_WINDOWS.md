# Deploy Saans Compass from Windows

About 20 minutes the first time. Run every command in **PowerShell** from the project folder. Never paste keys or passwords into chat.

## 0. AWS account and student credits (once)
1. Create an AWS account at https://aws.amazon.com (a card is required even with credits).
2. Turn on MFA for the root user: account menu → Security credentials → Assign MFA device.
3. Apply your credits: in AWS Builder Center open your student rewards and copy the credit code, then in the console go to Billing and Cost Management → Credits → **Redeem credit**, paste it and submit. The credit then shows in that list with its expiry date and eligible services.
4. Create your everyday user: IAM → Users → Create user `violet-admin`, tick "Provide access to the AWS Management Console", attach **AdministratorAccess**, create. Copy the sign-in URL it shows.
5. Sign out and sign back in at that URL as `violet-admin`. Use this user from now on, not root.

Credits do not always cover every service. Check the "Eligible services" on the credit: Amazon Nova is billed by AWS itself, while Claude on Bedrock may be billed through AWS Marketplace, which credits often do not cover. The app makes very few AI calls, so either costs cents. The optional BudgetEmail at deploy warns you before spend passes $1.

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

## 4. Turn on Amazon Bedrock (once, about 5 minutes)
Amazon Bedrock powers the Personal advice panel and reads the "What do you do?" box. The Lambda signs in with its own IAM role, so there is no API key to create or store. The site works without it: a keyword match reads the box and the advice panel stays hidden.

You can use **Claude** (the default) or **Amazon Nova**. Claude needs a one-time form from Anthropic and a paid AWS plan; Nova needs neither.

1. **Check your AWS plan.** Billing and Cost Management → look for the plan banner. If it says **Free plan**, click **Upgrade plan** and confirm. Your credits still apply after upgrading. Claude on Bedrock is not available on the Free plan.
2. **Open Claude in Bedrock.** Console → Amazon Bedrock (region **Asia Pacific (Mumbai)**) → **Model catalog** → search "Claude" → open the Claude model you want (for example Claude Opus 5.5).
3. **Fill in the use-case form** if Bedrock asks for it. This happens once per account. A short description is enough, for example "Hackathon prototype giving air-quality advice to Delhi residents".
4. **Try it in the playground.** On the model page click **Open in playground**, type `hello` and send it. A reply means your account can use it. Copy the **model ID** shown on the model page.
5. **If the form says your account is not authorized,** open Support Center → **Create case** → **Account and billing** (free), and ask AWS to enable Anthropic models on Amazon Bedrock for your account. While you wait, use Amazon Nova:
   - Model catalog → search "Nova" → open **Amazon Nova Lite** (or Nova Pro) → **Open in playground** → send `hello`.
   - Copy its ID from the **Cross-region inference** tab. In Mumbai it is usually `apac.amazon.nova-lite-v1:0`.
6. Deploy (step 5) with that ID as **Parameter BedrockModel**.
7. Test it: open `<SiteUrl>api/summary?persona=rider&area=ito`. You should see `{"summary": ..., "by": "Claude on Amazon Bedrock"}` (or `"Amazon Nova on Bedrock"`).

**If it says not available**, run `sam logs -n WebFunction --stack-name saans-compass --start-time "10min ago"` and look for:
- `bedrock returned 403` or `AccessDeniedException`: the account cannot use that model yet. Repeat steps 1 to 5, or switch to Nova.
- `bedrock returned 404`, `ValidationException` or `ResourceNotFoundException`: the model ID is wrong or not offered in Mumbai. Copy the ID again from the model page, or set **Parameter BedrockRegion** to the region where the playground worked.
- `bedrock rate limited` or `ThrottlingException`: wait a minute; answers are cached after the first one.

What is sent: the plan's decisions, the age and health conditions picked, and the "What do you do?" text. No names or emails. Bedrock does not use it to train models.

**Removing the old Gemini key** (if you set one up earlier):
```powershell
aws ssm delete-parameter --name /saans-compass/gemini-api-key --region ap-south-1
```
Then delete the key itself at https://aistudio.google.com/apikey.

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
| Parameter AiProvider | press Enter (keeps `bedrock`) |
| Parameter BedrockModel | the model ID from step 4 (Enter keeps `anthropic.claude-opus-5-5`) |
| Parameter BedrockRegion | press Enter (`ap-south-1`), or the region where the playground worked |
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
- **Personal advice says "not available":** Bedrock access (step 4) is not on yet, or the model ID is wrong; follow "If it says not available" there.
- **Deploy says "Parameters: [GeminiModel] do not exist in the template":** your saved settings still name the old Gemini option. Run `sam deploy --guided` once and answer the questions again.
- Anything else: paste the last 20 lines of the error in the thread (no keys).

## Remove everything after the hackathon
```powershell
sam delete --stack-name saans-compass
```
