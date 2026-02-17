import os
import sys
from unittest.mock import MagicMock

import pytest

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(autouse=True)
def mock_settings(monkeypatch):
    """
    Mock settings environment variables to avoid needing real credentials.
    """
    monkeypatch.setenv("PROJECT_ID", "test-project")
    monkeypatch.setenv("GCP_REGION", "us-central1")
    monkeypatch.setenv("GCS_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")
    monkeypatch.setenv("WEB_UI_URL", "http://localhost:8501")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")


@pytest.fixture
def mock_logger(mocker):
    """
    Mock the logger to prevent console spam during tests.
    """
    return mocker.patch("src.shared.logger.get_logger")


@pytest.fixture(autouse=True)
def mock_init_client(mocker):
    """
    Mock vertex_client.init_client to prevent real connection attempts during import.
    """
    return mocker.patch("src.extraction.vertex_client.init_client")
