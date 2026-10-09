# Deploy Saans Compass from Windows

About 20 minutes the first time. Run every command in **PowerShell** from the project folder. Never paste keys or passwords into chat.

## 0. AWS account and student credits (once)
1. Create an AWS account at https://aws.amazon.com (a card is required even with credits).
2. Turn on MFA for the root user: account menu → Security credentials → Assign MFA device.
3. Apply your credits: in AWS Builder Center open your student rewards and copy the credit code, then in the console go to Billing and Cost Management → Credits → **Redeem credit**, paste it and submit. The credit then shows in that list with its expiry date and eligible services.
4. Create your everyday user: IAM → Users → Create user `violet-admin`, tick "Provide access to the AWS Management Console", attach **AdministratorAccess**, create. Copy the sign-in URL it shows.
5. Sign out and sign back in at that URL as `violet-admin`. Use this user from now on, not root.

Credits do not always cover every service. Check the "Eligible services" on the credit. Claude models on Bedrock are sold through AWS Marketplace and may be billed to your card instead; for this app that is a few cents (each summary is cached for 6 hours). The optional BudgetEmail at deploy warns you before spend passes $1.

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
py -3.12 -m venv E:\venv312          # once; needs Python 3.12 from python.org (see below)
E:\venv312\Scripts\Activate.ps1
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

## 4. Turn on Claude in Bedrock (once)
Console → switch region to **Asia Pacific (Mumbai) ap-south-1** → Amazon Bedrock → Model catalog → **Claude Opus 5.5** → enable / request access. Anthropic asks for a short use-case form the first time ("hackathon demo, air-quality advice app" is fine).
You can skip this; the site still works, it just hides the "In plain words" box.

## 5. Build and deploy
Keep the `E:\venv312` venv active (sam build uses the Python 3.12 on PATH).
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
| Parameter BedrockModel | press Enter (keeps `anthropic.claude-opus-5-5`) |
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
- **`sam build` fails on a long path:** make sure LongPathsEnabled is on (we did this for pip), or move the project to a short folder like `E:\ac`.
- **`sam build` says Python 3.12 not found:** activate the venv first (step 2).
- **Deploy fails with "not authorized":** your AWS user needs admin rights for the deploy.
- **The summary box says "not available":** Bedrock access (step 4) is not enabled yet.
- Anything else: paste the last 20 lines of the error in the thread (no keys).

## Remove everything after the hackathon
```powershell
sam delete --stack-name saans-compass
```
