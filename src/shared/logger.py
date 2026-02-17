import logging
import json
import sys
import os
from src.shared.config import settings

# Import Google Cloud Logging
try:
    import google.cloud.logging
    from google.cloud.logging.handlers import StructuredLogHandler
    HAS_GOOGLE_LOGGING = True
except ImportError:
    HAS_GOOGLE_LOGGING = False


def setup_logger(name: str) -> logging.Logger:
    """
    Configures and returns a logger.
    Uses Google Cloud Logging (StructuredLogHandler) when in cloud environment.
    """
    logger = logging.getLogger(name)

    # Remove existing handlers (e.g., from functions-framework or other libraries)
    # to ensure our configuration (StructuredLogHandler) takes precedence.
    if logger.hasHandlers():
        logger.handlers.clear()

    # Check Environment
    is_cloud = (
        settings.ENVIRONMENT.lower() in ("prod", "production", "cloud") 
        or os.environ.get("K_SERVICE") is not None
    )

    # Cloud Environment: Use Google Cloud Logging Native Client
    if is_cloud and HAS_GOOGLE_LOGGING:
        try:
            # StructuredLogHandler writes JSON to stdout, which Cloud Functions/Run
            # agent picks up and parses (setting severity correctly).
            handler = StructuredLogHandler()
            logger.addHandler(handler)
            logger.propagate = False # Prevent duplication to root
            
            # Set Level
            level_str = settings.LOG_LEVEL.upper()
            level = getattr(logging, level_str, logging.INFO)
            logger.setLevel(level)
            
            return logger
        except Exception as e:
            # Fallback if setup fails
            print(f"Failed to setup Google Cloud Logging: {e}", file=sys.stderr)

    # Local Dev or Fallback: Standard StreamHandler
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(asctime)s - [%(levelname)s] - %(name)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = True  # Keep default for local dev

    # Set Level
    level_str = settings.LOG_LEVEL.upper()
    level = getattr(logging, level_str, logging.INFO)
    logger.setLevel(level)

    return logger


def get_logger(name: str) -> logging.Logger:
    return setup_logger(name)
