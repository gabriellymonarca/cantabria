from abc import ABC, abstractmethod

from contexts.auth.ports.inbound.authorize_port import User, UserCapabilities


# Outbound (driven) port: Financial Analysis conforms to Auth via OHS. The
# domain never decides permission; it receives the capabilities the auth
# context resolved for the authenticated user.
class AuthCapacityPort(ABC):
    """Resolves the capabilities the authenticated user has for analysis."""

    @abstractmethod
    def capabilities_for(self, user: User) -> UserCapabilities:
        """Returns the metric/axis capabilities of `user`."""
        ...
