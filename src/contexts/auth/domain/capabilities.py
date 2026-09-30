"""O que o usuário pode ver, decidido pelo Auth.

A autorização é decidida FORA do modelo generativo: o planner propõe, e a
validação determinística da análise nega com `unauthorized` quando a métrica
ou o eixo não pertencem às capacidades do usuário. A granularidade é ampla
(pode usar análise financeira) + fina (métricas e eixos permitidos por role).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class UserCapabilities:
    """Capacidades de um usuário para a análise financeira."""

    can_use_financial_analysis: bool
    metrics: frozenset[str] = field(default_factory=frozenset)
    axes: frozenset[str] = field(default_factory=frozenset)

    def allows_metric(self, rule_id: str) -> bool:

        return rule_id in self.metrics

    def allows_axis(self, axis_type: str, level: str) -> bool:

        return f"{axis_type}.{level}" in self.axes
