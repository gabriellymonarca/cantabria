"""Vínculo de negócio: qual fórmula genérica mede qual métrica.

A FÓRMULA é genérica e vive no kernel puro (`shared.aggregation`). O VÍNCULO é
negócio e vive aqui: quais medidas, unidade e como o número rola no tempo
(`ratio` | `stock` | `count`). A tabela física é escolhida pelo adapter a
partir dos `subjects` do plano (mapa `subject.type` → tabela).
"""

from __future__ import annotations

from dataclasses import dataclass

from contexts.financial_calculation.domain.calculation_plan import RuleId


@dataclass(frozen=True)
class Aggregation:
    """Expressão genérica declarada sobre medidas semânticas.

    kind = ratio | sum | distinct | compounded_rate. As medidas (`vl_margem`,
    `vl_saldo`) e as chaves distintas (`id_contrato`, `id_cliente`) são nomes
    semânticos; o adapter resolve a coluna física. Em `compounded_rate` o
    componente é a lista de taxas mensais em decimal do bucket (`rates`): o
    kernel compõe os fatores, nunca média/soma.
    """

    kind: str
    numerator: str | None = None
    denominator: str | None = None
    measure: str | None = None
    distinct_key: str | None = None


@dataclass(frozen=True)
class MetricBinding:
    """Como uma family é medida: unidade, fórmula e rollup temporal.

    temporal_behavior:
      ratio -> re-derivar Σnum/Σden no grão (nunca média de taxas)
      stock -> leitura do fim do período (nunca somar entre meses)
      count -> foto numa data (nunca somar entre meses)
      compounded -> capitalizar as taxas mensais do bucket (Π(1+r_i) − 1) e
                    anualizar a taxa efetiva da janela
    """

    rule_id: RuleId
    unit: str
    aggregation: Aggregation
    temporal_behavior: str


METRIC_BINDINGS: dict[RuleId, MetricBinding] = {
    RuleId.PROFITABILITY: MetricBinding(
        rule_id=RuleId.PROFITABILITY,
        unit="decimal_rate",
        aggregation=Aggregation(
            kind="ratio",
            numerator="vl_margem",
            denominator="vl_saldo",
        ),
        temporal_behavior="ratio",
    ),
    RuleId.OUTSTANDING_BALANCE: MetricBinding(
        rule_id=RuleId.OUTSTANDING_BALANCE,
        unit="currency",
        aggregation=Aggregation(kind="sum", measure="vl_saldo"),
        temporal_behavior="stock",
    ),
    RuleId.CONTRACT_COUNT: MetricBinding(
        rule_id=RuleId.CONTRACT_COUNT,
        unit="count",
        aggregation=Aggregation(kind="distinct", distinct_key="id_contrato"),
        temporal_behavior="count",
    ),
    RuleId.CUSTOMER_COUNT: MetricBinding(
        rule_id=RuleId.CUSTOMER_COUNT,
        unit="count",
        aggregation=Aggregation(kind="distinct", distinct_key="id_cliente"),
        temporal_behavior="count",
    ),
    RuleId.CDI_RATE: MetricBinding(
        rule_id=RuleId.CDI_RATE,
        unit="decimal_rate",
        aggregation=Aggregation(kind="compounded_rate", measure="taxa_mensal"),
        temporal_behavior="compounded",
    ),
    RuleId.SELIC_RATE: MetricBinding(
        rule_id=RuleId.SELIC_RATE,
        unit="decimal_rate",
        aggregation=Aggregation(kind="compounded_rate", measure="taxa_mensal"),
        temporal_behavior="compounded",
    ),
    RuleId.INFLATION_IPCA: MetricBinding(
        rule_id=RuleId.INFLATION_IPCA,
        unit="decimal_rate",
        aggregation=Aggregation(kind="compounded_rate", measure="taxa_mensal"),
        temporal_behavior="compounded",
    ),
}
