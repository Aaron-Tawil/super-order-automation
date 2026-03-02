import logging
import os
import sys

from src.shared.config import settings

# Import Google Cloud Logging
try:
    import google.cloud.logging
    from google.cloud.logging.handlers import StructuredLogHandler
    HAS_GOOGLE_LOGGING = True
except ImportError:
    HAS_GOOGLE_LOGGING = False


def _resolve_level() -> int:
    level_str = settings.LOG_LEVEL.upper()
    return getattr(logging, level_str, logging.INFO)


def _is_cloud_runtime() -> bool:
    return settings.ENVIRONMENT.lower() in ("prod", "production", "cloud") or os.environ.get("K_SERVICE") is not None


def setup_logger(name: str) -> logging.Logger:
    """
    Configures and returns a logger.
    Uses Google Cloud Logging (StructuredLogHandler) when in cloud environment.
    """
    logger = logging.getLogger(name)
    level = _resolve_level()
    logger.setLevel(level)

    # Idempotent configuration: if we've already configured this logger in-process,
    # only refresh level and return.
    if getattr(logger, "_soa_configured", False):
        return logger

    is_cloud = _is_cloud_runtime()
    handler: logging.Handler | None = None

    # Cloud Environment: Use Google Cloud Logging Native Client
    if is_cloud and HAS_GOOGLE_LOGGING:
        try:
            # StructuredLogHandler writes JSON to stdout, which Cloud Functions/Run
            # agent picks up and parses (setting severity correctly).
            handler = StructuredLogHandler()
        except Exception as e:
            # Fallback if setup fails
            print(f"Failed to setup Google Cloud Logging: {e}", file=sys.stderr)
            handler = None

    # Local Dev or fallback
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(asctime)s - [%(levelname)s] - %(name)s - %(message)s")
        handler.setFormatter(formatter)

    # Remove only handlers we previously attached.
    logger.handlers = [h for h in logger.handlers if not getattr(h, "_soa_handler", False)]
    handler._soa_handler = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.propagate = False  # Prevent duplication via root logger handlers
    logger._soa_configured = True  # type: ignore[attr-defined]

    return logger


def get_logger(name: str) -> logging.Logger:
    return setup_logger(name)
