# Adapter: ClickHouseOfficialDataRepository (outbound / driven)
#
# Implementa o Port `OfficialDataRepository` com o client HTTP `clickhouse-connect`.
# É o único lugar do projeto que conhece SQL, tabela e coluna física: o core fala
# (type, level), value_id e medida semântica; aqui isso vira `ds_segm`, faixa de
# score e nome de tabela. O banco agrega e o adapter devolve, por grupo/período,
# só os componentes (somas, contagem distinta, leitura de estoque).
#
# A tabela física é derivada dos `subjects`/`sample`:
#   eixo de produto  -> grão contrato x produto (fato_rentabilidade_contrato_produto)
#   eixo de cliente  -> grão cliente x mês (fato_rentabilidade_cliente)
#   contagens        -> fato_contratos ativos, com joins governados
#
# Segurança: conecta com o usuário de aplicação (`cantabria_app`, read-only);
# tabelas/colunas vêm dos mapas governados abaixo; valores de recorte e datas
# entram como parâmetros tipados do client.

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from contexts.financial_calculation.domain.errors import (
    UnknownAxisError,
    UnknownMeasureError,
    UnknownSourceError,
    UnknownValueError,
)
from contexts.financial_calculation.ports.outbound.official_data_repository import (
    AggregatedRow,
    MetricRequest,
    PeriodRequest,
)

# Faixa governada derivada do score cru: alta >= 70, media 40-69, baixa < 40
# (escala 0-100).
SCORE_ALTA_MIN = 70
SCORE_MEDIA_MIN = 40

_CLIENT_TYPES = frozenset(
    {
        "customer_segmentation",
        "customer_relationship",
        "customer_principality",
    }
)

_RENTABILIDADE_CLIENTE = "rentabilidade_cliente"
_RENTABILIDADE_ITEM = "rentabilidade_contrato_produto"
_CONTRATO = "contrato"
_MERCADO = "mercado"

# rule_id de série macro -> valor físico do indicador na tabela de mercado.
# É o ÚNICO lugar que conhece essa tradução; o plano fala rule_id.
_MARKET_RULE_INDICATORS: dict[str, str] = {
    "cdi_rate": "cdi",
    "selic_rate": "selic",
    "inflation_ipca": "ipca",
}


def _depth_case(column: str) -> str:

    return (
        f"multiIf({{s}}.{column} >= {SCORE_ALTA_MIN}, 'alta', "
        f"{{s}}.{column} >= {SCORE_MEDIA_MIN}, 'media', 'baixa')"
    )


# (type, level) -> expressão SQL do eixo; `{s}` é o alias da fonte.
DIMENSION_EXPRESSIONS: dict[tuple[str, str], str] = {
    ("customer_segmentation", "person_type"): "{s}.tp_pess",
    ("customer_segmentation", "segment_group"): "{s}.ds_segm_agrup",
    ("customer_segmentation", "segment"): "{s}.ds_segm",
    ("customer_segmentation", "subsegment_group"): "{s}.ds_subsegm_agrup",
    ("customer_segmentation", "subsegment"): "{s}.ds_subsegm",
    ("customer_principality", "principality_depth"): _depth_case(
        "principalidade_score"
    ),
    ("customer_relationship", "relationship_depth"): _depth_case("vinculacao_score"),
    ("product", "product_group"): "{s}.ds_grupo_prod",
    ("product", "product"): "{s}.ds_produto",
    ("product", "subproduct"): "{s}.ds_subproduto",
}

_DIMENSION_SOURCE: dict[str, str] = {
    "customer_segmentation": "dc",
    "customer_relationship": "dc",
    "customer_principality": "dc",
    "product": "dp",
}

# Profundidades derivadas do score cru: coluna física por eixo.
SCORE_COLUMNS: dict[tuple[str, str], str] = {
    ("customer_principality", "principality_depth"): "principalidade_score",
    ("customer_relationship", "relationship_depth"): "vinculacao_score",
}

_SCORE_RANGES: dict[str, str] = {
    "low": "{c} < {media_min}",
    "medium": "{c} >= {media_min} AND {c} < {alta_min}",
    "high": "{c} >= {alta_min}",
}

# value_id do catálogo -> valor físico gravado.
VALUE_TRANSLATION: dict[tuple[str, str], dict[str, str]] = {
    ("customer_segmentation", "segment"): {
        "varejo_pf": "Varejo PF",
        "varejo_pj": "Varejo PJ",
        "varejo_rural": "Varejo Rural",
        "private": "Private",
        "corporate_middle": "Corporate Middle",
        "corporate_large": "Corporate Large",
        "cib": "CIB",
    },
    ("product", "product_group"): {
        "rotativo": "Crédito Rotativo",
        "parcelado": "Crédito Parcelado",
        "consignado": "Crédito Consignado",
        "com_garantia": "Crédito com Garantia",
        "especializado": "Crédito Especializado",
        "transacional": "Crédito Transacional",
        "renegociacao": "Renegociação de Dívidas",
    },
    ("product", "product"): {
        "cartao": "Cartão",
    },
}

# Medida semântica -> coluna física.
MEASURE_COLUMNS: dict[str, str] = {
    "vl_margem": "vl_margem",
    "vl_saldo": "vl_saldo",
    "id_contrato": "id_contrato",
    "id_cliente": "id_cliente",
}

# Chave física do cliente: só entra em contagem distinta (`population`), nunca
# como coluna projetada — identificador é chave de junção, não resultado.
_CUSTOMER_KEY = "id_cliente"
_POPULATION = "population"


# ---------------------------------------------------------------------------
# Estruturas de compilação
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Axis:
    alias: str
    select: str
    key: str  # "type.level", chave semântica no resultado


@dataclass(frozen=True)
class CompiledQuery:
    """Uma consulta agregada pronta para executar, com o mapa de leitura."""

    sql: str
    params: dict
    axes: tuple[_Axis, ...]
    component_names: tuple[str, ...]


def _measure(name: str | None) -> str:

    if name is not None and name in MEASURE_COLUMNS:
        return MEASURE_COLUMNS[name]

    raise UnknownMeasureError(f"medida '{name}' sem coluna física.")


def _dimension_expression(axis_type: str, level: str) -> str:

    template = DIMENSION_EXPRESSIONS.get((axis_type, level))

    if template is None:
        raise UnknownAxisError(f"eixo '{axis_type}.{level}' fora do catálogo.")

    return template.format(s=_DIMENSION_SOURCE[axis_type])


def _axes(metric: MetricRequest) -> list[_Axis]:

    axes: list[_Axis] = []

    for subject in metric.subjects:
        if subject.type == "total":
            continue

        alias = f"d{len(axes)}"
        expression = _dimension_expression(subject.type, subject.level)

        axes.append(
            _Axis(
                alias=alias,
                select=f"{expression} AS {alias}",
                key=f"{subject.type}.{subject.level}",
            )
        )

    return axes


def _score_clause(column: str, value_id: str) -> str:

    template = _SCORE_RANGES.get(value_id)

    if template is None:
        raise UnknownValueError(f"valor '{value_id}' fora da faixa de '{column}'.")

    expression = template.format(
        c=column,
        media_min=SCORE_MEDIA_MIN,
        alta_min=SCORE_ALTA_MIN,
    )

    return f" AND ({expression})"


def _sample_clauses(metric: MetricRequest) -> tuple[str, dict]:

    clauses: list[str] = []
    params: dict[str, str] = {}

    for index, condition in enumerate(metric.sample):
        score_column = SCORE_COLUMNS.get((condition.type, condition.level))

        if score_column is not None:
            clauses.append(_score_clause(f"dc.{score_column}", condition.value_id))
            continue

        column = _dimension_expression(condition.type, condition.level)
        param = f"filter_{index}"

        clauses.append(f" AND {column} = {{{param}:String}}")
        params[param] = VALUE_TRANSLATION.get(
            (condition.type, condition.level), {}
        ).get(condition.value_id, condition.value_id)

    return "".join(clauses), params


def _dims_select(axes: list[_Axis]) -> str:

    return ", ".join(axis.select for axis in axes)


def _dims_group(axes: list[_Axis]) -> str:

    return "".join(f", {axis.alias}" for axis in axes)


def _dims_projection(axes: list[_Axis], table: str) -> str:

    if not axes:
        return ""

    return ", ".join(f"{table}.{axis.alias}" for axis in axes) + ", "


def _dims_join_condition(axes: list[_Axis]) -> str:

    return "".join(f" AND a.{axis.alias} = g.{axis.alias}" for axis in axes)


def _order_dims(axes: list[_Axis]) -> str:

    if not axes:
        return ""

    return ", " + ", ".join(f"g.{axis.alias}" for axis in axes)


def _has_product_axis(metric: MetricRequest) -> bool:

    return any(item.type == "product" for item in (*metric.subjects, *metric.sample))


def _needs_client(metric: MetricRequest) -> bool:

    return any(item.type in _CLIENT_TYPES for item in metric.subjects) or any(
        condition.type in _CLIENT_TYPES for condition in metric.sample
    )


def _source(metric: MetricRequest) -> str:

    if str(metric.rule_id) in _MARKET_RULE_INDICATORS:
        return _MERCADO

    if metric.aggregation.kind == "distinct":
        return _CONTRATO

    if _has_product_axis(metric):
        return _RENTABILIDADE_ITEM

    return _RENTABILIDADE_CLIENTE


def _value_parts(metric: MetricRequest) -> tuple[list[str], tuple[str, ...]]:

    if metric.aggregation.kind == "ratio":
        return (
            [
                "a.total_margem AS v0_numerator",
                "a.total_saldo AS v0_denominator",
                f"a.{_POPULATION} AS v0_{_POPULATION}",
            ],
            ("numerator", "denominator", _POPULATION),
        )

    # Estoque: o valor exibido é a leitura do último mês do bucket, logo a
    # população que julga o k = 10 tem de ser a desse mesmo mês (não a união
    # dos clientes de todos os meses, que não estão no número mostrado).
    if metric.temporal_behavior == "stock":
        return (
            ["a.last_saldo AS v0_value", f"a.last_{_POPULATION} AS v0_{_POPULATION}"],
            ("value", _POPULATION),
        )

    raise UnknownSourceError(
        "rentabilidade não suporta a agregação "
        f"'{metric.aggregation.kind}' com rollup '{metric.temporal_behavior}'."
    )


def _population_state(source_alias: str) -> str:
    """Estado parcial da contagem distinta de clientes, por mês do bucket.

    O grão mensal precisa do estado (`-State`) porque clientes distintos não
    se somam entre meses; o bucket funde os estados com `-Merge`."""

    return (
        f"uniqExactState({source_alias}.{_CUSTOMER_KEY}) AS customers_state,"
        f" uniqExact({source_alias}.{_CUSTOMER_KEY}) AS month_customers"
    )


def _population_merge() -> str:

    return (
        f"uniqExactMerge(customers_state) AS {_POPULATION},"
        f" argMax(month_customers, month) AS last_{_POPULATION}"
    )


# ---------------------------------------------------------------------------
# Alinhamento temporal (bucket)
# ---------------------------------------------------------------------------


def _bucket_expr(column: str, grain: str) -> str:

    if grain == "month":
        return f"toStartOfMonth({column})"

    if grain == "quarter":
        return f"toStartOfQuarter({column})"

    if grain == "year":
        return f"toStartOfYear({column})"

    if grain == "total":
        return "{end:Date}"

    raise UnknownSourceError(f"grain '{grain}' sem expressão de bucket.")


def _join_bucket_expr(column: str, grain: str) -> str:
    """Bucket do lado do join: para `total` o valor vem da coluna, não da
    constante do rótulo — senão o LEFT JOIN fica sem chave (403 no ClickHouse)."""

    if grain == "total":
        return column

    return _bucket_expr(column, grain)


def _last_day(year: int, month: int) -> int:

    if month == 12:
        return 31

    return (dt.date(year, month + 1, 1) - dt.timedelta(days=1)).day


def _bucket_end(month_start: dt.date, grain: str) -> dt.date:

    if grain == "month":
        return dt.date(
            month_start.year,
            month_start.month,
            _last_day(month_start.year, month_start.month),
        )

    if grain == "quarter":
        month_end = ((month_start.month - 1) // 3 + 1) * 3
        return dt.date(
            month_start.year, month_end, _last_day(month_start.year, month_end)
        )

    if grain == "year":
        return dt.date(month_start.year, 12, 31)

    raise UnknownSourceError(f"grain '{grain}' sem fim de bucket.")


def _bucket_ends(period: PeriodRequest) -> list[str]:

    if period.grain == "total":
        return [period.end]

    if period.type == "snapshot":
        return [period.end]

    start = dt.date.fromisoformat(period.start)
    end = dt.date.fromisoformat(period.end)
    current = start.replace(day=1)
    buckets: list[str] = []

    while current <= end:
        bucket = _bucket_end(current, period.grain).isoformat()

        if bucket not in buckets:
            buckets.append(bucket)

        current = dt.date(
            current.year + (current.month // 12), current.month % 12 + 1, 1
        )

    return buckets


# ---------------------------------------------------------------------------
# Compilação por caminho físico
# ---------------------------------------------------------------------------


def _compile_rentabilidade_cliente(
    metric: MetricRequest,
    axes: list[_Axis],
    sample_sql: str,
    period: PeriodRequest,
    database: str,
) -> tuple[str, tuple[str, ...]]:

    dims_select = _dims_select(axes)
    dims_group = _dims_group(axes)
    dims_tail = f", {dims_select}" if dims_select else ""
    value_parts, component_names = _value_parts(metric)

    monthly_bucket = _bucket_expr("r.mes_ref", period.grain)
    join_bucket = _join_bucket_expr("b.ref", period.grain)

    groups_body = (
        f"SELECT DISTINCT {dims_select} FROM {database}.fato_cliente AS dc"
        if axes
        else "SELECT 1 AS _g"
    )

    sql = (
        "WITH buckets AS (SELECT arrayJoin({buckets:Array(Date)}) AS ref),\n"
        f"groups AS ({groups_body}),\n"
        "monthly AS (\n"
        f"  SELECT {monthly_bucket} AS bucket,"
        f" toStartOfMonth(r.mes_ref) AS month{dims_tail},\n"
        "         SUM(r.vl_margem) AS sum_margem, SUM(r.vl_saldo) AS sum_saldo,\n"
        f"         {_population_state('r')}\n"
        f"  FROM {database}.fato_rentabilidade_cliente AS r\n"
        f"  JOIN {database}.fato_cliente AS dc ON dc.id_cliente = r.id_cliente\n"
        "  WHERE r.mes_ref >= {start:Date} AND r.mes_ref <= {end:Date}"
        f"{sample_sql}\n"
        f"  GROUP BY bucket, month{dims_group}\n"
        "),\n"
        "agg AS (\n"
        f"  SELECT bucket{dims_group}, SUM(sum_margem) AS total_margem,"
        " SUM(sum_saldo) AS total_saldo, argMax(sum_saldo, month) AS last_saldo,\n"
        f"         {_population_merge()}\n"
        "  FROM monthly\n"
        f"  GROUP BY bucket{dims_group}\n"
        ")\n"
        f"SELECT {_dims_projection(axes, 'g')}b.ref, {', '.join(value_parts)}\n"
        "FROM groups AS g\n"
        "CROSS JOIN buckets AS b\n"
        f"LEFT JOIN agg AS a ON a.bucket = {join_bucket}"
        f"{_dims_join_condition(axes)}\n"
        f"ORDER BY b.ref{_order_dims(axes)}"
    )

    return sql, component_names


def _compile_rentabilidade_item(
    metric: MetricRequest,
    axes: list[_Axis],
    sample_sql: str,
    period: PeriodRequest,
    database: str,
) -> tuple[str, tuple[str, ...]]:

    dims_select = _dims_select(axes)
    dims_group = _dims_group(axes)
    dims_tail = f", {dims_select}" if dims_select else ""
    value_parts, component_names = _value_parts(metric)

    client_join = (
        f"\n  JOIN {database}.fato_cliente AS dc ON dc.id_cliente = c.id_cliente"
        if _needs_client(metric)
        else ""
    )

    monthly_bucket = _bucket_expr("r.mes_ref", period.grain)
    join_bucket = _join_bucket_expr("b.ref", period.grain)

    groups_body = (
        f"SELECT DISTINCT {dims_select}\n"
        f"  FROM {database}.fato_contrato_produtos AS cp\n"
        f"  JOIN {database}.dim_produto AS dp ON dp.id_produto = cp.id_produto\n"
        f"  JOIN {database}.fato_contratos AS c ON c.id_contrato = cp.id_contrato"
        f"{client_join}"
        if axes
        else "SELECT 1 AS _g"
    )

    sql = (
        "WITH buckets AS (SELECT arrayJoin({buckets:Array(Date)}) AS ref),\n"
        f"groups AS ({groups_body}),\n"
        "monthly AS (\n"
        f"  SELECT {monthly_bucket} AS bucket,"
        f" toStartOfMonth(r.mes_ref) AS month{dims_tail},\n"
        "         SUM(r.vl_margem) AS sum_margem, SUM(r.vl_saldo) AS sum_saldo,\n"
        f"         {_population_state('c')}\n"
        f"  FROM {database}.fato_rentabilidade_contrato_produto AS r\n"
        f"  JOIN {database}.dim_produto AS dp ON dp.id_produto = r.id_produto\n"
        f"  JOIN {database}.fato_contratos AS c ON c.id_contrato = r.id_contrato"
        f"{client_join}\n"
        "  WHERE r.mes_ref >= {start:Date} AND r.mes_ref <= {end:Date}"
        f"{sample_sql}\n"
        f"  GROUP BY bucket, month{dims_group}\n"
        "),\n"
        "agg AS (\n"
        f"  SELECT bucket{dims_group}, SUM(sum_margem) AS total_margem,"
        " SUM(sum_saldo) AS total_saldo, argMax(sum_saldo, month) AS last_saldo,\n"
        f"         {_population_merge()}\n"
        "  FROM monthly\n"
        f"  GROUP BY bucket{dims_group}\n"
        ")\n"
        f"SELECT {_dims_projection(axes, 'g')}b.ref, {', '.join(value_parts)}\n"
        "FROM groups AS g\n"
        "CROSS JOIN buckets AS b\n"
        f"LEFT JOIN agg AS a ON a.bucket = {join_bucket}"
        f"{_dims_join_condition(axes)}\n"
        f"ORDER BY b.ref{_order_dims(axes)}"
    )

    return sql, component_names


def _compile_mercado(
    metric: MetricRequest,
    axes: list[_Axis],
    sample_sql: str,
    period: PeriodRequest,
    database: str,
) -> tuple[str, tuple[str, ...]]:
    """Série macro mensal: o banco devolve as TAXAS MENSAIS do bucket.

    A composição `Π(1 + r_i) − 1` e a anualização são do kernel puro
    (`shared.aggregation`). Só `total.total` chega aqui: a guarda do motor e o
    `validate_plan` recusam eixo e recorte antes.
    """

    if axes or sample_sql:
        raise UnknownAxisError(
            "métrica macro não tem eixo nem recorte: só total.total."
        )

    indicator = _MARKET_RULE_INDICATORS.get(str(metric.rule_id))

    if indicator is None:
        raise UnknownSourceError(
            f"rule_id '{metric.rule_id}' não é um indicador de mercado."
        )

    monthly_bucket = _bucket_expr("m.mes_ref", period.grain)
    join_bucket = _join_bucket_expr("b.ref", period.grain)

    sql = (
        "WITH buckets AS (SELECT arrayJoin({buckets:Array(Date)}) AS ref),\n"
        "monthly AS (\n"
        f"  SELECT {monthly_bucket} AS bucket, groupArray(m.taxa) AS rates\n"
        f"  FROM {database}.mercado_indicadores AS m\n"
        "  WHERE m.indicador = {indicador:String}\n"
        "    AND m.mes_ref >= toStartOfMonth({start:Date})\n"
        "    AND m.mes_ref <= toStartOfMonth({end:Date})\n"
        "  GROUP BY bucket\n"
        ")\n"
        "SELECT b.ref AS ref, a.rates\n"
        "FROM buckets AS b\n"
        f"LEFT JOIN monthly AS a ON a.bucket = {join_bucket}\n"
        "ORDER BY b.ref"
    )

    return sql, ("rates",)


def _compile_contagem(
    metric: MetricRequest,
    axes: list[_Axis],
    sample_sql: str,
    period: PeriodRequest,
    database: str,
) -> tuple[str, tuple[str, ...]]:

    dims_select = _dims_select(axes)
    dims_group = _dims_group(axes)
    dims_tail = f", {dims_select}" if dims_select else ""
    distinct_key = _measure(metric.aggregation.distinct_key)

    join_parts: list[str] = []

    if _has_product_axis(metric):
        join_parts.append(
            f"  JOIN {database}.fato_contrato_produtos AS cp"
            " ON cp.id_contrato = c.id_contrato"
        )
        join_parts.append(
            f"  JOIN {database}.dim_produto AS dp ON dp.id_produto = cp.id_produto"
        )

    if _needs_client(metric):
        join_parts.append(
            f"  JOIN {database}.fato_cliente AS dc ON dc.id_cliente = c.id_cliente"
        )

    joins = "\n" + "\n".join(join_parts) if join_parts else ""

    groups_body = (
        f"SELECT DISTINCT {dims_select}\n  FROM {database}.fato_contratos AS c{joins}"
        if axes
        else "SELECT 1 AS _g"
    )

    sql = (
        "WITH buckets AS (SELECT arrayJoin({buckets:Array(Date)}) AS ref),\n"
        f"groups AS ({groups_body}),\n"
        "agg AS (\n"
        f"  SELECT b.ref AS ref{dims_tail}, uniqExact(c.{distinct_key}) AS v0_value,\n"
        f"         uniqExact(c.{_CUSTOMER_KEY}) AS {_POPULATION}\n"
        "  FROM buckets AS b\n"
        f"  CROSS JOIN {database}.fato_contratos AS c{joins}\n"
        "  WHERE c.dt_ini_contrato <= b.ref\n"
        "    AND (c.dt_encerramento IS NULL OR c.dt_encerramento >= b.ref)"
        f"{sample_sql}\n"
        f"  GROUP BY b.ref{dims_group}\n"
        ")\n"
        f"SELECT {_dims_projection(axes, 'g')}b.ref, a.v0_value,"
        f" a.{_POPULATION} AS v0_{_POPULATION}\n"
        "FROM groups AS g\n"
        "CROSS JOIN buckets AS b\n"
        f"LEFT JOIN agg AS a ON a.ref = b.ref{_dims_join_condition(axes)}\n"
        f"ORDER BY b.ref{_order_dims(axes)}"
    )

    return sql, ("value", _POPULATION)


def compile_query(
    metric: MetricRequest,
    period: PeriodRequest,
    database: str,
) -> CompiledQuery:
    """Compila UMA métrica numa consulta agregada pronta para executar."""

    source = _source(metric)
    axes = _axes(metric)
    sample_sql, sample_params = _sample_clauses(metric)
    buckets = _bucket_ends(period)

    params = {
        "start": dt.date.fromisoformat(period.start),
        "end": dt.date.fromisoformat(period.end),
        "buckets": [dt.date.fromisoformat(bucket) for bucket in buckets],
        **sample_params,
    }

    if source == _MERCADO:
        params["indicador"] = _MARKET_RULE_INDICATORS[str(metric.rule_id)]
        sql, component_names = _compile_mercado(
            metric, axes, sample_sql, period, database
        )
    elif source == _RENTABILIDADE_CLIENTE:
        sql, component_names = _compile_rentabilidade_cliente(
            metric, axes, sample_sql, period, database
        )
    elif source == _RENTABILIDADE_ITEM:
        sql, component_names = _compile_rentabilidade_item(
            metric, axes, sample_sql, period, database
        )
    elif source == _CONTRATO:
        sql, component_names = _compile_contagem(
            metric, axes, sample_sql, period, database
        )
    else:
        raise UnknownSourceError(f"source '{source}' sem caminho físico.")

    return CompiledQuery(
        sql=sql,
        params=params,
        axes=tuple(axes),
        component_names=component_names,
    )


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------


def _to_number(
    value: object,
) -> Decimal | int | None | tuple[Decimal | int | None, ...]:

    if value is None:
        return None

    if isinstance(value, (tuple, list)):
        return tuple(_to_number(item) for item in value)

    if isinstance(value, Decimal):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return Decimal(str(value))

    return Decimal(str(value))


def _map_rows(compiled: CompiledQuery, result_rows) -> list[AggregatedRow]:

    axis_count = len(compiled.axes)
    rows: list[AggregatedRow] = []

    for raw in result_rows:
        values = tuple(raw)
        subjects = {axis.key: values[index] for index, axis in enumerate(compiled.axes)}
        reference = values[axis_count]
        period = (
            reference.isoformat() if isinstance(reference, dt.date) else str(reference)
        )
        components = {
            name: _to_number(values[axis_count + 1 + index])
            for index, name in enumerate(compiled.component_names)
        }

        rows.append(
            AggregatedRow(subjects=subjects, period=period, components=components)
        )

    return rows


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class ClickHouseOfficialDataRepository:
    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
    ) -> None:

        import clickhouse_connect

        self._database = database
        # Sem sessão: os planos rodam em threads e o driver recusa queries
        # concorrentes na mesma sessão; leitura não precisa de afinidade.
        self._client = clickhouse_connect.get_client(
            host=host,
            port=port,
            database=database,
            username=user,
            password=password,
            autogenerate_session_id=False,
        )

    def fetch_aggregated(
        self,
        metric: MetricRequest,
        period: PeriodRequest,
    ) -> list[AggregatedRow]:

        compiled = compile_query(metric, period, self._database)
        result = self._client.query(
            compiled.sql,
            parameters=compiled.params,
            # Sem isto o ClickHouse preenche grupo ausente com o default do
            # tipo (0), e a ausência viraria 0.0 — exatamente o que a política
            # proíbe. Com join_use_nulls=1, ausência é NULL.
            settings={"join_use_nulls": 1},
        )

        return _map_rows(compiled, result.result_rows)

    def close(self) -> None:

        self._client.close()
