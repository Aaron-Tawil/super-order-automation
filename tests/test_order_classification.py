from src.shared.config import settings
from src.shared.utils import extract_sender_email, is_test_sender


def test_extract_sender_email_from_display_name() -> None:
    assert extract_sender_email("Test <test@example.com>") == "test@example.com"


def test_is_test_sender_uses_configured_test_emails(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TEST_ORDER_EMAILS_STR", "test.user@example.com")
    assert is_test_sender("Test User <test.user@example.com>") is True
    assert is_test_sender("real.user@example.com") is False
