"""Protocolo legível de um turno.

O `trace_id` completo (32 hex) é o que o log e o trace guardam; ao usuário vai
uma forma curta e pronunciável — `CAN-` mais os oito primeiros caracteres em
maiúsculas — que o suporte consegue procurar sem ambiguidade prática. A UI
(mensagem de falha) e a análise (rodapé de procedência) produzem a referência
por esta função.
"""

from __future__ import annotations

_PROTOCOL_PREFIX = "CAN-"
_PROTOCOL_CHARS = 8


def protocol_of(trace_id: str) -> str:
    """`fc4dea24af97…` → `CAN-FC4DEA24`; vazio quando não há trace."""

    if not trace_id:
        return ""

    return f"{_PROTOCOL_PREFIX}{trace_id[:_PROTOCOL_CHARS].upper()}"
