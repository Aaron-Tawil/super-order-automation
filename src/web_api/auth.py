from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse

import requests

from src.shared.config import settings

GOOGLE_PROVIDER = "google"
MICROSOFT_PROVIDER = "microsoft"
SUPPORTED_AUTH_PROVIDERS = (GOOGLE_PROVIDER, MICROSOFT_PROVIDER)
PROVIDER_LABELS = {
    GOOGLE_PROVIDER: "Google",
    MICROSOFT_PROVIDER: "Microsoft",
}
GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USER_INFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_SCOPE = "openid email profile"
MICROSOFT_GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me?$select=displayName,mail,userPrincipalName"
MICROSOFT_SCOPE = "openid profile email User.Read"
STATE_MAX_AGE_SECONDS = 600
AUTH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def normalize_provider(provider: str | None) -> str:
    normalized = (provider or "").strip().lower()
    if normalized in SUPPORTED_AUTH_PROVIDERS:
        return normalized
    return GOOGLE_PROVIDER


def provider_label(provider: str | None) -> str:
    return PROVIDER_LABELS[normalize_provider(provider)]


def get_cookie_secret() -> str:
    return (
        settings.COOKIE_SECRET.strip()
        or settings.GOOGLE_CLIENT_SECRET.strip()
        or settings.MICROSOFT_CLIENT_SECRET.strip()
        or "local-dev-insecure-secret"
    )


def _microsoft_base_oauth_url() -> str:
    tenant = (settings.MICROSOFT_TENANT_ID or "").strip() or "common"
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"


def get_provider_config(provider: str | None) -> dict[str, str]:
    normalized = normalize_provider(provider)
    if normalized == MICROSOFT_PROVIDER:
        base_url = _microsoft_base_oauth_url()
        return {
            "provider": MICROSOFT_PROVIDER,
            "label": provider_label(MICROSOFT_PROVIDER),
            "client_id": settings.MICROSOFT_CLIENT_ID.strip(),
            "client_secret": settings.MICROSOFT_CLIENT_SECRET.strip(),
            "authorization_url": f"{base_url}/authorize",
            "token_url": f"{base_url}/token",
            "scope": MICROSOFT_SCOPE,
        }

    return {
        "provider": GOOGLE_PROVIDER,
        "label": provider_label(GOOGLE_PROVIDER),
        "client_id": settings.GOOGLE_CLIENT_ID.strip(),
        "client_secret": settings.GOOGLE_CLIENT_SECRET.strip(),
        "authorization_url": GOOGLE_AUTHORIZATION_URL,
        "token_url": GOOGLE_TOKEN_URL,
        "scope": GOOGLE_SCOPE,
    }


def is_provider_configured(provider: str | None) -> bool:
    cfg = get_provider_config(provider)
    return bool(cfg["client_id"] and cfg["client_secret"])


def get_enabled_auth_providers() -> list[str]:
    return [provider for provider in SUPPORTED_AUTH_PROVIDERS if is_provider_configured(provider)]


def encode_payload(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_payload(encoded: str | None) -> dict[str, object] | None:
    if not encoded:
        return None
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def sign_payload(payload: dict[str, object]) -> str:
    secret = get_cookie_secret().encode("utf-8")
    message = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def build_state_payload(provider: str, redirect_params: dict[str, str] | None = None) -> dict[str, object]:
    issued_at = int(time.time())
    payload: dict[str, object] = {
        "nonce": secrets.token_urlsafe(12),
        "provider": normalize_provider(provider),
        "iat": issued_at,
    }
    if redirect_params:
        payload["redir"] = redirect_params
    payload["sig"] = sign_payload(payload)
    return payload


def decode_state(state: str | None) -> dict[str, object] | None:
    payload = decode_payload(state)
    if not payload:
        return None
    provided_sig = payload.get("sig")
    if not isinstance(provided_sig, str):
        return None
    unsigned = dict(payload)
    unsigned.pop("sig", None)
    if not hmac.compare_digest(provided_sig, sign_payload(unsigned)):
        return None
    issued_at = payload.get("iat")
    if not isinstance(issued_at, int):
        return None
    now = int(time.time())
    if issued_at > now + 60 or now - issued_at > STATE_MAX_AGE_SECONDS:
        return None
    return payload


def build_login_url(provider: str, redirect_params: dict[str, str] | None = None) -> str:
    cfg = get_provider_config(provider)
    redirect_uri = f"{settings.get_web_api_url.rstrip('/')}/api/v1/auth/callback/{cfg['provider']}"
    query = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": cfg["scope"],
        "state": encode_payload(build_state_payload(cfg["provider"], redirect_params=redirect_params)),
    }
    if cfg["provider"] == GOOGLE_PROVIDER:
        query["access_type"] = "offline"
        query["prompt"] = "select_account"
    return f"{cfg['authorization_url']}?{urllib.parse.urlencode(query)}"


def exchange_code_for_token(code: str, provider: str) -> dict | None:
    cfg = get_provider_config(provider)
    redirect_uri = f"{settings.get_web_api_url.rstrip('/')}/api/v1/auth/callback/{cfg['provider']}"
    response = requests.post(
        cfg["token_url"],
        data={
            "code": code,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    if not response.ok:
        return None
    return response.json()


def get_user_info(token_data: dict, provider: str) -> dict | None:
    access_token = token_data.get("access_token")
    if not access_token:
        return None

    if normalize_provider(provider) == MICROSOFT_PROVIDER:
        response = requests.get(
            MICROSOFT_GRAPH_ME_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        if not response.ok:
            return None
        data = response.json()
        email = data.get("mail") or data.get("userPrincipalName")
        return {"email": email, "name": data.get("displayName") or "User"}

    response = requests.get(
        GOOGLE_USER_INFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    if not response.ok:
        return None
    data = response.json()
    return {"email": data.get("email"), "name": data.get("name") or "User"}


def is_user_allowed(email: str | None) -> bool:
    normalized = normalize_email(email)
    if not normalized:
        return False

    allowed = settings.allowed_emails
    if not allowed:
        return True

    for value in allowed:
        candidate = value.strip().lower()
        if not candidate:
            continue
        if candidate.startswith("@") and normalized.endswith(candidate):
            return True
        if normalized == candidate:
            return True
    return False


def encode_session_cookie(email: str, user_name: str, provider: str) -> str:
    issued_at = int(time.time())
    payload: dict[str, object] = {
        "email": normalize_email(email),
        "name": user_name.strip() or "User",
        "provider": normalize_provider(provider),
        "iat": issued_at,
        "exp": issued_at + AUTH_COOKIE_MAX_AGE_SECONDS,
    }
    payload["sig"] = sign_payload(payload)
    return encode_payload(payload)


def decode_session_cookie(raw_value: str | None) -> dict[str, object] | None:
    payload = decode_payload(raw_value)
    if not payload:
        return None
    provided_sig = payload.get("sig")
    if not isinstance(provided_sig, str):
        return None
    unsigned = dict(payload)
    unsigned.pop("sig", None)
    if not hmac.compare_digest(provided_sig, sign_payload(unsigned)):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return None
    return payload
