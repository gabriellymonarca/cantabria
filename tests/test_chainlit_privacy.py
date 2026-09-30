"""Nenhum dado pessoal entra no trace.

O adapter Chainlit redige CPF/CNPJ/e-mail/telefone ANTES de abrir o span do
Langfuse; o port do user_interaction recebe o texto original (o handler redige
de novo antes de guardar na conversa e o guardrail da análise redige antes do
modelo) e o `trace_id` do turno vai junto no port e no span. O adapter não
guarda histórico: isso é da `Conversation` (ver `test_submit_question.py`).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import chainlit as cl
import pytest

from contexts.auth.domain.user import User
from contexts.financial_analysis.ports.inbound.user_request import Text
from contexts.user_interaction.adapters.inbound.chainlit import ChainlitAdapter
from shared.redaction import CPF_PLACEHOLDER

VALID_CPF = "529.982.247-25"


class _FakeMessage:
    def __init__(self, content: str = "", **_: object):

        self.content = content
        self.id = "m1"

    async def send(self) -> _FakeMessage:

        return self

    async def update(self) -> None:

        return None

    async def remove(self) -> None:

        return None


class _FakeSession:
    def __init__(self) -> None:

        self._values: dict[str, object] = {}

    def get(self, key: str, default: object = None) -> object:

        return self._values.get(key, default)

    def set(self, key: str, value: object) -> None:

        self._values[key] = value


class _RecordingPort:
    def __init__(self) -> None:

        self.request: str | None = None
        self.session_id: str | None = None
        self.trace_id: str | None = None

    async def execute(
        self,
        *,
        user: User,
        session_id: str,
        trace_id: str,
        request: str,
        locale: str = "pt-BR",
    ):

        self.request = request
        self.session_id = session_id
        self.trace_id = trace_id

        return [Text(text="Resposta.")]


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> _FakeSession:

    fake = _FakeSession()

    monkeypatch.setattr(cl, "Message", _FakeMessage)
    monkeypatch.setattr(cl, "user_session", fake)
    monkeypatch.setattr(
        cl, "context", SimpleNamespace(session=SimpleNamespace(thread_id="thread-1"))
    )

    return fake


@pytest.fixture
def traced(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:

    captured: dict[str, Any] = {}

    @contextlib.contextmanager
    def _fake_traced_request(
        user_id: str,
        session_id: str,
        request: str,
        trace_id: str | None = None,
        prompt_version: str = "",
    ) -> Iterator[Any]:

        captured.update(
            user_id=user_id,
            session_id=session_id,
            request=request,
            trace_id=trace_id,
            prompt_version=prompt_version,
        )

        yield lambda output: captured.update(output=output)

    monkeypatch.setattr(
        "contexts.user_interaction.adapters.inbound.chainlit.traced_request",
        _fake_traced_request,
    )

    return captured


@pytest.fixture
def adapter(session: _FakeSession) -> ChainlitAdapter:

    instance = ChainlitAdapter.__new__(ChainlitAdapter)
    instance._port = _RecordingPort()

    return instance


def test_cpf_nao_entra_no_span(
    adapter: ChainlitAdapter,
    session: _FakeSession,
    traced: dict[str, Any],
) -> None:

    incoming = SimpleNamespace(
        id="user-msg", content=f"Qual a rentabilidade do cliente {VALID_CPF}?"
    )

    asyncio.run(adapter._on_message(incoming))  # type: ignore[arg-type]

    assert VALID_CPF not in traced["request"]
    assert CPF_PLACEHOLDER in traced["request"]
    assert traced["output"] == "Resposta."


def test_port_recebe_o_texto_original_a_sessao_e_o_trace_id_do_turno(
    adapter: ChainlitAdapter,
    session: _FakeSession,
    traced: dict[str, Any],
) -> None:

    incoming = SimpleNamespace(
        id="user-msg", content=f"Qual a rentabilidade do cliente {VALID_CPF}?"
    )

    asyncio.run(adapter._on_message(incoming))  # type: ignore[arg-type]

    port: _RecordingPort = adapter._port  # type: ignore[assignment]

    assert port.request == incoming.content
    assert port.session_id == "thread-1"
    assert port.trace_id
    assert port.trace_id == traced["trace_id"]


def test_pergunta_sem_dado_pessoal_segue_intacta(
    adapter: ChainlitAdapter,
    session: _FakeSession,
    traced: dict[str, Any],
) -> None:

    incoming = SimpleNamespace(
        id="user-msg", content="Saldo em 31/08/2026 acima de 15%?"
    )

    asyncio.run(adapter._on_message(incoming))  # type: ignore[arg-type]

    assert traced["request"] == incoming.content
