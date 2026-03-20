"""
Structured JSON logging configuration.
"""

import logging
import sys
from pythonjsonlogger import jsonlogger


def setup_logging(level: str = "INFO") -> None:
    """Configure structured JSON logging for the application."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Suppress noisy third-party loggers
    for noisy in ("urllib3", "docker", "kafka", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.LoggerAdapter:
    """Return a logger instance with contextual fields support."""
    logger = logging.getLogger(name)

    class _ContextAdapter(logging.LoggerAdapter):
        def process(self, msg, kwargs):
            extra = kwargs.pop("extra", {})
            extra.update(self.extra)
            # Flatten any keyword args into extra
            for key in list(kwargs.keys()):
                if key not in ("exc_info", "stack_info", "stacklevel"):
                    extra[key] = kwargs.pop(key)
            kwargs["extra"] = extra
            return msg, kwargs

    return _ContextAdapter(logger, {})
