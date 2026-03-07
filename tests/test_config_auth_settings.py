from src.shared.config import Settings


def test_allowed_emails_reads_allowed_emails_env(monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", " 'Admin@Example.com, user@example.com' ")
    monkeypatch.delenv("ALLOWED_EMAILS_STR", raising=False)

    cfg = Settings()

    assert cfg.allowed_emails == ["admin@example.com", "user@example.com"]


def test_allowed_emails_back_compat_for_allowed_emails_str(monkeypatch):
    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)
    monkeypatch.setenv("ALLOWED_EMAILS_STR", "legacy@example.com")

    cfg = Settings()

    assert cfg.allowed_emails == ["legacy@example.com"]


def test_allowed_emails_supports_domain_entry(monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", "admin@example.com, @superhome.co.il")

    cfg = Settings()

    assert cfg.allowed_emails == ["admin@example.com", "@superhome.co.il"]


def test_cookie_secret_env_alias(monkeypatch):
    monkeypatch.setenv("DASHBOARD_COOKIE_SECRET", "cookie-secret-value")
    monkeypatch.delenv("COOKIE_SECRET", raising=False)

    cfg = Settings()

    assert cfg.COOKIE_SECRET == "cookie-secret-value"


def test_microsoft_oauth_settings(monkeypatch):
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "ms-client")
    monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "ms-secret")
    monkeypatch.setenv("MICROSOFT_TENANT_ID", "tenant-abc")

    cfg = Settings()

    assert cfg.MICROSOFT_CLIENT_ID == "ms-client"
    assert cfg.MICROSOFT_CLIENT_SECRET == "ms-secret"
    assert cfg.MICROSOFT_TENANT_ID == "tenant-abc"
