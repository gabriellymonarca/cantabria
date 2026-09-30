"""Composition root: wires the user_interaction context to the Chainlit UI."""

import asyncio
import os
import sys

import structlog
from chainlit.config import DEFAULT_HOST, DEFAULT_PORT

from contexts.auth.adapters.outbound.yaml_capabilities import (
    YamlCapabilitiesAdapter,
)
from contexts.auth.adapters.outbound.yaml_local_user_store import (
    YamlLocalUserStoreAdapter,
)
from contexts.auth.application.queries.authenticate import AuthenticateUserQuery
from contexts.auth.application.queries.authenticate_local import (
    AuthenticateLocalUserQuery,
)
from contexts.auth.application.queries.authorize import AuthorizeQuery
from contexts.financial_analysis.adapters.outbound.auth_capacity_acl import (
    AuthCapacityAcl,
)
from contexts.financial_analysis.adapters.outbound.calculation_service import (
    CalculationService,
)
from contexts.financial_analysis.adapters.outbound.clickhouse_dataset_fingerprint import (
    ClickHouseDatasetFingerprintAdapter,
)
from contexts.financial_analysis.adapters.outbound.clickhouse_reference_date import (
    ClickHouseReferenceDateAdapter,
)
from contexts.financial_analysis.adapters.outbound.hashed_snapshot_version import (
    HashedSnapshotVersionAdapter,
)
from contexts.financial_analysis.adapters.outbound.langchain_documental import (
    LangChainDocumentalSynthesisAdapter,
)
from contexts.financial_analysis.adapters.outbound.langchain_insight import (
    LangChainInsightAdapter,
)
from contexts.financial_analysis.adapters.outbound.langchain_llm import (
    LangChainLlmAdapter,
)
from contexts.financial_analysis.adapters.outbound.localized_interpretation_prompt import (
    LocalizedInterpretationPromptAdapter,
)
from contexts.financial_analysis.adapters.outbound.plotly_artifact_builder import (
    PlotlyArtifactBuilder,
)
from contexts.financial_analysis.adapters.outbound.reference_date_snapshot_version import (
    ReferenceDateSnapshotVersionAdapter,
)
from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from contexts.financial_analysis.application.commands.answer_question import (
    AnswerQuestionHandler,
)
from contexts.financial_analysis.application.commands.execute_pipeline import (
    AnalysisPipeline,
)
from contexts.financial_analysis.domain.errors import InvalidCatalogError
from contexts.financial_analysis.domain.services.describe_capabilities import (
    starter_questions,
)
from contexts.financial_analysis.ports.outbound.semantic_catalog_port import (
    SemanticCatalogPort,
)
from contexts.financial_calculation.application.commands.execute_calculations import (
    ExecuteCalculationsHandler,
)
from contexts.user_interaction.adapters.inbound.chainlit import ChainlitAdapter
from contexts.user_interaction.application.commands.submit_question import (
    SubmitQuestionHandler,
)
from cross_cutting.config import AppConfig, ConfigError, load_config
from cross_cutting.logging import configure_logging
from cross_cutting.observability import configure_observability, shutdown_observability
from entrypoints.composition import (
    build_calculation_store,
    build_chainlit_data_layer,
    build_event_wiring,
    build_knowledge,
    build_mongo_database,
    build_official_data_repository,
)
from entrypoints.env import load_dotenv
from entrypoints.health import (
    catalog_version,
    check_clickhouse,
    check_minio,
    check_mongo,
    check_qdrant,
    default_deps,
    prompt_version,
    register_health_route,
)

logger = structlog.get_logger("entrypoints.app")


def build_chainlit_adapter(config: AppConfig) -> ChainlitAdapter:
    """Instantiates the use cases and injects them into the inbound adapter."""

    llm = LangChainLlmAdapter(config.llm)
    prompt = LocalizedInterpretationPromptAdapter(
        prompts_dir=config.data.resolved_interpretation_prompts_dir(),
        catalogs_dir=config.data.resolved_catalogs_dir(),
    )
    reference_date = ClickHouseReferenceDateAdapter.from_env()
    catalog = YamlSemanticCatalogAdapter(
        catalogs_dir=config.data.resolved_catalogs_dir()
    )
    starters = _starters(catalog)
    prompts_version = prompt_version(config.data)
    auth_capacity = AuthCapacityAcl(
        AuthorizeQuery(
            YamlCapabilitiesAdapter(
                config_path=config.data.resolved_capabilities_file()
            )
        )
    )

    # Barramento de eventos em processo: os handlers publicam o que os
    # agregados registraram; as policies (persistir, gerar artefatos) reagem.
    # Com MongoDB conectado os stores são persistentes; sem ele, em memória.
    database = build_mongo_database()
    wiring = build_event_wiring(database)

    repository = build_official_data_repository()
    engine = ExecuteCalculationsHandler(
        repository, build_calculation_store(), publisher=wiring.dispatcher
    )
    pipeline = AnalysisPipeline(
        calculation=CalculationService(engine),
        snapshot_version=HashedSnapshotVersionAdapter(
            ReferenceDateSnapshotVersionAdapter(reference_date),
            ClickHouseDatasetFingerprintAdapter.from_env(),
        ),
        knowledge=build_knowledge(config),
        insight=LangChainInsightAdapter(
            llm, prompts_dir=config.data.resolved_insight_prompts_dir()
        ),
        documental_synthesis=LangChainDocumentalSynthesisAdapter(
            llm, prompts_dir=config.data.resolved_documental_prompts_dir()
        ),
        artifacts=PlotlyArtifactBuilder(),
        prompt_version=prompts_version,
    )

    authenticate = AuthenticateUserQuery(
        allowed_domains=config.auth.allowed_domains,
        role_map=config.auth.role_map,
        default_roles=config.auth.default_roles,
    )

    local_authenticate = None

    if config.auth.local_login_enabled:
        local_authenticate = AuthenticateLocalUserQuery(
            YamlLocalUserStoreAdapter(config.auth.users_file)
        )

    use_case = SubmitQuestionHandler(
        port=AnswerQuestionHandler(
            llm=llm,
            prompt=prompt,
            reference_date=reference_date,
            catalog=catalog,
            auth_capacity=auth_capacity,
            pipeline=pipeline,
            repository=wiring.analysis_requests,
            publisher=wiring.dispatcher,
        ),
        store=wiring.conversations,
        publisher=wiring.dispatcher,
    )
    adapter = ChainlitAdapter(
        port=use_case,
        authenticate=authenticate,
        local_authenticate=local_authenticate,
        data_layer=build_chainlit_data_layer(database),
        starters=starters,
        prompt_version=prompts_version,
    )

    return adapter


def _starters(catalog: SemanticCatalogPort) -> tuple[tuple[str, str], ...]:
    """Monta os starters da tela inicial a partir do catálogo ativo.

    Sem catálogo disponível a conversa abre sem starters: devolve vazio e o
    adapter não registra `set_starters`.
    """

    try:
        active = catalog.load_active()
    except InvalidCatalogError:
        logger.warning("Starters disabled: active catalog unavailable")
        return ()

    return starter_questions(active)


def log_startup_summary(config: AppConfig) -> None:
    """Logs the effective configuration once, before serving requests."""

    host = os.environ.get("CHAINLIT_HOST", DEFAULT_HOST)
    port = int(os.environ.get("CHAINLIT_PORT", str(DEFAULT_PORT)))

    tracing = (
        f"enabled ({config.observability.host})"
        if config.observability.enabled
        else "disabled"
    )

    logger.info(
        "Cantabria starting",
        server=f"http://{host}:{port}",
        health=f"http://{host}:{port}/health",
        ready=f"http://{host}:{port}/ready",
        tracing=tracing,
        catalog_version=catalog_version(),
        prompt_version=prompt_version(config.data),
        clickhouse=check_clickhouse(),
        mongo=check_mongo(),
        qdrant=check_qdrant(
            embeddings_configured=config.resolved_embeddings() is not None
        ),
        minio=check_minio(),
    )


if __name__ == "__main__":
    load_dotenv()

    try:
        config = load_config(os.environ.get("CONFIG_PATH", "config.yaml"))
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    configure_logging(config.logging.level)
    configure_observability(config.observability)
    log_startup_summary(config)

    from chainlit.server import app as chainlit_app

    register_health_route(chainlit_app, default_deps(config))

    try:
        asyncio.run(build_chainlit_adapter(config).run())
    finally:
        shutdown_observability()
