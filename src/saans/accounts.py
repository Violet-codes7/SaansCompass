"""Sign-up and sign-in with Amazon Cognito.

The web app talks to a Cognito user pool app client (no client secret) with
the USER_PASSWORD_AUTH and REFRESH_TOKEN_AUTH flows, so it needs no IAM
permissions and no hosted login page. The access and refresh tokens go in
HttpOnly cookies; who is signed in is looked up with GetUser and cached in
this Lambda's memory for a few minutes. Accounts are off when no app client
id is configured (local runs).
"""
import hashlib
import logging
import os
import time

from . import settings

log = logging.getLogger(__name__)

TEXT = settings.load("accounts")


class AccountError(Exception):
    """A user-facing account error."""


def enabled():
    return bool(settings.get("user_pool_client_id"))


_client = None


def _cognito():
    global _client
    if _client is None:
        import boto3

        region = settings.get("cognito_region") or os.environ.get("AWS_REGION")
        _client = boto3.client("cognito-idp", region_name=region)
    return _client


def set_client(client):
    """Replace the Cognito client (used by tests)."""
    global _client
    _client = client
    _users.clear()


def message(key, **kw):
    return TEXT["messages"][key].format(**kw)


# Calls made with the app client id rather than a user's access token.
_CLIENT_ID_CALLS = {"sign_up", "confirm_sign_up", "resend_confirmation_code", "initiate_auth",
                    "forgot_password", "confirm_forgot_password"}


def _call(name, **kw):
    if name in _CLIENT_ID_CALLS:
        kw["ClientId"] = settings.get("user_pool_client_id")
    try:
        return getattr(_cognito(), name)(**kw)
    except Exception as exc:  # botocore ClientError carries the Cognito error code
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
        log.info("cognito %s failed: %s", name, code)
        raise AccountError(TEXT["errors"].get(code, TEXT["error_default"])) from None


def _email(email):
    return (email or "").strip().lower()


def sign_up(email, password, name):
    _call("sign_up", Username=_email(email), Password=password,
          UserAttributes=[{"Name": "email", "Value": _email(email)}, {"Name": "name", "Value": name}])


def confirm(email, code):
    _call("confirm_sign_up", Username=_email(email), ConfirmationCode=(code or "").strip())


def resend(email):
    _call("resend_confirmation_code", Username=_email(email))


def sign_in(email, password):
    """{"access", "refresh"} tokens."""
    out = _call("initiate_auth", AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={"USERNAME": _email(email), "PASSWORD": password or ""})
    result = out.get("AuthenticationResult")
    if not result:  # a challenge such as a forced password change
        raise AccountError(TEXT["error_default"])
    return {"access": result["AccessToken"], "refresh": result.get("RefreshToken")}


def refresh(refresh_token):
    """A new access token, or None when the refresh token is no longer valid."""
    try:
        out = _call("initiate_auth", AuthFlow="REFRESH_TOKEN_AUTH", AuthParameters={"REFRESH_TOKEN": refresh_token})
    except AccountError:
        return None
    return out.get("AuthenticationResult", {}).get("AccessToken")


def forgot(email):
    try:
        _call("forgot_password", Username=_email(email))
    except AccountError:
        pass  # never reveal whether an account exists


def reset(email, code, password):
    _call("confirm_forgot_password", Username=_email(email), ConfirmationCode=(code or "").strip(), Password=password)


_users = {}


def _key(token):
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(access_token, now=None):
    """{"sub", "email", "name"} for a valid access token, else None."""
    if not access_token:
        return None
    now = now if now is not None else time.time()
    key = _key(access_token)
    hit = _users.get(key)
    if hit and hit[0] > now:
        return hit[1]
    try:
        out = _call("get_user", AccessToken=access_token)
    except AccountError:
        _users.pop(key, None)
        return None
    attrs = {a["Name"]: a["Value"] for a in out.get("UserAttributes", [])}
    user = {"sub": attrs.get("sub") or out["Username"], "email": attrs.get("email", ""), "name": attrs.get("name", "")}
    if len(_users) >= 1000:
        _users.pop(next(iter(_users)))
    _users[key] = (now + settings.get("user_cache_seconds"), user)
    return user


def sign_out(access_token):
    _users.pop(_key(access_token), None)
    try:
        _call("global_sign_out", AccessToken=access_token)
    except AccountError:
        pass


def delete(access_token):
    _users.pop(_key(access_token), None)
    _call("delete_user", AccessToken=access_token)
