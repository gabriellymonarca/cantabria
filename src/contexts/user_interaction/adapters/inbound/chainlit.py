"""Inbound Chainlit adapter: the UI server, the user request port and SSO.

The server wiring mirrors what `chainlit.cli.run_chainlit` does synchronously —
environment settings, uvicorn config — as a server the entrypoint can await and
control.
"""

import asyncio
import contextlib
import itertools
import json
import os
import signal
from collections.abc import Generator
from uuid import uuid4

import chainlit as cl
import structlog
import uvicorn
from chainlit.auth import ensure_jwt_secret
from chainlit.cache import init_lc_cache
from chainlit.config import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_ROOT_PATH, config
from chainlit.data import BaseDataLayer
from chainlit.element import Element
from pandas import DataFrame
from plotly.graph_objects import Figure

from contexts.auth.ports.inbound.authenticate_local_user_port import (
    AuthenticateLocalUserPort,
)
from contexts.auth.ports.inbound.authenticate_user_port import (
    AuthenticateUserPort,
    ExternalIdentity,
)
from contexts.auth.ports.inbound.authorize_port import Role, User
from contexts.financial_analysis.ports.inbound.user_request import (
    Content,
    Dataframe,
    Image,
    MethodNote,
    Plotly,
    Structured,
    Text,
)
from contexts.user_interaction.ports.inbound.user_request_port import UserRequestPort
from cross_cutting.logging import bind_request_context, unbind_request_context
from cross_cutting.observability import traced_request
from shared.protocol import protocol_of
from shared.redaction import redact_personal_identifiers

logger = structlog.get_logger(__name__)

# Locale do usuário (BCP-47): seleciona a superfície localizada do prompt. Sem
# detecção por conversa ainda, o v1 usa o default, configurável por ambiente.
_DEFAULT_LOCALE = os.environ.get("CANTABRIA_LOCALE", "pt-BR")

_THINKING_INTERVAL_SECONDS = 5.0
_THINKING_MESSAGES = (
    "Analisando sua pergunta...",
    "Consultando os dados...",
    "Preparando a resposta...",
)

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_SPINNER_TICK_SECONDS = 0.25
_TICKS_PER_MESSAGE = int(_THINKING_INTERVAL_SECONDS / _SPINNER_TICK_SECONDS)

_FAILURE_MESSAGE = (
    "Não consegui processar sua pergunta agora. Tente reformular ou repita em "
    "instantes. (protocolo {protocol})"
)

# Um starter: rótulo curto no cartão e a pergunta completa que ele envia.
Starter = tuple[str, str]


# uvicorn installs its own SIGINT/SIGTERM handlers inside serve() and has no
# public opt-out (uvicorn discussion #2965). Overriding capture_signals leaves
# the signals to the caller, which owns the shutdown orchestration.
class GracefulServer(uvicorn.Server):
    """uvicorn server whose shutdown signals are handled by the caller."""

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None]:

        yield

    def request_shutdown(self, sig: signal.Signals) -> None:
        """Requests a graceful shutdown; a second signal forces it."""

        if self.should_exit:
            logger.warning("Received signal again; forcing shutdown", signal=sig.name)
            self.force_exit = True
            return

        logger.info("Received signal; shutting down gracefully", signal=sig.name)
        self.should_exit = True


def build_server() -> GracefulServer:
    """Builds the uvicorn server from the Chainlit environment settings."""

    config.run.host = os.environ.get("CHAINLIT_HOST", DEFAULT_HOST)
    config.run.port = int(os.environ.get("CHAINLIT_PORT", DEFAULT_PORT))
    config.run.root_path = os.environ.get("CHAINLIT_ROOT_PATH", DEFAULT_ROOT_PATH)

    ws_per_message_deflate = os.environ.get(
        "UVICORN_WS_PER_MESSAGE_DEFLATE", "true"
    ).lower() in {"1", "true", "yes"}

    # "chainlit.server:app" is an import string: chainlit.server derives the
    # socket.io path and the router prefix from config.run.root_path at import
    # time, so uvicorn loads it at serve() time, after the settings above.
    #
    # log_config=None keeps uvicorn from replacing the structured root handler;
    # its loggers propagate to it.
    return GracefulServer(
        uvicorn.Config(
            "chainlit.server:app",
            host=config.run.host,
            port=config.run.port,
            ws=os.environ.get("UVICORN_WS_PROTOCOL", "auto"),
            ws_per_message_deflate=ws_per_message_deflate,
            ssl_keyfile=os.environ.get("CHAINLIT_SSL_KEY"),
            ssl_certfile=os.environ.get("CHAINLIT_SSL_CERT"),
            log_config=None,
            log_level="debug" if config.run.debug else "error",
        )
    )


# Chainlit turns login on when an auth hook is registered: the oauth hook only
# when the Google credentials are present, the password hook when local login
# is enabled. Without either the app runs without login, for local development.
def _google_sso_configured() -> bool:

    return bool(
        os.environ.get("OAUTH_GOOGLE_CLIENT_ID")
        and os.environ.get("OAUTH_GOOGLE_CLIENT_SECRET")
    )


def _failure_message(trace_id: str) -> str:
    """Mensagem ao usuário quando o turno falha; carrega o protocolo do turno."""

    return _FAILURE_MESSAGE.format(protocol=protocol_of(trace_id))


def _text(contents: list[Content]) -> str:
    """Renders the contents the way the UI shows them."""

    blocks: list[str] = []

    for content in contents:
        if isinstance(content, Text):
            blocks.append(content.text)
        elif isinstance(content, Structured):
            payload = json.dumps(content.data, indent=2, ensure_ascii=False)
            blocks.append(f"```json\n{payload}\n```")

    return "\n\n".join(blocks)


def _elements(contents: list[Content]) -> list[Element]:
    """Builds the Chainlit elements for the non-textual contents."""

    elements: list[Element] = []

    for content in contents:
        match content:
            case Image():
                elements.append(cl.Image(content=content.data, mime=content.mime_type))
            case Dataframe():
                frame = DataFrame(content.rows, columns=content.columns)
                elements.append(cl.Dataframe(data=frame))
            case Plotly():
                figure = Figure(content.figure)
                elements.append(cl.Plotly(figure=figure))

    return elements


def _method_notes(contents: list[Content]) -> list[MethodNote]:

    return [content for content in contents if isinstance(content, MethodNote)]


async def _send_method_note(note: MethodNote) -> None:
    """A nota "Como calculei" é um passo recolhível, separado do texto da
    mensagem: quem quiser ver o método abre; quem não quiser não é
    interrompido por ele."""

    async with cl.Step(name=note.title, type="tool", show_input=False) as step:
        step.output = note.text


# Inbound (driving) adapter: translates Chainlit UI events into calls to the
# user_interaction inbound port. It is the only piece that knows Chainlit; the
# queries and the ports stay framework-agnostic.
#
# The constructor concentrates the semi-private Chainlit/uvicorn wiring
# (config.run, JWT secret, cache, hooks and server); `run` only serves and
# handles the shutdown signals.
class ChainlitAdapter:
    # Defaults dos starters e da versão de prompt: instâncias montadas fora do
    # `__init__` (testes) seguem sem registrar `set_starters`.
    _starters: tuple[Starter, ...] = ()
    _prompt_version: str = ""

    def __init__(
        self,
        port: UserRequestPort,
        authenticate: AuthenticateUserPort,
        local_authenticate: AuthenticateLocalUserPort | None = None,
        data_layer: BaseDataLayer | None = None,
        starters: tuple[Starter, ...] = (),
        prompt_version: str = "",
    ):
        """Os starters são determinísticos e vêm do composition root (gerados
        do catálogo ativo); sem eles a tela inicial fica só com o nome e a
        descrição do assistente. `prompt_version` vai ao metadata do trace."""

        self._port = port
        self._authenticate = authenticate
        self._local_authenticate = local_authenticate
        self._starters = tuple(starters)
        self._prompt_version = prompt_version

        config.run.headless = True
        init_lc_cache()

        # Com data layer e login, o Chainlit mostra a barra lateral de sessões
        # lendo/escrevendo a mesma coleção de conversas do store.
        if data_layer is not None:
            cl.data_layer(lambda: data_layer)
            logger.info("Session sidebar enabled (MongoDB data layer)")

        self._server = build_server()

        # Registering the oauth hook turns login on, so the JWT secret becomes
        # mandatory at startup; the check runs after the registration.
        self._register_callbacks()
        ensure_jwt_secret()

    async def run(self) -> None:
        """Serves the UI until a shutdown signal arrives."""

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._server.request_shutdown, sig)

        await self._server.serve()

    def _register_callbacks(self) -> None:

        cl.on_message(self._on_message)

        # Starters e mensagem de abertura competem pela tela inicial no
        # Chainlit 2.12: com starters registrados, nenhuma `cl.Message` é
        # enviada em `on_chat_start`.
        if self._starters:
            cl.set_starters(self._on_starters)

        if _google_sso_configured():
            cl.oauth_callback(self._on_oauth_callback)

        if self._local_authenticate is not None:
            cl.password_auth_callback(self._on_password_callback)

    async def _on_starters(self, user: cl.User | None = None) -> list[cl.Starter]:
        """Cartões da tela inicial: determinísticos, gerados do catálogo, sem
        LLM. Cada clique envia a pergunta completa pelo caminho normal."""

        return [
            cl.Starter(label=label, message=message)
            for label, message in self._starters
        ]

    async def _on_message(self, message: cl.Message) -> None:

        trace_id = uuid4().hex

        # A falha é capturada aqui e o usuário recebe uma mensagem com a referência.
        # Resolver usuário/sessão também fica dentro do try: é onde metadata
        # inesperado costuma explodir.
        try:
            user = self._resolve_user()
            session_id = cl.context.session.thread_id

            bind_request_context(
                trace_id=trace_id,
                session_id=session_id,
                user_id=user.id,
            )

            await self._handle_message(message, user, session_id, trace_id)
        except Exception:
            logger.exception("User message failed", message_id=message.id)
            await self._report_failure(trace_id)
        finally:
            unbind_request_context("trace_id", "session_id", "user_id")

    async def _report_failure(self, trace_id: str) -> None:

        try:
            await cl.Message(content=_failure_message(trace_id)).send()
        except Exception:
            logger.exception("Failure message could not be sent")

    async def _handle_message(
        self, message: cl.Message, user: User, session_id: str, trace_id: str
    ) -> None:

        logger.info("User message received", message_id=message.id)

        # Dados pessoais são redigidos ANTES de entrar no trace; o port recebe
        # o texto original e a aplicação redige de novo (idempotente) antes de
        # guardar no histórico e de qualquer chamada ao modelo. O histórico é
        # da `Conversation` (contexto user_interaction), não da sessão da UI.
        redacted = redact_personal_identifiers(message.content).text

        placeholder = cl.Message(
            content=f"{_SPINNER_FRAMES[0]} {_THINKING_MESSAGES[0]}"
        )
        await placeholder.send()
        rotation = asyncio.create_task(self._rotate(placeholder))

        try:
            with traced_request(
                user.id,
                session_id,
                redacted,
                trace_id=trace_id,
                prompt_version=self._prompt_version,
            ) as record_output:
                contents = await self._port.execute(
                    user=user,
                    session_id=session_id,
                    trace_id=trace_id,
                    request=message.content,
                    locale=_DEFAULT_LOCALE,
                )
                record_output(_text(contents))
        except Exception:
            await placeholder.remove()
            raise
        finally:
            rotation.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await rotation

        await self._finalize(placeholder, contents)

        logger.info("User message answered", message_id=message.id)

    async def _rotate(self, message: cl.Message) -> None:

        frames = itertools.cycle(_SPINNER_FRAMES)
        texts = itertools.cycle(_THINKING_MESSAGES)
        next(frames)  # the placeholder already shows the first frame
        next(texts)  # ... and the first text

        message_text = _THINKING_MESSAGES[0]
        ticks = 0

        while True:
            await asyncio.sleep(_SPINNER_TICK_SECONDS)
            ticks += 1

            if ticks >= _TICKS_PER_MESSAGE:
                message_text = next(texts)
                ticks = 0

            message.content = f"{next(frames)} {message_text}"
            await message.update()

    async def _on_oauth_callback(
        self,
        provider_id: str,
        token: str,
        raw_user_data: dict,
        default_user: cl.User,
        # Only the Azure AD hybrid flow passes id_token; Google does not.
        id_token: str | None = None,
    ) -> cl.User | None:

        email = raw_user_data.get("email") or default_user.identifier
        identity = ExternalIdentity(
            provider=provider_id,
            subject=str(raw_user_data.get("id") or email),
            email=email,
            email_verified=bool(raw_user_data.get("verified_email")),
            name=raw_user_data.get("name"),
            hosted_domain=raw_user_data.get("hd"),
            picture=raw_user_data.get("picture"),
        )

        user = await self._authenticate.execute(identity)

        if user is None:
            logger.warning(
                "OAuth identity rejected", provider=provider_id, email=identity.email
            )
            return None

        logger.info("OAuth login accepted", provider=provider_id, user_id=user.id)

        return cl.User(
            identifier=user.email,
            display_name=user.name,
            metadata={
                "user_id": user.id,
                "provider": provider_id,
                "roles": [role.id for role in user.roles],
            },
        )

    async def _on_password_callback(
        self,
        username: str,
        password: str,
    ) -> cl.User | None:

        if self._local_authenticate is None:
            return None

        user = await self._local_authenticate.execute(username, password)

        if user is None:
            logger.warning("Local login rejected", username=username)
            return None

        logger.info("Local login accepted", user_id=user.id)

        return cl.User(
            identifier=user.email or user.id,
            display_name=user.name,
            metadata={
                "user_id": user.id,
                "provider": "local",
                "roles": [role.id for role in user.roles],
            },
        )

    def _resolve_user(self) -> User:

        chainlit_user = cl.user_session.get("user")

        if chainlit_user is None:
            return User(id="anonymous", name="Anonymous", email="", roles=[])

        metadata = chainlit_user.metadata or {}
        roles = [Role(id=role, name=role) for role in metadata.get("roles", [])]

        return User(
            id=metadata.get("user_id") or chainlit_user.identifier,
            name=chainlit_user.display_name or chainlit_user.identifier,
            email=chainlit_user.identifier,
            roles=roles,
        )

    async def _finalize(self, message: cl.Message, contents: list[Content]) -> None:

        if not contents:
            await message.remove()
            return

        message.content = _text(contents)
        await message.update()

        for element in _elements(contents):
            await element.send(for_id=message.id)

        for note in _method_notes(contents):
            await _send_method_note(note)
