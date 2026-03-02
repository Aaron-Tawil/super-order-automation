import logging

from google import genai
from google.genai import errors
from tenacity import before_sleep_log, retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.shared.config import settings
from src.shared.logger import get_logger

logger = get_logger(__name__)

_client = None


def init_client(
    project_id: str | None = None,
    location: str | None = None,
    api_key: str | None = None,
    *,
    settings_obj=None,
    genai_module=None,
):
    """
    Initialize the Gen AI client.

    Runtime-aware default behavior:
    - Local/dev: prefer API key if both are available
    - Cloud runtime: prefer Vertex AI project credentials
    """
    global _client

    settings_ref = settings_obj or settings
    genai_ref = genai_module or genai

    if project_id is None:
        project_id = settings_ref.PROJECT_ID
    project_id = (project_id or "").strip()

    if location is None:
        location = settings_ref.LOCATION
    location = location or "global"

    if not api_key and settings_ref.GEMINI_API_KEY:
        api_key = settings_ref.GEMINI_API_KEY.get_secret_value()

    use_vertex = False
    if project_id and api_key:
        use_vertex = settings_ref.is_cloud_runtime
    elif project_id:
        use_vertex = True

    if use_vertex:
        logger.info(f"Initializing Gen AI Client with VERTEX AI (Project: {project_id})...")
        _client = genai_ref.Client(vertexai=True, project=project_id, location=location)
    elif api_key:
        logger.info("Initializing Gen AI Client with API KEY (AI Studio mode)...")
        _client = genai_ref.Client(api_key=api_key)
    else:
        logger.error("Error: Must provide either project_id OR api_key.")

    return _client


def is_retryable_error(exception):
    """
    Retry on 5xx server errors and 429 resource-exhausted style errors.
    """
    if isinstance(exception, errors.ServerError):
        return True
    if isinstance(exception, errors.ClientError):
        code = getattr(exception, "code", None) or getattr(exception, "status_code", None)
        if code == 429:
            return True
        if "429" in str(exception) or "RESOURCE_EXHAUSTED" in str(exception):
            return True
    return False


@retry(
    retry=retry_if_exception(is_retryable_error),
    stop=stop_after_attempt(8),
    wait=wait_exponential(multiplier=2, min=4, max=120),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def generate_content_safe(model, contents, config):
    """
    Resilient wrapper around `generate_content` with retry semantics for transient failures.
    """
    if not _client:
        raise ValueError("Client not initialized")

    return _client.models.generate_content(model=model, contents=contents, config=config)
