from unittest.mock import MagicMock, patch

from src.ingestion.gmail_utils import get_gmail_service, send_reply


def test_get_gmail_service_retries_refresh_on_retryable_network_error(tmp_path, monkeypatch):
    token_path = tmp_path / "token.pickle"
    token_path.write_bytes(b"token")
    monkeypatch.chdir(tmp_path)

    creds = MagicMock()
    creds.valid = False
    creds.expired = True
    creds.refresh_token = "refresh-token"
    creds.refresh.side_effect = [Exception("SSL EOF"), Exception("Connection reset"), None]

    with patch("src.ingestion.gmail_utils.settings.GMAIL_TOKEN", None), \
         patch("src.ingestion.gmail_utils.pickle.load", return_value=creds), \
         patch("src.ingestion.gmail_utils.build", return_value="gmail-service") as mock_build, \
         patch("src.ingestion.gmail_utils.time.sleep") as mock_sleep, \
         patch("src.ingestion.gmail_utils.random.uniform", return_value=0.0):
        service = get_gmail_service()

    assert service == "gmail-service"
    assert creds.refresh.call_count == 3
    assert mock_sleep.call_count == 2
    mock_build.assert_called_once()


def test_send_reply_retries_transient_network_error():
    service = MagicMock()
    send_call = service.users.return_value.messages.return_value.send.return_value.execute
    send_call.side_effect = [Exception("SSL handshake failed"), Exception("Timeout"), None]

    with patch("src.ingestion.gmail_utils.time.sleep") as mock_sleep, \
         patch("src.ingestion.gmail_utils.random.uniform", return_value=0.0):
        send_reply(
            service,
            thread_id="thread-1",
            msg_id_header="msg-1",
            to="user@example.com",
            subject="Subject",
            body_text="hello",
        )

    assert send_call.call_count == 3
    assert mock_sleep.call_count == 2
