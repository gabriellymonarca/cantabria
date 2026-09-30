from abc import ABC, abstractmethod
from datetime import date


# Outbound (driven) port: the application depends on this interface to obtain
# the interpretation system prompt; a file-backed adapter implements it.
class InterpretationPromptPort(ABC):
    """Builds the system prompt that governs the interpretation step."""

    @abstractmethod
    def build_system_prompt(
        self, locale: str, reference_date: date | None = None
    ) -> str:
        """Monta o prompt para o locale; `reference_date` é o as-of do dado."""
        ...
