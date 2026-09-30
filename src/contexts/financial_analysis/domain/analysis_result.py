"""O resultado verificado da análise.

O `AnalysisResult` espelha a forma do `AnalysisPlan`: cada método com o seu
número e cada operação com a sua saída. Carrega o que a execução determinística
produziu, com a procedência (versão do catálogo, versão do dado e trace) que
torna o número auditável.

Valor ausente é `None` com motivo (`undefined`): população vazia, célula
suprimida por small-cell ou quantidade não calculável. Nunca 0 fingindo medição.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

Number = Decimal | int

SMALL_CELL_K = 10


class UndefinedReason(StrEnum):
    """Por que uma linha não tem valor."""

    NO_OBSERVATIONS = "no_observations"
    SMALL_CELL = "small_cell"
    NOT_COMPUTABLE = "not_computable"


@dataclass(frozen=True)
class MethodValue:
    """Uma linha de método: identidade `subjects` + medidas nomeadas.

    As chaves de `values` dependem do método: `value` (`null`, `share`, `mean`,
    `median`, `mode`, `std`), `absolute`/`percent` (`variation`) ou o pacote de
    `dispersion` (`mean`, `median`, `std`, `variance`, `min`, `max`, `q1`, `q3`,
    `iqr`). Linha sem número traz `undefined`.
    """

    subjects: dict[str, str | None]
    values: dict[str, Number | None] = field(default_factory=dict)
    undefined: UndefinedReason | None = None
    period: str | None = None


@dataclass(frozen=True)
class MethodResult:
    """A saída de um método declarado no plano.

    `unit`/`rule_id` herdados do cálculo de origem dizem como ler cada
    número: taxa decimal, moeda ou contagem. `share` produz taxa mesmo
    quando a origem é estoque ou contagem; `correlation` é adimensional.
    """

    id: str
    method: str
    values: list[MethodValue] = field(default_factory=list)
    unit: str | None = None
    rule_id: str | None = None


@dataclass(frozen=True)
class OperationValue:
    """Uma linha de operação: identidade `subjects` + medidas e posição."""

    subjects: dict[str, str | None]
    values: dict[str, Number | None] = field(default_factory=dict)
    rank: int | None = None
    undefined: UndefinedReason | None = None
    period: str | None = None


@dataclass(frozen=True)
class OperationResult:
    """A saída de uma operação declarada no plano.

    `unit`/`rule_id` herdados do método de origem, com a mesma leitura do
    `MethodResult`. `decomposition` herda da variação, não da participação.
    """

    id: str
    type: str
    refs: list[str]
    values: list[OperationValue] = field(default_factory=list)
    unit: str | None = None
    rule_id: str | None = None


@dataclass(frozen=True)
class AnalysisResult:
    """Números verificados prontos para explicar, com procedência.

    `unit`/`rule_id` resumem o pacote quando todos os métodos concordam;
    são `None` quando o pacote mistura unidades. A leitura fiel por linha
    mora em cada `MethodResult`/`OperationResult`. `prompt_version` registra
    os contratos de prompt vigentes no turno (ex.: `interpretation=v1,
    insight=v3,documental=v1`); vazio quando o executor não os conhece.
    """

    analysis_plan_id: str
    catalog_version: str
    dataset_version: str
    trace_id: str
    statistical_method: list[MethodResult] = field(default_factory=list)
    operations: list[OperationResult] = field(default_factory=list)
    unit: str | None = None
    rule_id: str | None = None
    prompt_version: str = ""
