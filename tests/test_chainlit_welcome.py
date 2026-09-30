"""Tela inicial e nota de método no Chainlit.

Os starters são determinísticos (gerados do catálogo) e substituem a mensagem
de boas-vindas: com starters, `set_starters` é registrado e nenhum
`on_chat_start` envia texto; sem starters, nada é registrado. A nota "Como
calculei" (`MethodNote`) vira um `cl.Step` recolhível, fora do texto da
mensagem.
"""

from __future__ import annotations

import asyncio

import chainlit as cl
import pytest

from contexts.auth.domain.user import User
from contexts.financial_analysis.ports.inbound.user_request import MethodNote, Text
from contexts.user_interaction.adapters.inbound.chainlit import ChainlitAdapter


class _FakeMessage:
    sent: list[_FakeMessage] = []

    def __init__(self, content: str = "", **_: object):

        self.content = content
        self.id = f"m{len(_FakeMessage.sent) + 1}"

    async def send(self) -> _FakeMessage:

        _FakeMessage.sent.append(self)

        return self

    async def update(self) -> None:

        return None


class _FakeStep:
    opened: list[_FakeStep] = []

    def __init__(self, name: str = "", type: str = "undefined", **kwargs: object):

        self.name = name
        self.type = type
        self.kwargs = kwargs
        self.output = ""

    async def __aenter__(self) -> _FakeStep:

        _FakeStep.opened.append(self)

        return self

    async def __aexit__(self, *exc: object) -> None:

        return None


class _RecordingPort:
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

        return []


def _callbacks(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[object]]:

    registered: dict[str, list[object]] = {"starters": [], "chat_start": []}

    monkeypatch.setattr(cl, "on_message", lambda func: None)
    monkeypatch.setattr(cl, "set_starters", registered["starters"].append)
    monkeypatch.setattr(cl, "on_chat_start", registered["chat_start"].append)
    monkeypatch.delenv("OAUTH_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("OAUTH_GOOGLE_CLIENT_SECRET", raising=False)

    return registered


def test_sem_starters_nao_registra_set_starters_nem_on_chat_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    registered = _callbacks(monkeypatch)

    adapter = ChainlitAdapter.__new__(ChainlitAdapter)
    adapter._local_authenticate = None
    adapter._starters = ()

    adapter._register_callbacks()

    assert registered == {"starters": [], "chat_start": []}


def test_com_starters_registra_set_starters_e_nao_envia_boas_vindas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    registered = _callbacks(monkeypatch)

    adapter = ChainlitAdapter.__new__(ChainlitAdapter)
    adapter._port = _RecordingPort()
    adapter._local_authenticate = None
    adapter._starters = (("Rótulo", "Pergunta completa?"),)

    adapter._register_callbacks()

    starters = asyncio.run(adapter._on_starters(None))

    assert registered["starters"] == [adapter._on_starters]
    assert registered["chat_start"] == []
    assert [(item.label, item.message) for item in starters] == [
        ("Rótulo", "Pergunta completa?")
    ]
    assert adapter._port.calls == 0  # type: ignore[attr-defined]


def test_method_note_vira_step_recolhivel_fora_do_texto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    _FakeMessage.sent = []
    _FakeStep.opened = []

    monkeypatch.setattr(cl, "Message", _FakeMessage)
    monkeypatch.setattr(cl, "Step", _FakeStep)

    adapter = ChainlitAdapter.__new__(ChainlitAdapter)
    placeholder = _FakeMessage(content="…")
    contents = [
        Text(text="Explicação."),
        MethodNote(title="Como calculei", text="- Métrica: rentabilidade."),
    ]

    asyncio.run(adapter._finalize(placeholder, contents))  # type: ignore[arg-type]

    (step,) = _FakeStep.opened

    assert placeholder.content == "Explicação."
    assert "Como calculei" not in placeholder.content
    assert step.name == "Como calculei"
    assert step.type == "tool"
    assert step.output == "- Métrica: rentabilidade."


def test_sem_method_note_nenhum_step_e_aberto(monkeypatch: pytest.MonkeyPatch) -> None:

    _FakeStep.opened = []

    monkeypatch.setattr(cl, "Step", _FakeStep)

    adapter = ChainlitAdapter.__new__(ChainlitAdapter)

    asyncio.run(adapter._finalize(_FakeMessage(), [Text(text="Só texto.")]))  # type: ignore[arg-type]

    assert _FakeStep.opened == []
