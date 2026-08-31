"""Structured logging configuration for scanner components."""

import logging
import os
import sys
from typing import cast

import structlog


def configure_logging(environment: str) -> None:
    """Configure structlog for the selected execution environment."""
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: structlog.types.Processor
    if environment == "development":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(component: str) -> structlog.BoundLogger:
    """Return a logger bound to the component emitting each event."""
    return cast(structlog.BoundLogger, structlog.get_logger().bind(component=component))


_environment = os.getenv("ENVIRONMENT", "development").lower()
configure_logging(
    _environment if _environment in {"development", "paper", "live"} else "development"
)
