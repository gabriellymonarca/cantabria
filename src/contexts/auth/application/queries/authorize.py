# Determine which analytical resources and data sources the user can access.

from contexts.auth.domain.capabilities import UserCapabilities
from contexts.auth.domain.user import User
from contexts.auth.ports.inbound.authorize_port import AuthorizePort
from contexts.auth.ports.outbound.capabilities_source_port import (
    CapabilitiesSourcePort,
)


class AuthorizeQuery(AuthorizePort):
    """Lê as capacidades do usuário na fonte configurada; sem efeito colateral."""

    def __init__(self, source: CapabilitiesSourcePort):

        self._source = source

    def capabilities_for(self, user: User) -> UserCapabilities:

        return self._source.capabilities_for_roles([role.id for role in user.roles])
