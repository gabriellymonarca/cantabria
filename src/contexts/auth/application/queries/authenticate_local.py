import hashlib
import hmac

from contexts.auth.domain.user import User
from contexts.auth.ports.inbound.authenticate_local_user_port import (
    AuthenticateLocalUserPort,
)
from contexts.auth.ports.outbound.local_user_store_port import LocalUserStorePort


def hash_password(password: str) -> str:

    return hashlib.sha256(password.encode("utf-8")).hexdigest()


class AuthenticateLocalUserQuery(AuthenticateLocalUserPort):
    """Autentica credenciais locais e devolve o ator com seus papéis."""

    def __init__(self, store: LocalUserStorePort):

        self._store = store

    async def execute(self, username: str, password: str) -> User | None:

        stored = self._store.find_by_username(username)

        if stored is None:
            return None

        candidate = hash_password(password)

        if not hmac.compare_digest(candidate, stored.password_sha256):
            return None

        return User(
            id=stored.username,
            name=stored.name,
            email=stored.email,
            roles=list(stored.roles),
        )
