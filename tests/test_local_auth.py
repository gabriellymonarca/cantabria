"""Login local e papéis: da credencial demo até as capabilities por role.

Sem Google SSO o app roda anônimo; com `auth.local_login_enabled` a UI passa
a exigir usuário/senha (`data/auth/users.yaml`, senha demo `cantabria123`) e
os papéis fluem para `User.roles`, de onde o adapter de capabilities resolve
o que cada papel pode ver (`analista` é restrito, `admin`/`default` é total).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import chainlit as cl
import yaml

from contexts.auth.adapters.outbound.yaml_capabilities import (
    YamlCapabilitiesAdapter,
)
from contexts.auth.adapters.outbound.yaml_local_user_store import (
    YamlLocalUserStoreAdapter,
)
from contexts.auth.application.queries.authenticate import AuthenticateUserQuery
from contexts.auth.application.queries.authenticate_local import (
    AuthenticateLocalUserQuery,
    hash_password,
)
from contexts.auth.application.queries.authorize import AuthorizeQuery
from contexts.auth.domain.user import Role, User
from contexts.auth.ports.inbound.authenticate_user_port import ExternalIdentity
from contexts.financial_analysis.adapters.outbound.auth_capacity_acl import (
    AuthCapacityAcl,
)
from contexts.user_interaction.adapters.inbound.chainlit import ChainlitAdapter

_DEMO_PASSWORD = "cantabria123"

_USERS_FILE = Path(__file__).resolve().parents[1] / "data" / "auth" / "users.yaml"


def _identity(
    email: str = "ana@example.com",
    *,
    verified: bool = True,
    domain: str | None = None,
) -> ExternalIdentity:

    return ExternalIdentity(
        provider="google",
        subject="sub-1",
        email=email,
        email_verified=verified,
        name="Ana",
        hosted_domain=domain,
    )


def _store(tmp_path: Path) -> YamlLocalUserStoreAdapter:

    path = tmp_path / "users.yaml"

    path.write_text(
        yaml.safe_dump(
            {
                "users": [
                    {
                        "username": "analista",
                        "name": "Analista Demo",
                        "email": "analista@cantabria.local",
                        "password_sha256": hash_password(_DEMO_PASSWORD),
                        "roles": ["analista"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    return YamlLocalUserStoreAdapter(path)


def test_store_resolve_caminho_sem_depender_do_checkout(
    tmp_path: Path, monkeypatch
) -> None:

    # No container o pacote vive em site-packages (sem pyproject.toml acima):
    # caminho absoluto vale como está e relativo resolve contra o cwd.
    store = _store(tmp_path)
    monkeypatch.setattr(
        "contexts.auth.adapters.outbound.yaml_local_user_store._project_root",
        lambda: (_ for _ in ()).throw(AssertionError("não deveria procurar a raiz")),
    )

    assert YamlLocalUserStoreAdapter(store._path).find_by_username("analista")

    monkeypatch.chdir(tmp_path)

    assert YamlLocalUserStoreAdapter("users.yaml").find_by_username("analista")


def test_sso_sem_mapa_mantem_roles_vazios() -> None:

    query = AuthenticateUserQuery()

    user = asyncio.run(query.execute(_identity()))

    assert user is not None
    assert user.roles == ()


def test_sso_resolve_papeis_pelo_email() -> None:

    query = AuthenticateUserQuery(
        role_map={"ana@example.com": ["analista"]},
        default_roles=["default"],
    )

    mapped = asyncio.run(query.execute(_identity()))
    fallback = asyncio.run(query.execute(_identity("outra@example.com")))

    assert mapped is not None
    assert [role.id for role in mapped.roles] == ["analista"]

    assert fallback is not None
    assert [role.id for role in fallback.roles] == ["default"]


def test_sso_recusa_nao_verificado_e_dominio() -> None:

    query = AuthenticateUserQuery(allowed_domains=["example.com"])

    assert asyncio.run(query.execute(_identity(verified=False))) is None
    assert asyncio.run(query.execute(_identity(domain="other.com"))) is None
    assert asyncio.run(query.execute(_identity(domain="example.com"))) is not None


def test_login_local_aceita_senha_e_carrega_papeis(tmp_path: Path) -> None:

    query = AuthenticateLocalUserQuery(_store(tmp_path))

    user = asyncio.run(query.execute("analista", _DEMO_PASSWORD))

    assert user is not None
    assert user.id == "analista"
    assert [role.id for role in user.roles] == ["analista"]


def test_login_local_recusa_senha_e_usuario(tmp_path: Path) -> None:

    query = AuthenticateLocalUserQuery(_store(tmp_path))

    assert asyncio.run(query.execute("analista", "errada")) is None
    assert asyncio.run(query.execute("ninguem", _DEMO_PASSWORD)) is None


def test_credenciais_demo_documentadas_funcionam() -> None:

    query = AuthenticateLocalUserQuery(YamlLocalUserStoreAdapter(_USERS_FILE))

    analista = asyncio.run(query.execute("analista", _DEMO_PASSWORD))
    admin = asyncio.run(query.execute("admin", _DEMO_PASSWORD))

    assert analista is not None
    assert [role.id for role in analista.roles] == ["analista"]

    assert admin is not None
    assert [role.id for role in admin.roles] == ["admin"]


def test_capabilities_do_analista_negam_e_do_admin_liberam() -> None:

    adapter = AuthCapacityAcl(AuthorizeQuery(YamlCapabilitiesAdapter()))

    analista = adapter.capabilities_for(
        User(id="a", name="A", email="a", roles=[Role(id="analista", name="analista")])
    )
    admin = adapter.capabilities_for(
        User(id="b", name="B", email="b", roles=[Role(id="admin", name="admin")])
    )
    anonimo = adapter.capabilities_for(User(id="c", name="C", email="", roles=[]))

    assert analista.can_use_financial_analysis
    assert not analista.allows_metric("profitability")
    assert analista.allows_metric("outstanding_balance")
    assert not analista.allows_axis("customer_segmentation", "segment")
    assert analista.allows_axis("product", "product")

    assert admin.allows_metric("profitability")
    assert anonimo.allows_metric("profitability")


class _LocalAuthStub:
    def __init__(self, user: User | None):

        self._user = user

    async def execute(self, username: str, password: str) -> User | None:

        return self._user


def _adapter(local_authenticate) -> ChainlitAdapter:  # type: ignore[no-untyped-def]

    adapter = ChainlitAdapter.__new__(ChainlitAdapter)
    adapter._local_authenticate = local_authenticate

    return adapter


def test_password_callback_devolve_chainlit_user_com_papeis() -> None:

    user = User(
        id="analista",
        name="Analista Demo",
        email="analista@cantabria.local",
        roles=[Role(id="analista", name="analista")],
    )

    result = asyncio.run(
        _adapter(_LocalAuthStub(user))._on_password_callback("analista", _DEMO_PASSWORD)
    )

    assert isinstance(result, cl.User)
    assert result.identifier == "analista@cantabria.local"
    assert result.metadata["roles"] == ["analista"]
    assert result.metadata["provider"] == "local"


def test_password_callback_recusa_credencial_invalida() -> None:

    result = asyncio.run(
        _adapter(_LocalAuthStub(None))._on_password_callback("analista", "errada")
    )

    assert result is None


def test_password_hook_so_registrado_com_login_local(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:

    registered: list[str] = []

    monkeypatch.setattr(cl, "on_message", lambda func: registered.append("message"))
    monkeypatch.setattr(
        cl, "password_auth_callback", lambda func: registered.append("password")
    )
    monkeypatch.setattr(cl, "oauth_callback", lambda func: registered.append("oauth"))

    _adapter(_LocalAuthStub(None))._register_callbacks()
    assert "password" in registered

    registered.clear()

    _adapter(None)._register_callbacks()
    assert "password" not in registered
