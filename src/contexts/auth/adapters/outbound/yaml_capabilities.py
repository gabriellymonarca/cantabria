"""Adapter outbound que lê as capacidades de autorização do arquivo do Auth.

O núcleo só conhece `CapabilitiesSourcePort`; o I/O e o formato ficam aqui. O
role do usuário seleciona a entrada; sem entrada, vale `default`. Listas
explícitas — acrescentar algo ao catálogo não concede acesso sozinho.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from contexts.auth.domain.capabilities import UserCapabilities
from contexts.auth.ports.outbound.capabilities_source_port import (
    CapabilitiesSourcePort,
)
from cross_cutting.resources import resolve_data_dir

_CAPABILITIES_SUBDIR = Path("auth")
_CAPABILITIES_FILE = "capabilities.yaml"


class CapabilityConfigurationError(RuntimeError):
    """O arquivo de capacidades está ausente ou inválido."""


class YamlCapabilitiesAdapter(CapabilitiesSourcePort):
    """Resolve as capacidades por role a partir do arquivo do Auth."""

    def __init__(self, config_path: Path | None = None):

        data_dir = resolve_data_dir()
        self._path = config_path or (
            data_dir / _CAPABILITIES_SUBDIR / _CAPABILITIES_FILE
        )
        self._cache: dict[str, Any] | None = None

    def capabilities_for_roles(self, role_ids: list[str]) -> UserCapabilities:

        data = self._load()

        entry = next(
            (data[role_id] for role_id in role_ids if role_id in data),
            data.get("default"),
        )

        if entry is None:
            return UserCapabilities(can_use_financial_analysis=False)

        return UserCapabilities(
            can_use_financial_analysis=bool(
                entry.get("can_use_financial_analysis", False)
            ),
            metrics=frozenset(entry.get("metrics") or []),
            axes=frozenset(entry.get("axes") or []),
        )

    def _load(self) -> dict[str, Any]:

        if self._cache is not None:
            return self._cache

        if not self._path.is_file():
            raise CapabilityConfigurationError(
                f"arquivo de capacidades não encontrado: {self._path}."
            )

        data = yaml.safe_load(self._path.read_text(encoding="utf-8"))

        if not isinstance(data, dict):
            raise CapabilityConfigurationError(
                "o arquivo de capacidades precisa ser um mapa role -> capacidades."
            )

        self._cache = data

        return data
