"""Langfuse tracing bootstrap for the application.

The Langfuse SDK owns the global OpenTelemetry tracer provider and exports to
the self-hosted stack (compose.yaml, profile `observability`). LangChain is instrumented with
OpenInference, so every ``ChatOpenAI`` call creates spans that the Langfuse
span processor picks up from the same provider.

Credentials come from the ``observability`` section of config.yaml.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import structlog

from cross_cutting.config import ObservabilityConfig

logger = structlog.get_logger(__name__)

_client: Any | None = None


def is_enabled() -> bool:

    return _client is not None


def configure_observability(config: ObservabilityConfig) -> None:
    """Starts tracing when enabled; otherwise leaves the application untouched."""

    global _client

    if not config.enabled:
        logger.warning(
            "Tracing disabled",
            hint="set observability.enabled=true to export LangChain traces",
        )

        return

    from langfuse import Langfuse

    # The client must exist before the instrumentor: it registers the span
    # processor on the global tracer provider that OpenInference then uses.
    _client = Langfuse(
        public_key=config.public_key,
        secret_key=config.secret_key,
        host=config.host,
        environment=config.environment,
        release=config.release or None,
    )

    from openinference.instrumentation.langchain import LangChainInstrumentor

    LangChainInstrumentor().instrument()

    logger.info(
        "Tracing enabled",
        host=config.host,
        environment=config.environment,
    )


def shutdown_observability() -> None:
    """Flushes buffered spans; safe to call when tracing is disabled."""

    global _client

    if _client is None:
        return

    _client.shutdown()
    _client = None


def _ignore_output(output: str) -> None:
    """No-op output recorder used while tracing is disabled."""


def _span_metadata(trace_id: str | None, prompt_version: str) -> dict[str, str] | None:
    """Metadata do span raiz: só as chaves informadas; `None` quando nenhuma."""

    metadata: dict[str, str] = {}

    if trace_id:
        metadata["cantabria.trace_id"] = trace_id

    if prompt_version:
        metadata["cantabria.prompt_version"] = prompt_version

    return metadata or None


# Groups one user turn into a single trace and records the actor and session on
# every span of that trace. The yielded callable stores the response so the
# trace shows input and output even when it has no child observations.
#
# `request` must already be redacted by the caller: whatever is passed here
# becomes the span input. `trace_id` is the turn id created by the inbound
# adapter; it goes into the span metadata (`cantabria.trace_id`) so the trace
# can be found from the log line or the user-facing reference (`CAN-` + the
# first eight characters). `prompt_version` is the effective prompt contract
# of the process (`cantabria.prompt_version`), so a trace can be replayed
# against the prompts that produced it.
@contextmanager
def traced_request(
    user_id: str,
    session_id: str,
    request: str,
    trace_id: str | None = None,
    prompt_version: str = "",
) -> Iterator[Callable[[str], None]]:

    if _client is None:
        yield _ignore_output
        return

    from langfuse import propagate_attributes
    from openinference.instrumentation import using_attributes

    metadata = _span_metadata(trace_id, prompt_version)

    with propagate_attributes(user_id=user_id, session_id=session_id):
        with _client.start_as_current_observation(
            as_type="span",
            name="user-request",
            input=request,
            metadata=metadata,
        ) as span:
            with using_attributes(
                user_id=user_id, session_id=session_id, metadata=metadata
            ):
                yield lambda output: span.update(output=output)
