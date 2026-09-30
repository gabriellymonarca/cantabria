"""Erros de domínio do motor determinístico.

A taxonomia separa "função inexistente" de "parâmetro inválido", para que a
recusa diga o motivo.
"""

from __future__ import annotations


class CalculationError(ValueError):
    """Base dos erros do motor de cálculo."""


class UnknownRuleError(CalculationError):
    """rule_id fora do catálogo de métricas."""


class UnknownAxisError(CalculationError):
    """(type, level) de eixo ou recorte fora do catálogo governado."""


class UnknownValueError(CalculationError):
    """value_id de recorte fora do conjunto governado para aquele eixo."""


class UnknownMeasureError(CalculationError):
    """Medida semântica sem coluna física mapeada no adapter."""


class UnknownSourceError(CalculationError):
    """Fonte declarada pela métrica sem caminho físico no armazém oficial."""


class UnsupportedGrainError(CalculationError):
    """grain fora de month|quarter|year."""


class InvalidPeriodError(CalculationError):
    """start/end/type inconsistentes (ex.: snapshot com start != end)."""


class InvalidPlanError(CalculationError):
    """Plano malformado: sem quebra, quebra repetida ou `total` cruzado."""
