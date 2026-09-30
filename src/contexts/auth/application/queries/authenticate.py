from contexts.auth.domain.user import Role, User
from contexts.auth.ports.inbound.authenticate_user_port import (
    AuthenticateUserPort,
    ExternalIdentity,
)


# Authentication policy: accept only verified identities; when allowed domains
# are configured, the identity must belong to one of them. Provisioning is
# minimal until a user store exists: the provider subject becomes the id.
# Roles come from the configured map (SSO email -> roles), falling back to the
# default roles; without configuration the actor stays roleless, as before.
class AuthenticateUserQuery(AuthenticateUserPort):
    """Authenticates an external identity and returns the actor context."""

    def __init__(
        self,
        allowed_domains: list[str] | None = None,
        role_map: dict[str, list[str]] | None = None,
        default_roles: list[str] | None = None,
    ):

        self._allowed_domains = allowed_domains or []
        self._role_map = role_map or {}
        self._default_roles = default_roles or []

    async def execute(self, identity: ExternalIdentity) -> User | None:

        if not identity.email_verified:
            return None

        if (
            self._allowed_domains
            and identity.hosted_domain not in self._allowed_domains
        ):
            return None

        role_ids = self._role_map.get(identity.email, self._default_roles)

        return User(
            id=identity.subject,
            name=identity.name or identity.email,
            email=identity.email,
            roles=[Role(id=role, name=role) for role in role_ids],
        )
