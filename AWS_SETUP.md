# What we need from AWS

Please don't paste keys, passwords or account links into chat. You run the deploy from your own laptop. Nothing below needs to be shared with Claude except the final `SiteUrl`.

## 1. Account and region
- An AWS account with billing set up (Free Tier or credits are fine).
- Region: **ap-south-1 (Mumbai)**. It is already set in `samconfig.toml`.

## 2. A deploy user, not the root account
- In IAM Identity Center, create a user for yourself with the `AdministratorAccess` permission set, then sign in with `aws configure sso`.
- If Identity Center is too slow to set up, create an IAM user with `AdministratorAccess` and use `aws configure`. Delete its access key after the hackathon.
- Turn on MFA for the root user and don't use root for anything else.

## 3. Tools on your laptop
- AWS CLI v2, SAM CLI, Python 3.12, Git.
- Check that both work: `aws sts get-caller-identity` and `sam --version`.

## 4. Service limits and verifications
- **SNS email: nothing to request.** Email subscriptions work right away. Each subscriber clicks a confirmation link once.
- **SNS SMS: not used.** India SMS needs DLT sender registration, which takes too long for this hackathon. Email covers the "alert arrives" moment in the demo.
- **SES: not used**, so there is no sandbox exit to request.
- **Lambda concurrency:** new accounts sometimes get a low limit, which is still enough here. If a deploy complains, check Service Quotas → Lambda → Concurrent executions.

## 5. Deploy
```bash
cd saans-compass
sam build
sam deploy --guided   # accept the defaults; give BudgetEmail and AlarmEmail if you want those emails
```
Open the `SiteUrl` from the outputs, subscribe your own email on a plan page, and confirm it. Then send a test alert:
```bash
sam remote invoke AlertFunction --stack-name saans-compass --event '{"run": "today"}'
```

## 6. Optional: deploy from GitHub with no stored keys
Create an IAM role that trusts GitHub's OIDC provider for your repo, then set it as the repository variable `AWS_DEPLOY_ROLE_ARN`. After that, each push to `main` deploys.
