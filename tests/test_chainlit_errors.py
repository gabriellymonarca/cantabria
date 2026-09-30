"""Toda falha no processamento vira uma mensagem ao usuário.

O adapter registra a exceção, remove o placeholder e envia uma mensagem em
português com o protocolo do turno, sem relançar.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import chainlit as cl
import pytest

from contexts.auth.domain.user import User
from contexts.user_interaction.adapters.inbound.chainlit import (
    ChainlitAdapter,
    _failure_message,
)
from shared.protocol import protocol_of


class _FakeMessage:
    """Substitui `cl.Message`: registra o que foi enviado, atualizado e removido."""

    sent: list[_FakeMessage] = []
    removed: list[_FakeMessage] = []

    def __init__(self, content: str = "", **_: object):

        self.content = content
        self.id = f"m{len(_FakeMessage.sent) + 1}"

    async def send(self) -> _FakeMessage:

        _FakeMessage.sent.append(self)

        return self

    async def update(self) -> None:

        return None

    async def remove(self) -> None:

        _FakeMessage.removed.append(self)


class _FakeSession:
    def __init__(self) -> None:

        self._values: dict[str, object] = {}

    def get(self, key: str, default: object = None) -> object:

        return self._values.get(key, default)

    def set(self, key: str, value: object) -> None:

        self._values[key] = value


class _FailingPort:
    def __init__(self) -> None:

        self.calls = 0

    async def execute(
        self,
        *,
        user: User,
        session_id: str,
        trace_id: str,
        request: str,
        locale: str = "pt-BR",
    ):

        self.calls += 1

        raise RuntimeError("provedor indisponível")


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> ChainlitAdapter:

    _FakeMessage.sent = []
    _FakeMessage.removed = []

    monkeypatch.setattr(cl, "Message", _FakeMessage)
    monkeypatch.setattr(cl, "user_session", _FakeSession())
    monkeypatch.setattr(
        cl, "context", SimpleNamespace(session=SimpleNamespace(thread_id="thread-1"))
    )

    instance = ChainlitAdapter.__new__(ChainlitAdapter)
    instance._port = _FailingPort()

    return instance


def test_mensagem_de_falha_e_em_portugues_com_protocolo() -> None:

    text = _failure_message("abc123def456")

    assert text.startswith("Não consegui processar sua pergunta agora.")
    assert "Tente reformular" in text
    assert "(protocolo CAN-ABC123DE)" in text
    assert "abc123def456" not in text


def test_falha_no_port_envia_mensagem_ao_usuario_sem_relancar(
    adapter: ChainlitAdapter,
) -> None:

    incoming = SimpleNamespace(id="user-msg", content="Qual a rentabilidade?")

    asyncio.run(adapter._on_message(incoming))  # type: ignore[arg-type]

    assert adapter._port.calls == 1  # type: ignore[attr-defined]

    placeholder, failure = _FakeMessage.sent

    assert placeholder in _FakeMessage.removed
    assert failure.content.startswith("Não consegui processar sua pergunta agora.")
    assert "(protocolo CAN-" in failure.content


def test_falha_ao_resolver_usuario_tambem_vira_mensagem(
    adapter: ChainlitAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    # Metadata inesperado na sessão explode ANTES do processamento; ainda
    # assim o usuário precisa receber a mensagem com a referência.
    def _broken_resolve() -> User:

        raise KeyError("metadata")

    monkeypatch.setattr(adapter, "_resolve_user", _broken_resolve)

    incoming = SimpleNamespace(id="user-msg", content="Qual a rentabilidade?")

    asyncio.run(adapter._on_message(incoming))  # type: ignore[arg-type]

    assert adapter._port.calls == 0  # type: ignore[attr-defined]

    (failure,) = _FakeMessage.sent

    assert failure.content.startswith("Não consegui processar sua pergunta agora.")


def test_referencia_da_mensagem_e_o_trace_id_do_turno(
    adapter: ChainlitAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    bound: dict[str, str] = {}

    def _bind(**fields: str) -> None:

        bound.update(fields)

    monkeypatch.setattr(
        "contexts.user_interaction.adapters.inbound.chainlit.bind_request_context",
        _bind,
    )

    incoming = SimpleNamespace(id="user-msg", content="Qual a rentabilidade?")

    asyncio.run(adapter._on_message(incoming))  # type: ignore[arg-type]

    failure = _FakeMessage.sent[-1]

    assert protocol_of(bound["trace_id"]) in failure.content
