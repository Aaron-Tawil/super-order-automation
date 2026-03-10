import urllib.parse
from types import SimpleNamespace

from src.dashboard import auth


def test_get_login_url_sets_signed_oauth_state_and_session(monkeypatch):
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(auth, "st", fake_st)

    login_url = auth.get_login_url(
        session_id="session-123",
        redirect_params={"order_id": "order-123"},
    )
    parsed = urllib.parse.urlparse(login_url)
    params = urllib.parse.parse_qs(parsed.query)

    assert "state" in params
    state_value = params["state"][0]
    payload = auth._decode_oauth_state(state_value)

    assert payload is not None
    assert payload["session"] == "session-123"
    assert payload["provider"] == auth.GOOGLE_PROVIDER
    assert payload["redir"] == {"order_id": "order-123"}
    assert auth._is_valid_oauth_state(payload)


def test_decode_oauth_state_rejects_invalid_values():
    assert auth._decode_oauth_state(None) is None
    assert auth._decode_oauth_state("not-valid-base64") is None


def test_oauth_state_validation_rejects_tampered_and_expired_state(monkeypatch):
    # Freeze "now" so expiry behavior is deterministic.
    monkeypatch.setattr(auth.time, "time", lambda: 1_700_000_000)

    payload = auth._build_oauth_state_payload(
        nonce="abc123",
        provider=auth.GOOGLE_PROVIDER,
        issued_at=1_700_000_000,
        session_id="sess-1",
    )
    payload["sig"] = auth._sign_oauth_state(payload)
    assert auth._is_valid_oauth_state(payload)

    tampered = dict(payload)
    tampered["session"] = "sess-2"
    assert not auth._is_valid_oauth_state(tampered)

    expired = auth._build_oauth_state_payload(
        nonce="abc123",
        provider=auth.GOOGLE_PROVIDER,
        issued_at=1_700_000_000 - auth.OAUTH_STATE_MAX_AGE_SECONDS - 1,
        session_id="sess-1",
    )
    expired["sig"] = auth._sign_oauth_state(expired)
    assert not auth._is_valid_oauth_state(expired)


def test_get_login_url_supports_microsoft_provider(monkeypatch):
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(auth, "st", fake_st)
    monkeypatch.setattr(auth.settings, "MICROSOFT_CLIENT_ID", "ms-client", raising=False)
    monkeypatch.setattr(auth.settings, "MICROSOFT_CLIENT_SECRET", "ms-secret", raising=False)
    monkeypatch.setattr(auth.settings, "MICROSOFT_TENANT_ID", "tenant-123", raising=False)

    login_url = auth.get_login_url(session_id="session-abc", provider=auth.MICROSOFT_PROVIDER)
    parsed = urllib.parse.urlparse(login_url)
    params = urllib.parse.parse_qs(parsed.query)

    assert "login.microsoftonline.com/tenant-123/oauth2/v2.0/authorize" in login_url
    assert params["client_id"][0] == "ms-client"
    state_payload = auth._decode_oauth_state(params["state"][0])
    assert state_payload is not None
    assert state_payload["provider"] == auth.MICROSOFT_PROVIDER
    assert state_payload["session"] == "session-abc"


def test_oauth_state_validation_accepts_redirect_params(monkeypatch):
    monkeypatch.setattr(auth.time, "time", lambda: 1_700_000_000)

    payload = auth._build_oauth_state_payload(
        nonce="nonce-1",
        provider=auth.GOOGLE_PROVIDER,
        issued_at=1_700_000_000,
        redirect_params={"order_id": "abc123", "foo": "bar"},
    )
    payload["sig"] = auth._sign_oauth_state(payload)

    encoded = auth._encode_oauth_state(payload)
    decoded = auth._decode_oauth_state(encoded)

    assert decoded is not None
    assert decoded["redir"] == {"order_id": "abc123", "foo": "bar"}
    assert auth._is_valid_oauth_state(decoded)


def test_persist_auth_cookies_and_read_back_provider():
    class DummyCookies(dict):
        def save(self):
            return None

    cookies = DummyCookies()
    assert auth._persist_auth_cookies(cookies, "user@example.com", "User Name", auth.MICROSOFT_PROVIDER)
    assert auth.AUTH_COOKIE_KEY in cookies
    payload = auth._decode_payload(cookies[auth.AUTH_COOKIE_KEY])
    assert auth._is_valid_auth_cookie(payload)
    assert payload is not None
    assert payload["email"] == "user@example.com"
    assert payload["name"] == "User Name"
    assert payload["provider"] == auth.MICROSOFT_PROVIDER

    email, name, provider = auth._read_auth_cookie(cookies)
    assert email == "user@example.com"
    assert name == "User Name"
    assert provider == auth.MICROSOFT_PROVIDER


def test_is_user_allowed_supports_domain_suffix_rule(monkeypatch):
    monkeypatch.setattr(auth.settings, "ALLOWED_EMAILS", "admin@example.com, @superhome.co.il", raising=False)

    assert auth.is_user_allowed("admin@example.com")
    assert auth.is_user_allowed("sales@superhome.co.il")
    assert auth.is_user_allowed("CEO@SUPERHOME.CO.IL")
    assert not auth.is_user_allowed("user@other.com")
