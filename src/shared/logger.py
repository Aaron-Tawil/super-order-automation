import json
import logging
import sys

try:
    from pythonjsonlogger import jsonlogger
    HAS_JSON_LOGGER = True
except ImportError:
    HAS_JSON_LOGGER = False

from src.shared.config import settings


def setup_logger(name: str) -> logging.Logger:
    """
    Configures and returns a logger with JSON formatting.
    """
    logger = logging.getLogger(name)

    # Check if handlers already exist to avoid duplicate logs
    if logger.hasHandlers():
        return logger

    handler = logging.StreamHandler(sys.stdout)

    # Use JSON formatting for Cloud environments, simple text for local dev
    if settings.ENVIRONMENT.lower() in ("prod", "production", "cloud") and HAS_JSON_LOGGER:
        formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"levelname": "severity", "asctime": "timestamp"},
        )
        # Prevent propagation to root logger (Streamlit/Gunicorn) to avoid duplicate/text logs
        logger.propagate = False
    else:
        # Local Dev or fallback: simpler format
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        logger.propagate = True  # Keep default for local dev

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Set level from config
    level_str = settings.LOG_LEVEL.upper()
    # Handle cases where level might be invalid
    level = getattr(logging, level_str, logging.INFO)
    logger.setLevel(level)

    return logger


def get_logger(name: str) -> logging.Logger:
    return setup_logger(name)
