from collections.abc import Mapping, Sequence
from typing import Any, cast

import structlog
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr, ValidationError

from contexts.financial_analysis.ports.outbound.llm_port import (
    LlmMessage,
    LlmPort,
    LlmReply,
    LlmUsage,
    StructuredOutput,
    StructuredOutputError,
)
from cross_cutting.config import LlmConfig

logger = structlog.get_logger(__name__)

_MESSAGE_TYPES: dict[str, type[BaseMessage]] = {
    "system": SystemMessage,
    "user": HumanMessage,
    "assistant": AIMessage,
}

_MAX_RETRIES = 2
_MAX_DETAIL_CHARS = 500

# Falhas de parsing/validação do output estruturado. Erros de rede e de
# provedor (openai.APIError) não entram aqui: eles não são falha de schema.
# ValueError/TypeError genéricos também ficam de fora: mascarariam bugs do
# adapter como "reformule sua pergunta".
_SCHEMA_ERRORS: tuple[type[Exception], ...] = (
    ValidationError,
    OutputParserException,
)


# Outbound (driven) adapter: translates the LlmPort contract into LangChain
# calls against an OpenAI-compatible endpoint. LangChain stays confined here.
class LangChainLlmAdapter(LlmPort):
    """Calls an OpenAI-compatible endpoint through LangChain."""

    def __init__(self, config: LlmConfig):

        self._model = config.model
        self._session_header = config.session_header
        self._client = ChatOpenAI(
            model=config.model,
            base_url=config.base_url,
            api_key=SecretStr(config.api_key),
            temperature=config.temperature,
            timeout=config.timeout,
            max_retries=_MAX_RETRIES,
            default_headers=config.headers,
        )
        self._structured: dict[type, Any] = {}

    async def generate(
        self,
        messages: Sequence[LlmMessage],
        session_id: str | None = None,
        step: str = "llm",
    ) -> LlmReply:

        kwargs: dict[str, Any] = {}
        if session_id and self._session_header:
            kwargs["extra_headers"] = {self._session_header: session_id}

        response = await self._client.ainvoke(_langchain_messages(messages), **kwargs)

        usage = _message_usage(response)
        self._log_usage(step, usage)

        return LlmReply(text=_text(response.content), model=self._model, usage=usage)

    async def generate_structured(
        self,
        messages: Sequence[LlmMessage],
        schema: type[StructuredOutput],
        session_id: str | None = None,
        step: str = "llm",
    ) -> StructuredOutput:

        # OpenAI-compatible providers (DeepSeek, Zen, ...) implement structured
        # output through tool calling; the json_schema response_format is
        # OpenAI-specific and the endpoint rejects it with a 400.
        # `include_raw=True` keeps the raw AIMessage, the only place where the
        # provider reports token usage for the structured call.
        # With `include_raw` the chain is `RunnableMap(raw=llm) | parser`; a
        # `.bind(extra_headers=...)` on that chain hands the kwarg to the map,
        # which does not forward it to the model. The header must be bound on
        # the model itself, so a session-scoped chain is built per call (the
        # extra kwargs of `with_structured_output` go to `bind_tools`); the
        # per-schema cache serves the calls without session.
        if session_id and self._session_header:
            runnable = self._structured_runnable(
                schema, extra_headers={self._session_header: session_id}
            )
        else:
            runnable = self._structured.get(schema)

            if runnable is None:
                runnable = self._structured_runnable(schema)
                self._structured[schema] = runnable

        try:
            output = await runnable.ainvoke(_langchain_messages(messages))
        except _SCHEMA_ERRORS as error:
            raise _as_structured_output_error(error) from error

        parsed, raw = _unpack_structured(output)
        self._log_usage(step, _message_usage(raw))

        # Sem tool call na resposta o parser devolve None.
        if parsed is None:
            raise StructuredOutputError(
                attempts=1, detail="o modelo não devolveu o output estruturado."
            )

        return cast(StructuredOutput, parsed)

    def _structured_runnable(self, schema: type[StructuredOutput], **model_kwargs):

        return self._client.with_structured_output(
            schema,
            method="function_calling",
            strict=False,
            include_raw=True,
            **model_kwargs,
        )

    def _log_usage(self, step: str, usage: LlmUsage | None) -> None:

        if usage is None:
            return

        logger.info(
            "LLM usage",
            step=step,
            prompt_tokens=usage.input_tokens,
            completion_tokens=usage.output_tokens,
            model=self._model,
        )


def _unpack_structured(output: Any) -> tuple[Any, Any]:
    """Separa `parsed` e `raw` do output com `include_raw`; erro de parsing
    vira o erro do port. Um output sem a chave `parsed` é devolvido como o
    próprio objeto parseado, sem mensagem bruta."""

    if not isinstance(output, dict) or "parsed" not in output:
        return output, None

    error = output.get("parsing_error")

    if isinstance(error, _SCHEMA_ERRORS):
        raise _as_structured_output_error(error) from error

    if isinstance(error, BaseException):
        raise error

    return output.get("parsed"), output.get("raw")


def _as_structured_output_error(error: Exception) -> StructuredOutputError:
    """Traduz a falha de parsing/validação do LangChain para o erro do port."""

    if isinstance(error, ValidationError):
        detail = _validation_detail(error)
    else:
        text = str(error).strip()
        detail = text.splitlines()[0] if text else type(error).__name__

    return StructuredOutputError(attempts=1, detail=detail[:_MAX_DETAIL_CHARS])


def _validation_detail(error: ValidationError) -> str:
    """Resume a falha pydantic: contagem, campo e mensagem do primeiro erro."""

    errors = error.errors()

    if not errors:
        return "erro de validação sem detalhe"

    location = ".".join(str(part) for part in errors[0]["loc"]) or "-"

    return (
        f"{error.error_count()} erro(s) de validação; "
        f"primeiro em '{location}': {errors[0]['msg']}"
    )


def _langchain_messages(messages: Sequence[LlmMessage]) -> list[BaseMessage]:

    return [
        _MESSAGE_TYPES[message.role](content=message.content) for message in messages
    ]


def _text(content: str | list[Any]) -> str:

    if isinstance(content, str):
        return content

    return "".join(
        block.get("text", "") for block in content if isinstance(block, dict)
    )


def _message_usage(message: Any) -> LlmUsage | None:
    """Uso de tokens da mensagem: `usage_metadata` ou `token_usage` do provedor."""

    if message is None:
        return None

    usage = _usage(getattr(message, "usage_metadata", None))

    if usage is not None:
        return usage

    response_metadata = getattr(message, "response_metadata", None) or {}

    return _token_usage(response_metadata.get("token_usage"))


def _usage(metadata: Mapping[str, Any] | None) -> LlmUsage | None:

    if not metadata:
        return None

    return LlmUsage(
        input_tokens=int(metadata.get("input_tokens", 0)),
        output_tokens=int(metadata.get("output_tokens", 0)),
    )


def _token_usage(metadata: Mapping[str, Any] | None) -> LlmUsage | None:

    if not metadata:
        return None

    return LlmUsage(
        input_tokens=int(metadata.get("prompt_tokens", 0)),
        output_tokens=int(metadata.get("completion_tokens", 0)),
    )
