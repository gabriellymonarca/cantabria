"""Kernel numérico puro, compartilhado entre contextos.

Operadores agnósticos de domínio, sem I/O e sem framework. São a definição de
referência da semântica determinística: o adapter ClickHouse empurra a
agregação para o banco e devolve os COMPONENTES (somas, contagens), e é AQUI
que a fórmula genérica os combina — inclusive a política de ausência.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal


def ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """Divisão protegida: denominador zero é AUSÊNCIA, nunca 0.0.

    Devolver 0.0 seria afirmar "rendeu 0%", que é um número plausível e falso.
    """

    if denominator == 0:
        return None
    return numerator / denominator


def sum_values(values: Iterable[Decimal]) -> Decimal:
    """Soma exata em Decimal. Dinheiro nunca passa por float."""

    total = Decimal(0)
    for value in values:
        total += value
    return total


def count_distinct(keys: Iterable[str]) -> int:
    """Contagem distinta exata (o adapter usa uniqExact; aqui é a referência)."""

    return len(set(keys))


def latest(values_by_period: Mapping[str, Decimal]) -> Decimal | None:
    """Valor do período mais recente — rollup de ESTOQUE no tempo.

    Estoque não soma entre meses: R$ 200 parados por três meses continuam
    R$ 200. A leitura correta no grão é a do período mais recente.
    """

    if not values_by_period:
        return None
    return values_by_period[max(values_by_period)]


def compound_rate(rates: Iterable[Decimal]) -> Decimal | None:
    """Fator composto da janela: Π(1 + r_i) − 1, nunca média nem soma.

    As taxas são MENSAIS em decimal (0.0084 = 0.84% no mês). Compor é o único
    rollup correto de uma taxa periódica: 10% por dois meses é 21%, não 20%
    (soma) nem 10% (média). Lista vazia é AUSÊNCIA (`None`), nunca 0.0.

    Os fatores são multiplicados em ordem canônica (crescente): a
    multiplicação Decimal arredonda a cada operação, e a ordem da fonte não
    pode mudar o último dígito do resultado.
    """

    factors = tuple(sorted(Decimal(1) + Decimal(rate) for rate in rates))

    if not factors:
        return None

    product = Decimal(1)

    for factor in factors:
        product *= factor

    return product - 1


def annualize_rate(effective_rate: Decimal | None, months: int) -> Decimal | None:
    """Taxa anual equivalente de uma taxa efetiva de `months` meses.

    `(1 + R) ** (12 / months) − 1` — a MESMA base anual de `profitability`
    (cuja margem já é anualizada). Doze meses é o ponto fixo; um mês vira
    `(1 + r) ** 12 − 1`. Base não-positiva (`R <= -1`) ou janela vazia é
    AUSÊNCIA com motivo, nunca um número inventado.
    """

    if effective_rate is None or months <= 0:
        return None

    base = Decimal(1) + Decimal(effective_rate)

    if base <= 0:
        return None

    return base ** (Decimal(12) / Decimal(months)) - 1


def compound_annualized_rate(rates: Iterable[Decimal]) -> Decimal | None:
    """Taxa anual equivalente de uma janela: compõe os meses e anualiza.

    É o valor que a métrica macro devolve em qualquer grão: cada bucket vira a
    taxa anual equivalente dos meses que o compõem.
    """

    monthly = tuple(Decimal(rate) for rate in rates)
    effective = compound_rate(monthly)

    if effective is None:
        return None

    return annualize_rate(effective, len(monthly))
