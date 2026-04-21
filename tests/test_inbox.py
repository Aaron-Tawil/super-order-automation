from src.dashboard.inbox import _format_ingestion_source


def test_format_ingestion_source_for_email_order() -> None:
    assert _format_ingestion_source({"ingestion_source": "email"}) == "אימייל"


def test_format_ingestion_source_for_dashboard_upload_order() -> None:
    assert _format_ingestion_source({"ingestion_source": "dashboard_upload"}) == "העלאה ידנית"


def test_format_ingestion_source_falls_back_to_ui_metadata() -> None:
    assert _format_ingestion_source({"ui_metadata": {"ingestion_source": "email"}}) == "אימייל"


def test_format_ingestion_source_defaults_to_unknown() -> None:
    assert _format_ingestion_source({}) == "לא ידוע"
