from unittest.mock import MagicMock, patch

from src.ingestion.gmail_utils import (
    SEND_REPLY_STATUS_PERMANENT_FAILED,
    SEND_REPLY_STATUS_RETRYABLE_FAILED,
    SEND_REPLY_STATUS_SENT,
    get_gmail_service,
    send_reply,
    send_reply_with_status,
)


def test_get_gmail_service_retries_refresh_on_retryable_network_error(tmp_path, monkeypatch):
    token_path = tmp_path / "token.pickle"
    token_path.write_bytes(b"token")
    monkeypatch.chdir(tmp_path)

    creds = MagicMock()
    creds.valid = False
    creds.expired = True
    creds.refresh_token = "refresh-token"
    creds.refresh.side_effect = [Exception("SSL EOF"), Exception("Connection reset"), None]

    with (
        patch("src.ingestion.gmail_utils.settings.GMAIL_TOKEN", None),
        patch("src.ingestion.gmail_utils.pickle.load", return_value=creds),
        patch("src.ingestion.gmail_utils.build", return_value="gmail-service") as mock_build,
        patch("src.ingestion.gmail_utils.time.sleep") as mock_sleep,
        patch("src.ingestion.gmail_utils.random.uniform", return_value=0.0),
    ):
        service = get_gmail_service()

    assert service == "gmail-service"
    assert creds.refresh.call_count == 3
    assert mock_sleep.call_count == 2
    mock_build.assert_called_once()


def test_send_reply_retries_transient_network_error():
    service = MagicMock()
    send_call = service.users.return_value.messages.return_value.send.return_value.execute
    send_call.side_effect = [Exception("SSL handshake failed"), Exception("Timeout"), None]

    with (
        patch("src.ingestion.gmail_utils.time.sleep") as mock_sleep,
        patch("src.ingestion.gmail_utils.random.uniform", return_value=0.0),
    ):
        sent = send_reply(
            service,
            thread_id="thread-1",
            msg_id_header="msg-1",
            to="user@example.com",
            subject="Subject",
            body_text="hello",
        )

    assert sent is True
    assert send_call.call_count == 3
    assert mock_sleep.call_count == 2


def test_send_reply_with_status_returns_permanent_failure_on_missing_thread():
    service = MagicMock()
    send_call = service.users.return_value.messages.return_value.send.return_value.execute
    send_call.side_effect = Exception("Requested entity was not found: 404")

    status, error = send_reply_with_status(
        service,
        thread_id="missing-thread",
        msg_id_header="msg-1",
        to="user@example.com",
        subject="Subject",
        body_text="hello",
    )

    assert status == SEND_REPLY_STATUS_PERMANENT_FAILED
    assert "404" in error
    assert send_call.call_count == 1


def test_send_reply_with_status_returns_retryable_after_retryable_failures():
    service = MagicMock()
    send_call = service.users.return_value.messages.return_value.send.return_value.execute
    send_call.side_effect = Exception("SSL handshake failed")

    with (
        patch("src.ingestion.gmail_utils.time.sleep"),
        patch("src.ingestion.gmail_utils.random.uniform", return_value=0.0),
    ):
        status, error = send_reply_with_status(
            service,
            thread_id="thread-1",
            msg_id_header="msg-1",
            to="user@example.com",
            subject="Subject",
            body_text="hello",
        )

    assert status == SEND_REPLY_STATUS_RETRYABLE_FAILED
    assert "SSL handshake failed" in error
    assert send_call.call_count == 5


def test_send_reply_with_status_returns_permanent_when_message_build_fails():
    service = MagicMock()

    with patch("src.ingestion.gmail_utils.MIMEText", side_effect=RuntimeError("build failed")):
        status, error = send_reply_with_status(
            service,
            thread_id="thread-1",
            msg_id_header="msg-1",
            to="user@example.com",
            subject="Subject",
            body_text="hello",
        )

    assert status == SEND_REPLY_STATUS_PERMANENT_FAILED
    assert "build failed" in error


def test_send_reply_with_status_returns_sent_on_success():
    service = MagicMock()
    send_call = service.users.return_value.messages.return_value.send.return_value.execute
    send_call.return_value = None

    status, error = send_reply_with_status(
        service,
        thread_id="thread-1",
        msg_id_header="msg-1",
        to="user@example.com",
        subject="Subject",
        body_text="hello",
    )

    assert status == SEND_REPLY_STATUS_SENT
    assert error is None
