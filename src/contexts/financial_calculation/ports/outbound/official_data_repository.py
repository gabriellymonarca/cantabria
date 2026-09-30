"""Port: OfficialDataRepository (outbound / driven).

Fronteira hexagonal entre o motor determinístico (financial_calculation) e o
armazém de dados oficiais (ClickHouse). O core NUNCA conhece SQL, driver,
tabela ou coluna física: declara a FORMA SEMÂNTICA da leitura e o Adapter
traduz (type, level), value_id e medida para o dialeto físico.

O banco AGREGA. O Port devolve, já no grão pedido, os COMPONENTES da agregação;
o core só combina os componentes com a fórmula genérica (`shared.aggregation`)
e aplica a política de ausência. Nenhuma linha de fato crua atravessa o Port.

A tabela física é escolhida pelo Adapter a partir dos `subjects` e do recorte:
eixo de produto lê o grão contrato × produto; eixo de cliente lê o grão
cliente × mês; contagens leem os contratos ativos na data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from contexts.financial_calculation.domain.metric_binding import Aggregation


@dataclass(frozen=True)
class SubjectRequest:
    """Um subject do plano, em termos SEMÂNTICOS."""

    type: str
    level: str


@dataclass(frozen=True)
class SampleConditionRequest:
    """Uma condição do campo amostral, em termos SEMÂNTICOS.

    `value_id` é o id governado; a tradução para valor físico (ex.: "Varejo
    PF") ou para a faixa do score é do Adapter.
    """

    type: str
    level: str
    value_id: str


@dataclass(frozen=True)
class PeriodRequest:
    """Recorte temporal, já com a forma do resultado.

    type:  series   -> um valor por bucket no intervalo
           snapshot -> um valor na data `end` (start == end)
    grain: month | quarter | year | total (total = a janela inteira num bucket)
    """

    start: str
    end: str
    type: str
    grain: str


@dataclass(frozen=True)
class MetricRequest:
    """O que calcular, em termos semânticos, para UMA métrica."""

    rule_id: str
    unit: str
    aggregation: Aggregation
    temporal_behavior: str
    subjects: tuple[SubjectRequest, ...] = ()
    sample: tuple[SampleConditionRequest, ...] = ()


@dataclass(frozen=True)
class AggregatedRow:
    """Componentes da agregação de UMA métrica, num grupo e período.

    `components` carrega as parcelas que a fórmula do core combina:
      ratio          -> {"numerator": Σnum, "denominator": Σden}
      sum            -> {"value": leitura do fim do período}
      distinct       -> {"value": contagem distinta}
      compounded_rate -> {"rates": (taxa_1, ..., taxa_n)} taxas MENSais em
                        decimal; a composição e a anualização são do kernel
    Valor None (ausente) propaga a política de ausência: nunca 0.0 por vazio.

    Toda família devolve ainda a chave opcional `"population"`: o número de
    clientes DISTINTOS que compõem o grupo naquele período (contagem exata,
    nunca a lista de identificadores). Ela alimenta a supressão small-cell
    (k = 10) no contexto de análise; ausente ou None significa "desconhecida",
    e o core não suprime.
    """

    subjects: dict[str, str | None]
    period: str
    components: dict[str, Decimal | int | None | tuple[Decimal | int | None, ...]] = (
        field(default_factory=dict)
    )


class OfficialDataRepository(Protocol):
    """Port de leitura agregada dos dados oficiais."""

    def fetch_aggregated(
        self,
        metric: MetricRequest,
        period: PeriodRequest,
    ) -> list[AggregatedRow]:
        """Executa a métrica pedida e devolve linhas já no grão pedido.

        Implementações devem empurrar filtros, joins, alinhamento temporal e
        agregação para o armazém.
        """
        ...
