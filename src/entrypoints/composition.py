# Composition root: onde as implementações concretas são instanciadas e
# conectadas aos Ports dos Bounded Contexts, formando a aplicação executável.
#
# É a ÚNICA camada que conhece todos os contextos ao mesmo tempo. Os contextos
# não se conhecem entre si: cada um fala com o outro apenas por Port.
#
# Aqui se conecta o armazém de dados oficiais (ClickHouse) ao Port de leitura
# do financial_calculation, e se monta o barramento de eventos em processo com
# as policies inscritas. MongoDB (histórico, auditoria, outbox) entra quando
# `MONGO_URL` existe e responde; sem ele — ou fora do ar — a fiação degrada
# para os adapters em memória com aviso. Qdrant/MinIO entram quando
# configurados (QDRANT_URL + seção `embeddings`), com fallback lexical BM25
# quando indisponíveis.

import os
from dataclasses import dataclass

import structlog
from pymongo.database import Database

from contexts.financial_analysis.adapters.outbound.in_memory_analysis_request_repository import (
    InMemoryAnalysisRequestRepository,
)
from contexts.financial_analysis.adapters.outbound.in_memory_plan_store import (
    InMemoryPlanStore,
)
from contexts.financial_analysis.adapters.outbound.in_memory_result_store import (
    InMemoryResultStore,
)
from contexts.financial_analysis.adapters.outbound.langchain_embeddings import (
    LangChainEmbeddingsAdapter,
)
from contexts.financial_analysis.adapters.outbound.local_knowledge import (
    LocalKnowledgeAdapter,
)
from contexts.financial_analysis.adapters.outbound.mongo_artifact_store import (
    MongoArtifactStore,
)
from contexts.financial_analysis.adapters.outbound.mongo_plan_store import (
    MongoPlanStore,
)
from contexts.financial_analysis.adapters.outbound.mongo_result_store import (
    MongoResultStore,
)
from contexts.financial_analysis.adapters.outbound.plotly_artifact_builder import (
    PlotlyArtifactBuilder,
)
from contexts.financial_analysis.adapters.outbound.qdrant_knowledge import (
    QdrantKnowledgeAdapter,
)
from contexts.financial_analysis.adapters.outbound.resilient_knowledge import (
    ResilientKnowledgeAdapter,
)
from contexts.financial_analysis.application.policies.build_artifacts import (
    BuildArtifactsPolicy,
)
from contexts.financial_analysis.application.policies.persist_results import (
    PersistResultsPolicy,
)
from contexts.financial_analysis.ports.outbound.analysis_request_repository_port import (
    AnalysisRequestRepository,
)
from contexts.financial_analysis.ports.outbound.artifact_store_port import (
    ArtifactStorePort,
)
from contexts.financial_analysis.ports.outbound.knowledge_port import KnowledgePort
from contexts.financial_analysis.ports.outbound.plan_store_port import PlanStorePort
from contexts.financial_analysis.ports.outbound.result_store_port import (
    ResultStorePort,
)
from contexts.financial_calculation.adapters.outbound.clickhouse_config import (
    ClickHouseConfig,
)
from contexts.financial_calculation.adapters.outbound.clickhouse_official_data import (
    ClickHouseOfficialDataRepository,
)
from contexts.financial_calculation.adapters.outbound.in_memory_calculation_store import (
    InMemoryCalculationStore,
)
from contexts.user_interaction.adapters.inbound.chainlit_data_layer import (
    CantabriaDataLayer,
)
from contexts.user_interaction.adapters.outbound.in_memory_conversation_store import (
    InMemoryConversationStore,
)
from contexts.user_interaction.adapters.outbound.mongo_conversation_store import (
    MongoConversationStore,
)
from contexts.user_interaction.ports.outbound.conversation_store_port import (
    ConversationStorePort,
)
from cross_cutting.config import AppConfig
from cross_cutting.event_outbox import MongoEventOutbox
from cross_cutting.mongo import MongoConfig, open_database
from entrypoints.env import load_dotenv
from shared.domain_events import EventDispatcher

logger = structlog.get_logger("entrypoints.composition")


def build_official_data_repository() -> ClickHouseOfficialDataRepository:
    """Instancia o Adapter ClickHouse com a config do ambiente.

    Usa o usuário de APLICAÇÃO (read-only). O financial_calculation recebe
    apenas o Port (OfficialDataRepository). Carrega o `.env` local, se
    existir, para dev; em produção o ambiente já vem do hospedeiro.
    """
    load_dotenv()
    config = ClickHouseConfig.from_env()

    return ClickHouseOfficialDataRepository(
        host=config.host,
        port=config.port,
        database=config.database,
        user=config.user,
        password=config.password,
    )


def build_knowledge(config: AppConfig) -> KnowledgePort:
    """RAG semântico quando configurado e alcançável; senão BM25 lexical.

    A escolha é no boot (degradação graciosa): sem `QDRANT_URL`
    ou sem a seção `embeddings`, a busca é lexical; com Qdrant fora do ar,
    idem. Mesmo com Qdrant de pé, resultado semântico vazio cai no BM25 — o
    acervo é pequeno e o léxico ainda acha o que o embedding pode perder.
    """
    load_dotenv()
    fallback = LocalKnowledgeAdapter()
    url = os.environ.get("QDRANT_URL", "").strip()
    settings = config.resolved_embeddings()

    if not url:
        logger.info("QDRANT_URL not set; knowledge search is lexical (BM25)")

        return fallback

    if settings is None:
        logger.info("embeddings not configured; knowledge search is lexical (BM25)")

        return fallback

    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=url, timeout=2.0)
        client.get_collections()
    except Exception as error:
        logger.warning(
            "Qdrant unavailable; knowledge search is lexical (BM25)",
            error=str(error),
        )

        return fallback

    logger.info("Qdrant knowledge enabled", collection="knowledge")

    return ResilientKnowledgeAdapter(
        primary=QdrantKnowledgeAdapter(
            client=client,
            embeddings=LangChainEmbeddingsAdapter(
                model=settings.model,
                base_url=settings.base_url,
                api_key=settings.api_key,
            ),
        ),
        fallback=fallback,
    )


def build_calculation_store() -> InMemoryCalculationStore:
    """Store de resultados por chave de reuso, em memória."""
    return InMemoryCalculationStore()


def build_mongo_database() -> Database | None:
    """Abre o MongoDB quando `MONGO_URL` existe; senão devolve `None`.

    A verificação é no boot: se o servidor não responde, a aplicação segue com
    os stores em memória e o aviso fica no log e no `/ready`.
    """
    load_dotenv()
    config = MongoConfig.from_env()

    if config is None:
        logger.info("MONGO_URL not set; conversation and audit stores in memory")

        return None

    try:
        database = open_database(config)
    except Exception as error:
        logger.warning(
            "MongoDB unavailable; conversation and audit stores in memory",
            error=str(error),
        )

        return None

    logger.info("MongoDB connected", database=database.name)

    return database


def build_chainlit_data_layer(database: Database | None) -> CantabriaDataLayer | None:
    """O data layer da barra lateral existe apenas com Mongo."""

    return CantabriaDataLayer(database) if database is not None else None


@dataclass(frozen=True)
class EventWiring:
    """O barramento em processo e os stores que as policies alimentam."""

    dispatcher: EventDispatcher
    analysis_requests: AnalysisRequestRepository
    plan_store: PlanStorePort
    result_store: ResultStorePort
    artifact_store: ArtifactStorePort | None
    conversations: ConversationStorePort


def build_event_wiring(database: Database | None = None) -> EventWiring:
    """Monta o dispatcher, os stores e as policies (persistir, gerar artefatos).

    Com MongoDB, planos/resultados/artefatos/conversas vão para as coleções e
    o outbox grava cada evento na coleção `events`. Sem ele, tudo em memória.
    """

    dispatcher = EventDispatcher()
    analysis_requests = InMemoryAnalysisRequestRepository()

    if database is not None:
        plan_store: PlanStorePort = MongoPlanStore(database)
        result_store: ResultStorePort = MongoResultStore(database)
        artifact_store: ArtifactStorePort | None = MongoArtifactStore(database)
        conversations: ConversationStorePort = MongoConversationStore(database)

        MongoEventOutbox(database).subscribe(dispatcher)
    else:
        plan_store = InMemoryPlanStore()
        result_store = InMemoryResultStore()
        artifact_store = None
        conversations = InMemoryConversationStore()

    PersistResultsPolicy(
        repository=analysis_requests,
        plan_store=plan_store,
        result_store=result_store,
    ).subscribe(dispatcher)
    BuildArtifactsPolicy(
        repository=analysis_requests,
        builder=PlotlyArtifactBuilder(),
        artifact_store=artifact_store,
    ).subscribe(dispatcher)

    return EventWiring(
        dispatcher=dispatcher,
        analysis_requests=analysis_requests,
        plan_store=plan_store,
        result_store=result_store,
        artifact_store=artifact_store,
        conversations=conversations,
    )
