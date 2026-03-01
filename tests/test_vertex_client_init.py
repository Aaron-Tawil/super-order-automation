from unittest.mock import patch

from pydantic import SecretStr

import src.extraction.vertex_client as vertex_client

# tests/conftest.py auto-mocks vertex_client.init_client, so keep a direct reference.
REAL_INIT_CLIENT = vertex_client.init_client


def test_init_client_prefers_api_key_in_local_runtime(monkeypatch):
    monkeypatch.setattr(vertex_client, "_client", None)
    monkeypatch.setattr(vertex_client.settings, "ENVIRONMENT", "dev")
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setattr(vertex_client.settings, "PROJECT_ID", "test-project")
    monkeypatch.setattr(vertex_client.settings, "LOCATION", "us-central1")
    monkeypatch.setattr(vertex_client.settings, "GEMINI_API_KEY", SecretStr("local-api-key"))

    with patch("src.extraction.vertex_client.genai.Client") as mock_client:
        REAL_INIT_CLIENT()
        mock_client.assert_called_once_with(api_key="local-api-key")


def test_init_client_prefers_vertex_in_cloud_runtime(monkeypatch):
    monkeypatch.setattr(vertex_client, "_client", None)
    monkeypatch.setattr(vertex_client.settings, "ENVIRONMENT", "cloud")
    monkeypatch.setenv("K_SERVICE", "processor-service")
    monkeypatch.setattr(vertex_client.settings, "PROJECT_ID", "cloud-project")
    monkeypatch.setattr(vertex_client.settings, "LOCATION", "us-central1")
    monkeypatch.setattr(vertex_client.settings, "GEMINI_API_KEY", SecretStr("cloud-api-key"))

    with patch("src.extraction.vertex_client.genai.Client") as mock_client:
        REAL_INIT_CLIENT()
        mock_client.assert_called_once_with(vertexai=True, project="cloud-project", location="us-central1")


def test_init_client_uses_vertex_when_only_project_available(monkeypatch):
    monkeypatch.setattr(vertex_client, "_client", None)
    monkeypatch.setattr(vertex_client.settings, "ENVIRONMENT", "dev")
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setattr(vertex_client.settings, "PROJECT_ID", "project-only")
    monkeypatch.setattr(vertex_client.settings, "LOCATION", "us-central1")
    monkeypatch.setattr(vertex_client.settings, "GEMINI_API_KEY", None)

    with patch("src.extraction.vertex_client.genai.Client") as mock_client:
        REAL_INIT_CLIENT()
        mock_client.assert_called_once_with(vertexai=True, project="project-only", location="us-central1")
