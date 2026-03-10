import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
from pathlib import Path

import requests
import streamlit as st
from streamlit_cookies_manager import CookieManager
from streamlit_cookies_manager.cookie_manager import CookiesNotReady

from src.shared.config import settings
from src.shared.logger import get_logger
from src.shared.translations import get_text

logger = get_logger(__name__)

_cookie_manager: CookieManager | None = None
_local_cookie_secret: str | None = None

GOOGLE_PROVIDER = "google"
MICROSOFT_PROVIDER = "microsoft"
DEFAULT_AUTH_PROVIDER = GOOGLE_PROVIDER
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
POST_AUTH_SESSION_KEY = "post_auth_session_id"
OAUTH_STATE_MAX_AGE_SECONDS = 600
AUTH_COOKIE_KEY = "auth_session"
AUTH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
LOCAL_COOKIE_SECRET_FILE = Path(".streamlit/.cookie_secret")


def _normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _normalize_provider(provider: str | None) -> str:
    normalized = (provider or "").strip().lower()
    if normalized in SUPPORTED_AUTH_PROVIDERS:
        return normalized
    return DEFAULT_AUTH_PROVIDER


def _provider_label(provider: str | None) -> str:
    return PROVIDER_LABELS[_normalize_provider(provider)]


def _microsoft_base_oauth_url() -> str:
    tenant = (settings.MICROSOFT_TENANT_ID or "").strip() or "common"
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"


def _get_provider_config(provider: str | None) -> dict[str, str]:
    normalized = _normalize_provider(provider)
    if normalized == MICROSOFT_PROVIDER:
        base_url = _microsoft_base_oauth_url()
        return {
            "provider": MICROSOFT_PROVIDER,
            "label": PROVIDER_LABELS[MICROSOFT_PROVIDER],
            "client_id": settings.MICROSOFT_CLIENT_ID.strip(),
            "client_secret": settings.MICROSOFT_CLIENT_SECRET.strip(),
            "authorization_url": f"{base_url}/authorize",
            "token_url": f"{base_url}/token",
            "scope": MICROSOFT_SCOPE,
        }

    return {
        "provider": GOOGLE_PROVIDER,
        "label": PROVIDER_LABELS[GOOGLE_PROVIDER],
        "client_id": settings.GOOGLE_CLIENT_ID.strip(),
        "client_secret": settings.GOOGLE_CLIENT_SECRET.strip(),
        "authorization_url": GOOGLE_AUTHORIZATION_URL,
        "token_url": GOOGLE_TOKEN_URL,
        "scope": GOOGLE_SCOPE,
    }


def _is_provider_configured(provider: str | None) -> bool:
    cfg = _get_provider_config(provider)
    return bool(cfg["client_id"] and cfg["client_secret"])


def _get_enabled_auth_providers() -> list[str]:
    return [provider for provider in SUPPORTED_AUTH_PROVIDERS if _is_provider_configured(provider)]


def _get_cookie_password() -> str:
    """
    Returns cookie encryption password.
    Cloud runtime must use configured secret; local dev gets persistent on-disk fallback.
    """
    global _local_cookie_secret

    configured_secret = (
        settings.COOKIE_SECRET.strip()
        or settings.GOOGLE_CLIENT_SECRET.strip()
        or settings.MICROSOFT_CLIENT_SECRET.strip()
    )
    if configured_secret:
        return configured_secret

    if settings.is_cloud_runtime:
        raise RuntimeError(
            "COOKIE_SECRET (or an OAuth client secret) is required for secure dashboard cookies in cloud runtime."
        )

    if not _local_cookie_secret:
        try:
            if LOCAL_COOKIE_SECRET_FILE.exists():
                existing = LOCAL_COOKIE_SECRET_FILE.read_text(encoding="utf-8").strip()
                if existing:
                    _local_cookie_secret = existing
                else:
                    _local_cookie_secret = secrets.token_urlsafe(48)
                    LOCAL_COOKIE_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
                    LOCAL_COOKIE_SECRET_FILE.write_text(_local_cookie_secret, encoding="utf-8")
            else:
                _local_cookie_secret = secrets.token_urlsafe(48)
                LOCAL_COOKIE_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
                LOCAL_COOKIE_SECRET_FILE.write_text(_local_cookie_secret, encoding="utf-8")
            logger.warning(
                "COOKIE_SECRET/OAuth client secrets not configured locally. "
                "Using persistent local cookie secret at .streamlit/.cookie_secret."
            )
        except OSError as err:
            _local_cookie_secret = secrets.token_urlsafe(32)
            logger.warning(f"Failed to persist local cookie secret ({err}); using temporary in-memory secret.")

    return _local_cookie_secret


def _get_cookie_manager() -> CookieManager:
    """
    Returns a per-run cookie manager instance.
    """
    global _cookie_manager
    if _cookie_manager is None:
        _cookie_manager = CookieManager(prefix="soa_dashboard_")
    return _cookie_manager


def _get_all_params_except_oauth() -> dict[str, str]:
    """Extracts all current query parameters except OAuth-specific ones."""
    params = {}
    for key, value in st.query_params.items():
        if key not in ("code", "state", "session_state", "authuser", "prompt", "scope"):
            norm = _normalize_query_value(value)
            if norm:
                params[key] = norm
    return params


def _refresh_cookie_manager_if_needed() -> CookieManager:
    """
    Refreshes stale not-ready manager instances across reruns while preserving
    single-instance usage within a run (avoids duplicate Streamlit component keys).
    """
    global _cookie_manager

    if _cookie_manager is None:
        _cookie_manager = CookieManager(prefix="soa_dashboard_")
        return _cookie_manager

    try:
        is_ready = bool(_cookie_manager.ready())
    except Exception:
        is_ready = False

    if not is_ready:
        _cookie_manager = CookieManager(prefix="soa_dashboard_")

    return _cookie_manager


def _safe_cookie_get(cookies: CookieManager, key: str) -> str | None:
    """Safely reads a cookie value without raising when cookie manager is not ready yet."""
    try:
        value = cookies.get(key)
        if isinstance(value, str):
            value = value.strip()
        return value or None
    except (CookiesNotReady, KeyError, ValueError) as err:
        logger.debug(f"Cookie read skipped for key='{key}': {type(err).__name__}")
        return None


def _encode_payload(payload: dict[str, str | int]) -> str:
    """Encodes JSON payload to URL-safe base64 without padding."""
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_payload(encoded: str | None) -> dict[str, str | int] | None:
    """Decodes URL-safe base64 JSON payload."""
    if not encoded:
        return None

    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    normalized: dict[str, str | int | dict[str, str]] = {}
    for key, value in payload.items():
        if isinstance(value, (str, int)):
            normalized[key] = value.strip() if isinstance(value, str) else value
        elif isinstance(value, dict):
            nested: dict[str, str] = {}
            for nested_key, nested_value in value.items():
                if not isinstance(nested_key, str):
                    continue
                if not isinstance(nested_value, str):
                    continue
                cleaned_key = nested_key.strip()
                cleaned_value = nested_value.strip()
                if cleaned_key and cleaned_value:
                    nested[cleaned_key] = cleaned_value
            if nested:
                normalized[key] = nested
    return normalized


def _build_auth_cookie_payload(
    email: str,
    user_name: str,
    provider: str,
    issued_at: int | None = None,
) -> dict[str, str | int]:
    issued = issued_at or int(time.time())
    return {
        "email": _normalize_email(email),
        "name": user_name.strip() or "User",
        "provider": _normalize_provider(provider),
        "iat": issued,
        "exp": issued + AUTH_COOKIE_MAX_AGE_SECONDS,
    }


def _sign_auth_cookie(payload: dict[str, str | int]) -> str:
    secret = _get_cookie_password().encode("utf-8")
    message = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _encode_auth_cookie(email: str, user_name: str, provider: str) -> str:
    payload = _build_auth_cookie_payload(email=email, user_name=user_name, provider=provider)
    payload["sig"] = _sign_auth_cookie(payload)
    return _encode_payload(payload)


def _read_auth_cookie_provider(payload: dict[str, str | int] | None) -> str:
    provider = payload.get("provider") if payload else None
    if isinstance(provider, str) and provider.strip():
        return _normalize_provider(provider)
    return DEFAULT_AUTH_PROVIDER


def _is_valid_auth_cookie(payload: dict[str, str | int] | None) -> bool:
    if not payload:
        return False
    email = payload.get("email")
    name = payload.get("name")
    provider = payload.get("provider")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    provided_sig = payload.get("sig")
    if not isinstance(email, str) or not email:
        return False
    if not isinstance(name, str) or not name:
        return False
    if not isinstance(issued_at, int) or not isinstance(expires_at, int):
        return False
    if not isinstance(provided_sig, str) or not provided_sig:
        return False
    if provider is not None and (
        not isinstance(provider, str) or provider.strip().lower() not in SUPPORTED_AUTH_PROVIDERS
    ):
        return False

    normalized_provider = _read_auth_cookie_provider(payload)

    unsigned = {
        "email": _normalize_email(email),
        "name": name.strip() or "User",
        "provider": normalized_provider,
        "iat": issued_at,
        "exp": expires_at,
    }

    expected_sig = _sign_auth_cookie(unsigned)
    if not hmac.compare_digest(provided_sig, expected_sig):
        # Backward compatibility for legacy cookies saved before provider claim was added.
        legacy_unsigned = {
            "email": _normalize_email(email),
            "name": name.strip() or "User",
            "iat": issued_at,
            "exp": expires_at,
        }
        legacy_expected_sig = _sign_auth_cookie(legacy_unsigned)
        if not hmac.compare_digest(provided_sig, legacy_expected_sig):
            return False

    now = int(time.time())
    if issued_at > now + 60:
        return False
    if expires_at <= now:
        return False
    return True


def _read_auth_cookie(cookies: CookieManager) -> tuple[str | None, str | None, str | None]:
    token = _safe_cookie_get(cookies, AUTH_COOKIE_KEY)
    payload = _decode_payload(token)
    if not _is_valid_auth_cookie(payload):
        return None, None, None
    email = payload.get("email")
    user_name = payload.get("name")
    provider = _read_auth_cookie_provider(payload)
    return (
        _normalize_email(email) if isinstance(email, str) else None,
        user_name if isinstance(user_name, str) else None,
        provider,
    )


def _persist_auth_cookies(cookies: CookieManager, email: str, user_name: str, provider: str) -> bool:
    """Best-effort auth cookie persistence."""
    try:
        cookies[AUTH_COOKIE_KEY] = _encode_auth_cookie(email=email, user_name=user_name, provider=provider)
        cookies.save()
        logger.info("Auth session cookie queued for save.")
        return True
    except Exception as err:
        logger.warning(f"Failed to persist auth cookies: {err}")
        return False


def _normalize_query_value(value: str | list[str] | None) -> str | None:
    """Normalizes Streamlit query param values to a single non-empty string."""
    if isinstance(value, list):
        if not value:
            return None
        value = value[0]
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _encode_oauth_state(payload: dict[str, str | int]) -> str:
    return _encode_payload(payload)


def _decode_oauth_state(state: str | None) -> dict[str, str | int | dict] | None:
    """Decodes OAuth state payload from URL-safe base64 JSON."""
    payload = _decode_payload(state)
    if not payload:
        return None

    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not nonce.strip():
        return None

    issued_at = payload.get("iat")
    if not isinstance(issued_at, int):
        return None

    provider = payload.get("provider")
    if not isinstance(provider, str) or provider.strip().lower() not in SUPPORTED_AUTH_PROVIDERS:
        return None

    signature = payload.get("sig")
    if not isinstance(signature, str) or not signature.strip():
        return None

    normalized: dict[str, str | int | dict] = {
        "nonce": nonce.strip(),
        "provider": _normalize_provider(provider),
        "iat": issued_at,
        "sig": signature.strip(),
    }

    # Legacy session support
    session_value = payload.get("session")
    if isinstance(session_value, str) and session_value.strip():
        normalized["session"] = session_value.strip()

    # Generic redirect params
    redir = payload.get("redir")
    if isinstance(redir, dict):
        normalized["redir"] = redir

    return normalized


def _build_oauth_state_payload(
    nonce: str,
    provider: str,
    issued_at: int,
    session_id: str | None = None,
    redirect_params: dict[str, str] | None = None,
) -> dict[str, str | int | dict]:
    payload: dict[str, str | int | dict] = {
        "nonce": nonce,
        "provider": _normalize_provider(provider),
        "iat": issued_at,
    }
    if session_id:
        payload["session"] = session_id
    if redirect_params:
        payload["redir"] = redirect_params
    return payload


def _sign_oauth_state(payload: dict[str, str | int]) -> str:
    """Signs state payload so callback validation is stateless across Streamlit sessions."""
    signing_secret = _get_cookie_password().encode("utf-8")
    message = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hmac.new(signing_secret, message, hashlib.sha256).hexdigest()


def _is_valid_oauth_state(payload: dict[str, str | int] | None) -> bool:
    """Validates signature and freshness of OAuth state payload."""
    if not payload:
        return False

    nonce = payload.get("nonce")
    provider = payload.get("provider")
    issued_at = payload.get("iat")
    provided_sig = payload.get("sig")

    if not isinstance(nonce, str) or not nonce:
        return False
    if not isinstance(provider, str) or provider not in SUPPORTED_AUTH_PROVIDERS:
        return False
    if not isinstance(issued_at, int):
        return False
    if not isinstance(provided_sig, str) or not provided_sig:
        return False

    session_id = payload.get("session")
    if session_id is not None and not isinstance(session_id, str):
        return False

    redirect_params = payload.get("redir")
    if redirect_params is not None:
        if not isinstance(redirect_params, dict):
            return False
        for key, value in redirect_params.items():
            if not isinstance(key, str) or not key.strip():
                return False
            if not isinstance(value, str) or not value.strip():
                return False

    unsigned_payload = _build_oauth_state_payload(
        nonce=nonce,
        provider=provider,
        issued_at=issued_at,
        session_id=session_id,
        redirect_params=redirect_params if isinstance(redirect_params, dict) else None,
    )
    expected_sig = _sign_oauth_state(unsigned_payload)
    if not hmac.compare_digest(provided_sig, expected_sig):
        return False

    now = int(time.time())
    # Allow tiny forward skew, but reject stale callbacks.
    if issued_at > now + 60:
        return False
    if now - issued_at > OAUTH_STATE_MAX_AGE_SECONDS:
        return False

    return True


def get_login_url(
    session_id: str | None = None,
    provider: str = DEFAULT_AUTH_PROVIDER,
    redirect_params: dict[str, str] | None = None,
) -> str:
    """Constructs provider-specific OAuth login URL."""
    provider_cfg = _get_provider_config(provider)
    nonce = secrets.token_urlsafe(24)
    issued_at = int(time.time())
    state_payload = _build_oauth_state_payload(
        nonce=nonce,
        provider=provider_cfg["provider"],
        issued_at=issued_at,
        session_id=session_id,
        redirect_params=redirect_params,
    )
    state_payload["sig"] = _sign_oauth_state(state_payload)

    params = {
        "client_id": provider_cfg["client_id"],
        "redirect_uri": settings.get_web_ui_url,
        "response_type": "code",
        "scope": provider_cfg["scope"],
        "state": _encode_oauth_state(state_payload),
        "prompt": "select_account",
    }
    if provider_cfg["provider"] == GOOGLE_PROVIDER:
        params["access_type"] = "offline"

    url_parts = list(urllib.parse.urlparse(provider_cfg["authorization_url"]))
    url_parts[4] = urllib.parse.urlencode(params)
    return urllib.parse.urlunparse(url_parts)


def exchange_code_for_token(code: str, provider: str) -> dict | None:
    """Exchanges the authorization code for provider token payload."""
    provider_cfg = _get_provider_config(provider)
    data = {
        "code": code,
        "client_id": provider_cfg["client_id"],
        "client_secret": provider_cfg["client_secret"],
        "redirect_uri": settings.get_web_ui_url,
        "grant_type": "authorization_code",
    }

    try:
        response = requests.post(provider_cfg["token_url"], data=data, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error exchanging code for token ({provider_cfg['provider']}): {e}")
        return None


def _decode_jwt_payload(jwt_token: str | None) -> dict | None:
    if not jwt_token:
        return None
    parts = jwt_token.split(".")
    if len(parts) < 2:
        return None
    try:
        payload_encoded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload_json = base64.urlsafe_b64decode(payload_encoded.encode("ascii")).decode("utf-8")
        payload = json.loads(payload_json)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    return payload


def _extract_microsoft_email(payload: dict | None) -> str | None:
    if not payload:
        return None
    for key in ("mail", "userPrincipalName", "preferred_username", "email", "upn"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_email(value)
    return None


def get_user_info(token_data: dict, provider: str) -> dict | None:
    """Fetches provider user information and returns normalized identity payload."""
    provider_name = _normalize_provider(provider)
    access_token = token_data.get("access_token") if isinstance(token_data, dict) else None
    if not isinstance(access_token, str) or not access_token.strip():
        logger.error(f"Token response missing access_token ({provider_name}).")
        return None

    headers = {"Authorization": f"Bearer {access_token}"}
    if provider_name == MICROSOFT_PROVIDER:
        graph_payload: dict | None = None
        try:
            response = requests.get(MICROSOFT_GRAPH_ME_URL, headers=headers, timeout=15)
            response.raise_for_status()
            parsed = response.json()
            graph_payload = parsed if isinstance(parsed, dict) else None
        except Exception as e:
            logger.warning(f"Error fetching Microsoft Graph profile: {e}")

        id_payload = _decode_jwt_payload(token_data.get("id_token"))
        email = _extract_microsoft_email(graph_payload) or _extract_microsoft_email(id_payload)
        if not email:
            return None

        display_name = None
        if graph_payload:
            display_name = graph_payload.get("displayName")
        if not display_name and id_payload:
            display_name = id_payload.get("name")

        return {
            "email": email,
            "name": display_name if isinstance(display_name, str) and display_name.strip() else "User",
            "picture": "",
        }

    try:
        response = requests.get(GOOGLE_USER_INFO_URL, headers=headers, timeout=15)
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        logger.error(f"Error fetching Google user info: {e}")
        return None

    if not isinstance(payload, dict):
        return None

    email = payload.get("email")
    if not isinstance(email, str) or not email.strip():
        return None

    return {
        "email": _normalize_email(email),
        "name": payload.get("name") if isinstance(payload.get("name"), str) and payload.get("name").strip() else "User",
        "picture": payload.get("picture") if isinstance(payload.get("picture"), str) else "",
    }


def is_user_allowed(email: str) -> bool:
    """Checks if the email is in the allowed list."""
    normalized_email = _normalize_email(email)
    if not normalized_email:
        return False
        
    allowed_list = settings.allowed_emails
    
    # Strictly deny if allowlist is empty in cloud, but allow warning locally
    if not allowed_list:
        if settings.is_cloud_runtime:
            logger.error("No allowed emails configured in CLOUD. Denying all access for security.")
            return False
        else:
            logger.warning("No allowed emails configured locally. Allowing all authenticated users.")
            return True

    if normalized_email in allowed_list:
        return True

    # Support domain-wide allowlist rules via entries like "@superhome.co.il"
    for allowed_entry in allowed_list:
        if allowed_entry.startswith("@") and len(allowed_entry) > 1 and normalized_email.endswith(allowed_entry):
            return True

    return False


def require_login():
    """
    Main Streamlit authentication interceptor.
    Call this at the very top of your Streamlit app.
    """
    try:
        cookies = _refresh_cookie_manager_if_needed()
    except RuntimeError as err:
        logger.error(f"Authentication misconfiguration: {err}")
        st.error(get_text("auth_err_config"))
        st.stop()

    try:
        cookies_ready = bool(cookies.ready())
    except Exception as err:
        logger.warning(f"Cookie manager initialization failed: {err}")
        cookies_ready = False
    logger.debug(f"Cookie manager ready={cookies_ready}")

    if not cookies_ready:
        st.info(get_text("auth_loading_session"))
        st.stop()

    # 1. Check if user is already logged in (via Session State OR Cookie)
    user_email = _normalize_email(st.session_state.get("user_email"))
    user_name = st.session_state.get("user_name")
    auth_provider = _normalize_provider(st.session_state.get("auth_provider"))
    if not user_email:
        cookie_email, cookie_name, cookie_provider = _read_auth_cookie(cookies)
        if cookie_email:
            user_email = cookie_email
            user_name = cookie_name or user_name
            auth_provider = _normalize_provider(cookie_provider)
            logger.debug("Recovered authenticated user from auth cookie.")

    if user_email:
        # User is known, verify they are STILL allowed (in case allowlist changed)
        if not is_user_allowed(user_email):
            st.error(get_text("auth_access_denied", email=user_email))
            st.warning(get_text("auth_contact_admin"))
            if st.button(get_text("auth_btn_logout_try_another"), type="primary"):
                logout()
            st.stop()
            
        # Ensure session state is synced with cookie
        st.session_state["user_email"] = user_email
        user_name = user_name or st.session_state.get("user_name") or "User"
        if user_name:
            st.session_state["user_name"] = user_name
        st.session_state["auth_provider"] = auth_provider

        return  # User is logged in and allowed, continue app rendering

    # 2. Check if this is an OAuth callback redirect
    query_params = st.query_params
    code = _normalize_query_value(query_params.get("code"))
    if code:
        state_payload = _decode_oauth_state(_normalize_query_value(query_params.get("state")))
        if not _is_valid_oauth_state(state_payload):
            logger.warning("Rejected OAuth callback due to invalid/expired signed state.")
            st.error(get_text("auth_err_invalid_state"))
            st.query_params.clear()
            if st.button(get_text("auth_btn_retry"), type="primary"):
                st.rerun()
            st.stop()

        callback_session_id = state_payload.get("session")
        if callback_session_id is not None and not isinstance(callback_session_id, str):
            callback_session_id = None
        callback_provider = _normalize_provider(state_payload.get("provider"))

        auth_error_key: str | None = None
        auth_error_provider: str | None = None
        denied_email: str | None = None
        if not _is_provider_configured(callback_provider):
            auth_error_key = "auth_err_provider_not_configured"
            auth_error_provider = _provider_label(callback_provider)
        else:
            with st.spinner(get_text("auth_spinner_authenticating", provider=_provider_label(callback_provider))):
                token_data = exchange_code_for_token(code, callback_provider)
                if not token_data:
                    auth_error_key = "auth_err_exchange_provider"
                    auth_error_provider = _provider_label(callback_provider)
                else:
                    user_info = get_user_info(token_data, callback_provider)
                    if not user_info or "email" not in user_info:
                        auth_error_key = "auth_err_no_email_provider"
                        auth_error_provider = _provider_label(callback_provider)
                    else:
                        email = _normalize_email(user_info["email"])
                        logger.info(f"User authenticated ({callback_provider}): {email}")
                        if is_user_allowed(email):
                            # Successful login
                            st.session_state["user_email"] = email
                            st.session_state["user_name"] = user_info.get("name", "User")
                            st.session_state["user_picture"] = user_info.get("picture", "")
                            st.session_state["auth_provider"] = callback_provider

                            # Set cookie for persistence.
                            cookie_saved = _persist_auth_cookies(
                                cookies,
                                email,
                                user_info.get("name", "User"),
                                callback_provider,
                            )
                            logger.info(f"Auth cookie save requested={cookie_saved}")

                            # Restore deep-link context after OAuth callback.
                            st.query_params.clear()
                            
                            redirect_params = state_payload.get("redir")
                            if isinstance(redirect_params, dict):
                                for k, v in redirect_params.items():
                                    st.query_params[k] = v
                                    if k == "order_id":
                                        st.session_state["active_order_id"] = v

                            if callback_session_id:
                                st.session_state[POST_AUTH_SESSION_KEY] = callback_session_id
                                st.query_params["session"] = callback_session_id

                            # Let this run finish so cookie-component save can flush to browser.
                            return

                        denied_email = email

        if denied_email:
            st.error(get_text("auth_access_denied", email=denied_email))
            st.warning(get_text("auth_contact_admin"))
            st.query_params.clear()
            if st.button(get_text("auth_btn_try_another"), type="primary"):
                logout()
            st.stop()

        if auth_error_key:
            if auth_error_provider:
                st.error(get_text(auth_error_key, provider=auth_error_provider))
            else:
                st.error(get_text(auth_error_key))

        # If we reached here without returning, auth failed.
        # Clear code to let them try again.
        st.query_params.clear()
        if st.button(get_text("auth_btn_retry")):
            st.rerun()
        st.stop()

    # 3. Not logged in, not a callback -> Show login screen
    params = _get_all_params_except_oauth()
    display_login_screen(redirect_params=params)
    st.stop() # Stop rendering the rest of the application


def display_login_screen(session_id: str | None = None, redirect_params: dict[str, str] | None = None):
    """Renders the login UI."""
    # Load global CSS so RTL is applied even when stopped at login
    import os
    css_path = os.path.join(os.path.dirname(__file__), "styles.css")
    with open(css_path) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
        
    # CSS for login container
    st.markdown("""
        <style>
        .login-container {
            max-width: 460px;
            margin: auto;
            text-align: center;
            padding: 2rem;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            background-color: white;
            color: black;
            margin-top: 100px;
            direction: rtl;
        }
        .oauth-btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            color: #ffffff !important;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            text-decoration: none;
            font-family: 'Roboto', sans-serif;
            font-size: 16px;
            font-weight: 500;
            cursor: pointer;
            box-shadow: 0 2px 4px 0 rgba(0,0,0,.25);
            transition: background-color .218s, border-color .218s, box-shadow .218s;
            width: 100%;
            margin-top: 14px;
        }
        .oauth-btn:hover {
            color: white;
        }
        .oauth-google {
            background-color: #4285f4;
        }
        .oauth-google:hover {
            box-shadow: 0 0 3px 3px rgba(66,133,244,.3);
        }
        .oauth-microsoft {
            background-color: #2f2f2f;
        }
        .oauth-microsoft:hover {
            box-shadow: 0 0 3px 3px rgba(90, 90, 90, .3);
        }
        </style>
    """, unsafe_allow_html=True)

    enabled_providers = _get_enabled_auth_providers()
    if not enabled_providers:
        st.markdown(
            f"""
            <div class="login-container">
                <h2>{get_text("auth_login_title")}</h2>
                <p>{get_text("auth_login_desc")}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.error(get_text("auth_err_no_provider_config"))
        return

    provider_buttons: list[str] = []
    for provider in enabled_providers:
        button_class = "oauth-google" if provider == GOOGLE_PROVIDER else "oauth-microsoft"
        label = get_text("auth_btn_login_google") if provider == GOOGLE_PROVIDER else get_text("auth_btn_login_microsoft")
        login_url = get_login_url(
            session_id=session_id, 
            provider=provider, 
            redirect_params=redirect_params
        )
        provider_buttons.append(
            f'<a href="{login_url}" class="oauth-btn {button_class}" target="_self">{label}</a>'
        )

    provider_buttons_html = "\n".join(provider_buttons)
    st.markdown(
        f"""
        <div class="login-container">
            <h2>{get_text("auth_login_title")}</h2>
            <p>{get_text("auth_login_desc")}</p>
            <p>{get_text("auth_choose_provider")}</p>
            {provider_buttons_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def logout():
    """Logs the user out by clearing session variables and cookies."""
    keys_to_clear = [
        "user_email",
        "user_name",
        "user_picture",
        "auth_provider",
        "extracted_data",
        "session_metadata",
        "from_email",
        POST_AUTH_SESSION_KEY,
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]

    # Clear cookies (best effort; logout should still clear in-memory session if cookies are unavailable).
    try:
        cookies = _get_cookie_manager()
    except RuntimeError:
        cookies = None

    if cookies and cookies.ready():
        if AUTH_COOKIE_KEY in cookies:
            cookies[AUTH_COOKIE_KEY] = ""
            del cookies[AUTH_COOKIE_KEY]
        # Clean legacy cookies from the encrypted-cookie approach if they exist.
        if "user_email" in cookies:
            del cookies["user_email"]
        if "user_name" in cookies:
            del cookies["user_name"]
        if "EncryptedCookieManager.key_params" in cookies:
            del cookies["EncryptedCookieManager.key_params"]
        cookies.save()

    st.query_params.clear()

    # We must let the script finish executing its current run
    # so the `CookieManager` component can physically clear the cookies on the browser
    import time

    time.sleep(1)

    st.rerun()
