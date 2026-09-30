"""Structured console logging for the application."""

import logging
import sys

import structlog

# Processors shared by structlog records and foreign (stdlib) records, so
# Chainlit and uvicorn logs are rendered exactly like the application's.
_SHARED_PROCESSORS = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
]


def _level_number(level: str | int) -> int:

    if isinstance(level, int):
        return level

    return logging.getLevelNamesMapping().get(level.upper(), logging.INFO)


def configure_logging(level: str | int = logging.INFO) -> None:
    """Sends every logger to stdout through structlog's console renderer."""

    structlog.configure(
        processors=[
            *_SHARED_PROCESSORS,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_SHARED_PROCESSORS,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(_level_number(level))


def bind_request_context(**fields: str) -> None:

    structlog.contextvars.bind_contextvars(**fields)


def unbind_request_context(*fields: str) -> None:

    structlog.contextvars.unbind_contextvars(*fields)
