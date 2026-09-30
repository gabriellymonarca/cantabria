from abc import ABC, abstractmethod
from datetime import date


# Outbound (driven) port: a data de referência (as-of) é um fato do DADO
# OFICIAL, não do calendário nem do prompt. O adapter lê o último mês com dado
# e o injeta no prompt; o núcleo nunca conhece SQL.
class ReferenceDatePort(ABC):
    """Informa o último período com dado oficial disponível."""

    @abstractmethod
    def latest_reference_date(self) -> date | None:
        """O último mês com dado, ou None se o dado não estiver acessível."""
        ...
