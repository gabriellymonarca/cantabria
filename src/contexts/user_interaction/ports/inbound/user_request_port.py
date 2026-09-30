from abc import ABC, abstractmethod

from contexts.auth.ports.inbound.authorize_port import User
from contexts.financial_analysis.ports.inbound.user_request import Content


# Inbound (driving) port of this context: what the UI adapter sees of
# user_interaction. The adapter passes only who asked, in which session, the
# turn's trace and the text; history and context are this context's business.
class UserRequestPort(ABC):
    """Processes a user request and returns the content to present."""

    @abstractmethod
    async def execute(
        self,
        *,
        user: User,
        session_id: str,
        trace_id: str,
        request: str,
        locale: str = "pt-BR",
    ) -> list[Content]: ...
