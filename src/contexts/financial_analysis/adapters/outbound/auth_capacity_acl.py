"""Adapter outbound (ACL): implementa o `AuthCapacityPort` sobre o port inbound
publicado pelo Auth (`AuthorizePort`).

O núcleo da análise vê só o seu próprio port; o Auth publica só o seu port
inbound. A linguagem é a mesma (`UserCapabilities`), então a tradução é uma
delegação; qualquer conversão entre as duas mora aqui.
"""

from __future__ import annotations

from contexts.auth.ports.inbound.authorize_port import (
    AuthorizePort,
    User,
    UserCapabilities,
)
from contexts.financial_analysis.ports.outbound.auth_capacity_port import (
    AuthCapacityPort,
)


class AuthCapacityAcl(AuthCapacityPort):
    """Resolve as capacidades do usuário perguntando ao Auth."""

    def __init__(self, authorize: AuthorizePort):

        self._authorize = authorize

    def capabilities_for(self, user: User) -> UserCapabilities:

        return self._authorize.capabilities_for(user)
