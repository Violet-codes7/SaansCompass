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

## 4. Turn on Claude in Bedrock (once)
Claude powers three things: reading the "What do you do?" box, the Personal advice panel, and its voice. The site works without it (a keyword match reads the box and the advice panel is hidden), so you can do this before or after deploying. Nothing needs redeploying once access is on.

1. Sign in to https://console.aws.amazon.com as `violet-admin`.
2. Top right, open the region menu and pick **Asia Pacific (Mumbai) ap-south-1**.
3. In the search bar type **Bedrock** and open **Amazon Bedrock**.
4. Left menu: **Model catalog**. Under Providers tick **Anthropic**, then click **Claude Opus 5.5**.
5. If the page shows **Submit use case details** or **Request model access**, click it and fill in the short Anthropic form once per account:
   - Company: `Personal / student project`; website: your `SiteUrl` (or the GitHub repo link)
   - Intended users: `External users`; use case: `Hackathon demo: air-quality advice app for Delhi residents`
   - Submit. Approval is usually immediate, sometimes up to 15 minutes.
6. Test it in the console: on the model page click **Open in playground** (or left menu **Playgrounds > Chat**), choose Claude Opus 5.5, type `Hello` and press **Run**. A reply means access works.
7. Test it on the site: open `<SiteUrl>api/summary?persona=rider&area=ito`. You should see `{"summary": ...}`. On a plan page, **Personal advice** fills in, and the first page's note says "Claude on Amazon Bedrock reads this".

**If step 6 or 7 fails**, look at the reason:
```powershell
sam logs -n WebFunction --stack-name saans-compass --start-time "10min ago"
```
Find the line that starts `bedrock returned`:
- **403 "don't have access" / "access denied"**: step 5 is not done or not approved yet. Wait 15 minutes and try again.
- **Mentions AWS Marketplace, a payment method, or the Free plan**: Free plan accounts cannot buy Marketplace models. Go to **Billing and Cost Management > Upgrade plan** (or the "Upgrade" banner) and switch to the **Paid plan**. Your $100 credit stays. Claude may bill your card rather than the credit: a few cents a day for this demo, since each answer is cached. Set **BudgetEmail** at deploy to get a warning before spend passes $1.
- **404 / model not found in this region**: run `sam deploy --guided`, press Enter through every question, and change only **Parameter BedrockRegion** to `us-east-1`. (Do not use `--parameter-overrides` for this: it would wipe your saved email settings.)

The Hindi switch uses **Amazon Translate**, which needs no setup. If Hindi only partly converts ("कुछ हिस्से अंग्रेज़ी में ही रहेंगे"), the same `sam logs` command shows `amazon translate failed` with the reason; the built-in Hindi for headings and labels still works.

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
- **`sam build` fails on a long path:** make sure LongPathsEnabled is on (we did this for pip), or move the project to a short folder like `C:\ac`.
- **`sam build` says Python 3.12 not found:** activate the venv first (step 2).
- **Deploy fails with "not authorized":** your AWS user needs admin rights for the deploy.
- **Personal advice says "not available":** Bedrock access (step 4) is not enabled yet; follow "If step 6 or 7 fails" there.
- Anything else: paste the last 20 lines of the error in the thread (no keys).

## Remove everything after the hackathon
```powershell
sam delete --stack-name saans-compass
```
