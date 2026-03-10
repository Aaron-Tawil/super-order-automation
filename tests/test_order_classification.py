from src.shared.config import settings
from src.shared.utils import extract_sender_email, is_allowed_sender, is_test_sender


def test_extract_sender_email_from_display_name() -> None:
    assert extract_sender_email("Test <test@example.com>") == "test@example.com"


def test_is_test_sender_uses_configured_test_emails(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TEST_ORDER_EMAILS_STR", "test.user@example.com")
    assert is_test_sender("Test User <test.user@example.com>") is True
    assert is_test_sender("real.user@example.com") is False


def test_is_allowed_sender_returns_true_when_allowlist_empty(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "", raising=False)
    assert is_allowed_sender("user@example.com") is True


def test_is_allowed_sender_matches_exact_email(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "allowed@example.com", raising=False)
    assert is_allowed_sender("Allowed User <allowed@example.com>") is True
    assert is_allowed_sender("blocked@example.com") is False


def test_is_allowed_sender_matches_allowed_domain(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "@example.com", raising=False)
    assert is_allowed_sender("Allowed User <allowed@example.com>") is True
    assert is_allowed_sender("blocked@other.com") is False
