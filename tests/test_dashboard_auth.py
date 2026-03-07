import urllib.parse
from types import SimpleNamespace

from src.dashboard import auth


def test_get_login_url_sets_signed_oauth_state_and_session(monkeypatch):
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(auth, "st", fake_st)

    login_url = auth.get_login_url(session_id="session-123")
    parsed = urllib.parse.urlparse(login_url)
    params = urllib.parse.parse_qs(parsed.query)

    assert "state" in params
    state_value = params["state"][0]
    payload = auth._decode_oauth_state(state_value)

    assert payload is not None
    assert payload["session"] == "session-123"
    assert auth._is_valid_oauth_state(payload)


def test_decode_oauth_state_rejects_invalid_values():
    assert auth._decode_oauth_state(None) is None
    assert auth._decode_oauth_state("not-valid-base64") is None


def test_oauth_state_validation_rejects_tampered_and_expired_state(monkeypatch):
    # Freeze "now" so expiry behavior is deterministic.
    monkeypatch.setattr(auth.time, "time", lambda: 1_700_000_000)

    payload = auth._build_oauth_state_payload(nonce="abc123", issued_at=1_700_000_000, session_id="sess-1")
    payload["sig"] = auth._sign_oauth_state(payload)
    assert auth._is_valid_oauth_state(payload)

    tampered = dict(payload)
    tampered["session"] = "sess-2"
    assert not auth._is_valid_oauth_state(tampered)

    expired = auth._build_oauth_state_payload(
        nonce="abc123",
        issued_at=1_700_000_000 - auth.OAUTH_STATE_MAX_AGE_SECONDS - 1,
        session_id="sess-1",
    )
    expired["sig"] = auth._sign_oauth_state(expired)
    assert not auth._is_valid_oauth_state(expired)


def test_persist_auth_cookies():
    class DummyCookies(dict):
        def save(self):
            return None

    cookies = DummyCookies()
    assert auth._persist_auth_cookies(cookies, "user@example.com", "User Name")
    assert auth.AUTH_COOKIE_KEY in cookies
    payload = auth._decode_payload(cookies[auth.AUTH_COOKIE_KEY])
    assert auth._is_valid_auth_cookie(payload)
    assert payload is not None
    assert payload["email"] == "user@example.com"
    assert payload["name"] == "User Name"
