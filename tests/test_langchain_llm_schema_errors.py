"""O adapter LangChain traduz falha de schema para o erro do port.

`ValidationError` (pydantic), `OutputParserException` (LangChain) e os
`ValueError`/`TypeError` do parser viram `StructuredOutputError`; assim a
aplicação decide o retry sem conhecer LangChain. Erros de provedor ou de rede
não são falha de schema e passam intactos.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from contexts.financial_analysis.adapters.outbound.langchain_llm import (
    LangChainLlmAdapter,
    _as_structured_output_error,
)
from contexts.financial_analysis.ports.outbound.llm_port import (
    LlmMessage,
    StructuredOutputError,
)
from cross_cutting.config import LlmConfig


class _Schema(BaseModel):
    route: str


class _FakeRunnable:
    def __init__(self, outcome: Exception | Any):

        self._outcome = outcome

    async def ainvoke(self, messages: Any) -> Any:

        if isinstance(self._outcome, Exception):
            raise self._outcome

        return self._outcome


def _adapter(outcome: Exception | Any) -> LangChainLlmAdapter:

    adapter = LangChainLlmAdapter(
        LlmConfig(
            model="fake",
            base_url="http://localhost:1/v1",
            api_key="x",
            temperature=0.0,
            timeout=1.0,
            headers={},
            session_header="",
        )
    )
    adapter._structured[_Schema] = _FakeRunnable(outcome)

    return adapter


def _generate(adapter: LangChainLlmAdapter) -> Any:

    return asyncio.run(
        adapter.generate_structured([LlmMessage(role="user", content="oi")], _Schema)
    )


def _validation_error() -> ValidationError:

    try:
        _Schema.model_validate({"route": 12.5, "extra": 1})
    except ValidationError as error:
        return error

    raise AssertionError("model_validate deveria falhar.")


def test_validation_error_vira_structured_output_error() -> None:

    with pytest.raises(StructuredOutputError) as raised:
        _generate(_adapter(_validation_error()))

    assert raised.value.attempts == 1
    assert "route" in raised.value.detail


def test_output_parser_exception_vira_structured_output_error() -> None:

    with pytest.raises(StructuredOutputError) as raised:
        _generate(_adapter(OutputParserException("Could not parse tool call")))

    assert "Could not parse" in raised.value.detail


def test_value_error_e_type_error_genericos_nao_sao_mascarados() -> None:
    """Bug do adapter não pode virar "reformule sua pergunta": sobe como está."""

    with pytest.raises(ValueError):
        _generate(_adapter(ValueError("bad json")))

    with pytest.raises(TypeError):
        _generate(_adapter(TypeError("NoneType is not subscriptable")))


def test_resposta_sem_tool_call_vira_structured_output_error() -> None:
    """Sem tool call o parser devolve None; isso é falha de schema, não sucesso."""

    with pytest.raises(StructuredOutputError):
        _generate(_adapter(None))


def test_erro_de_provedor_nao_e_mascarado_como_schema() -> None:

    with pytest.raises(ConnectionError):
        _generate(_adapter(ConnectionError("refused")))


def test_output_valido_passa_intacto() -> None:

    assert _generate(_adapter(_Schema(route="clarify"))).route == "clarify"


def _raw_output(
    parsed: Any,
    parsing_error: BaseException | None = None,
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    """A forma que `with_structured_output(..., include_raw=True)` devolve."""

    raw = AIMessage(content="", usage_metadata=usage)  # type: ignore[arg-type]

    return {"raw": raw, "parsed": parsed, "parsing_error": parsing_error}


def test_include_raw_com_parsed_passa_intacto() -> None:

    output = _raw_output(_Schema(route="clarify"))

    assert _generate(_adapter(output)).route == "clarify"


def test_include_raw_com_parsing_error_vira_structured_output_error() -> None:

    output = _raw_output(None, parsing_error=_validation_error())

    with pytest.raises(StructuredOutputError) as raised:
        _generate(_adapter(output))

    assert "route" in raised.value.detail


def test_include_raw_com_erro_generico_nao_e_mascarado() -> None:

    output = _raw_output(None, parsing_error=ValueError("bad json"))

    with pytest.raises(ValueError):
        _generate(_adapter(output))


def test_include_raw_sem_parsed_nem_erro_e_falha_de_schema() -> None:

    with pytest.raises(StructuredOutputError):
        _generate(_adapter(_raw_output(None)))


def test_uso_de_tokens_do_output_estruturado_e_registrado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Com `include_raw` a mensagem bruta traz `usage_metadata`; o adapter loga
    prompt/completion tokens rotulados com o `step` do chamador."""

    records: list[dict[str, Any]] = []

    class _Logger:
        def info(self, event: str, **fields: Any) -> None:

            records.append({"event": event, **fields})

    monkeypatch.setattr(
        "contexts.financial_analysis.adapters.outbound.langchain_llm.logger",
        _Logger(),
    )

    output = _raw_output(
        _Schema(route="clarify"),
        usage={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
    )
    adapter = _adapter(output)

    asyncio.run(
        adapter.generate_structured(
            [LlmMessage(role="user", content="oi")], _Schema, step="planner"
        )
    )

    (record,) = records

    assert record["event"] == "LLM usage"
    assert record["step"] == "planner"
    assert record["prompt_tokens"] == 120
    assert record["completion_tokens"] == 30
    assert record["model"] == "fake"


def test_sem_usage_metadata_nao_ha_log_de_uso(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    records: list[str] = []

    class _Logger:
        def info(self, event: str, **fields: Any) -> None:

            records.append(event)

    monkeypatch.setattr(
        "contexts.financial_analysis.adapters.outbound.langchain_llm.logger",
        _Logger(),
    )

    _generate(_adapter(_raw_output(_Schema(route="clarify"))))

    assert records == []


def _tool_call_result(name: str, args: dict[str, Any]) -> ChatResult:

    message = AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": "call_1", "type": "tool_call"}],
    )

    return ChatResult(generations=[ChatGeneration(message=message)])


def test_header_de_sessao_chega_ao_modelo_no_output_estruturado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Com `include_raw=True` a cadeia é `RunnableMap(raw=llm) | parser`; um
    `.bind(extra_headers=...)` nessa cadeia entrega o kwarg ao RunnableMap,
    que NÃO o repassa ao modelo. O header tem de ser ligado ao próprio modelo:
    aqui se prova que chega aos kwargs da chamada de geração."""

    captured: dict[str, Any] = {}

    async def fake_agenerate(self, messages, stop=None, run_manager=None, **kwargs):

        captured.update(kwargs)

        return _tool_call_result(_Schema.__name__, {"route": "clarify"})

    monkeypatch.setattr(ChatOpenAI, "_agenerate", fake_agenerate)

    adapter = LangChainLlmAdapter(
        LlmConfig(
            model="fake",
            base_url="http://localhost:1/v1",
            api_key="x",
            temperature=0.0,
            timeout=1.0,
            headers={},
            session_header="X-Session",
        )
    )

    result = asyncio.run(
        adapter.generate_structured(
            [LlmMessage(role="user", content="oi")], _Schema, session_id="abc"
        )
    )

    assert result.route == "clarify"
    assert captured["extra_headers"] == {"X-Session": "abc"}
    assert captured["tool_choice"]


def test_sem_sessao_o_header_nao_e_enviado_e_a_cadeia_e_reutilizada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    captured: list[dict[str, Any]] = []

    async def fake_agenerate(self, messages, stop=None, run_manager=None, **kwargs):

        captured.append(kwargs)

        return _tool_call_result(_Schema.__name__, {"route": "clarify"})

    monkeypatch.setattr(ChatOpenAI, "_agenerate", fake_agenerate)

    adapter = LangChainLlmAdapter(
        LlmConfig(
            model="fake",
            base_url="http://localhost:1/v1",
            api_key="x",
            temperature=0.0,
            timeout=1.0,
            headers={},
            session_header="X-Session",
        )
    )

    for _ in range(2):
        asyncio.run(
            adapter.generate_structured(
                [LlmMessage(role="user", content="oi")], _Schema
            )
        )

    assert all("extra_headers" not in kwargs for kwargs in captured)
    assert list(adapter._structured) == [_Schema]


def test_mapeamento_resume_validation_error_sem_conteudo_do_prompt() -> None:

    mapped = _as_structured_output_error(_validation_error())

    assert mapped.attempts == 1
    assert "erro(s) de validação" in mapped.detail
    assert "route" in mapped.detail
    assert "oi" not in mapped.detail
