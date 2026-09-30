"""Stores MongoDB: documentos, outbox e data layer do Chainlit (mongomock).

O dobro `mongomock` cobre a forma dos documentos e o comportamento das
consultas; a paridade com um MongoDB real fica em `test_mongo_parity.py`.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from decimal import Decimal

import mongomock
import pytest
from bson.decimal128 import Decimal128
from chainlit.types import Pagination, ThreadFilter
from pymongo.errors import DuplicateKeyError

from contexts.financial_analysis.adapters.outbound.in_memory_plan_store import (
    InMemoryPlanStore,
)
from contexts.financial_analysis.adapters.outbound.in_memory_result_store import (
    InMemoryResultStore,
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
from contexts.financial_analysis.domain.analysis_plan import (
    AnalysisPlan,
    StatisticalMethod,
    StatisticalMethodType,
)
from contexts.financial_analysis.domain.analysis_result import (
    AnalysisResult,
    MethodResult,
    MethodValue,
)
from contexts.financial_analysis.domain.artifacts import ArtifactKind, ArtifactRef
from contexts.financial_analysis.domain.events import PlanProposed
from contexts.financial_analysis.domain.interpretation import InterpretationRoute
from contexts.financial_analysis.ports.inbound.user_request import (
    Dataframe,
    Image,
    MethodNote,
    Plotly,
    Structured,
    Text,
)
from contexts.financial_calculation.domain.calculation_plan import (
    AxisLevel,
    AxisType,
    CalculationPlan,
    Grain,
    Metric,
    Period,
    PeriodType,
    RuleId,
    Subject,
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
from contexts.user_interaction.domain.conversation import Conversation
from contexts.user_interaction.domain.events import QuestionSubmitted
from cross_cutting.event_outbox import MongoEventOutbox
from cross_cutting.mongo import MongoConfig, from_bson_safe, upsert_document
from entrypoints.composition import (
    build_chainlit_data_layer,
    build_event_wiring,
)
from entrypoints.health import check_mongo
from shared.domain_events import EventDispatcher

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

TIMESTAMP = dt.datetime(2026, 9, 29, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def database():

    return mongomock.MongoClient().cantabria


def _conversation() -> Conversation:

    conversation = Conversation("s1", "u1")
    conversation.submit_question("t1", [Text(text="Qual a rentabilidade?")])
    conversation.deliver_response(
        "t1",
        [
            Text(text="A rentabilidade é 16%."),
            Dataframe(columns=["segmento", "share"], rows=[["Varejo PF", 0.16]]),
            Plotly(figure={"data": [{"type": "bar"}]}),
            Structured(data={"nota": "recorte"}),
            Image(data=b"\x89PNG", mime_type="image/png"),
            MethodNote(title="Como calculei", text="- Métrica: rentabilidade."),
        ],
    )
    conversation.submit_question("t2", [Text(text="E o saldo?")])
    conversation.deliver_response("t2", [Text(text="O saldo cresceu.")])
    conversation.pull_events()

    return conversation


def _calculation_plan(plan_id: str) -> CalculationPlan:

    return CalculationPlan(
        calculation_plan_id=plan_id,
        metric=Metric(
            rule_id=RuleId.PROFITABILITY,
            subjects=(Subject(AxisType.TOTAL, AxisLevel.TOTAL),),
        ),
        period=Period(
            start=dt.date(2026, 1, 1),
            end=dt.date(2026, 8, 31),
            type=PeriodType.SERIES,
            grain=Grain.MONTH,
        ),
    )


def _analysis_plan() -> AnalysisPlan:

    return AnalysisPlan(
        id="plan1",
        statistical_method=(
            StatisticalMethod(
                id="s1",
                method=StatisticalMethodType.MEAN,
                calculation_plan_ids=("calc_1", "calc_2"),
            ),
        ),
    )


def _analysis_result() -> AnalysisResult:

    return AnalysisResult(
        analysis_plan_id="plan1",
        catalog_version="v2",
        dataset_version="ds1",
        trace_id="t1",
        statistical_method=[
            MethodResult(
                id="s1",
                method="mean",
                unit="decimal_rate",
                rule_id="profitability",
                values=[
                    MethodValue(
                        subjects={"customer_segmentation.segment": "Varejo PF"},
                        values={"value": Decimal("0.132")},
                    )
                ],
            )
        ],
    )


def test_conversa_sobrevive_ao_round_trip(database) -> None:

    store = MongoConversationStore(database)
    conversation = _conversation()

    store.save(conversation)
    loaded = store.load("s1")

    assert loaded is not None
    assert loaded.user_id == "u1"
    assert [turn.trace_id for turn in loaded.turns] == ["t1", "t1", "t2", "t2"]
    assert [turn.role for turn in loaded.turns] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert loaded.turns[0].contents == (Text(text="Qual a rentabilidade?"),)
    assert loaded.turns[1].contents[1] == Dataframe(
        columns=["segmento", "share"], rows=[["Varejo PF", 0.16]]
    )
    assert loaded.turns[1].contents[4] == Image(data=b"\x89PNG", mime_type="image/png")
    assert loaded.turns[1].contents[5] == MethodNote(
        title="Como calculei", text="- Métrica: rentabilidade."
    )
    assert store.load("inexistente") is None


def test_conversa_carregada_continua_em_outro_processo(database) -> None:

    store = MongoConversationStore(database)
    store.save(_conversation())

    resumed = MongoConversationStore(database).load("s1")

    assert resumed is not None

    resumed.submit_question("t3", [Text(text="E a tendência?")])
    resumed.deliver_response("t3", [Text(text="A tendência é de alta.")])
    resumed.pull_events()
    store.save(resumed)

    again = store.load("s1")

    assert again is not None
    assert [turn.trace_id for turn in again.turns][-2:] == ["t3", "t3"]


def test_dataframe_com_decimal_volta_como_decimal(database) -> None:

    conversation = Conversation("s1", "u1")
    conversation.submit_question("t1", [Text(text="Qual o share?")])
    conversation.deliver_response(
        "t1",
        [Dataframe(columns=["share"], rows=[[Decimal("0.16")]])],
    )
    conversation.pull_events()

    store = MongoConversationStore(database)
    store.save(conversation)

    loaded = store.load("s1")

    assert loaded is not None
    assert loaded.turns[1].contents[0].rows == [[Decimal("0.16")]]


def test_upsert_repete_quando_perde_a_corrida_de_criacao() -> None:

    class _FlakyCollection:
        def __init__(self) -> None:

            self.calls = 0

        def update_one(self, selector, update, upsert=False) -> None:

            self.calls += 1

            if self.calls == 1:
                raise DuplicateKeyError("corrida no _id")

    collection = _FlakyCollection()

    upsert_document(collection, {"_id": "s1"}, {"$set": {}})

    assert collection.calls == 2


def test_save_preserva_o_subdocumento_da_barra_lateral(database) -> None:

    collection = database["conversations"]
    collection.update_one(
        {"_id": "s1"},
        {"$set": {"thread": {"name": "Rentabilidade", "user_id": "ana@banco"}}},
        upsert=True,
    )

    MongoConversationStore(database).save(_conversation())

    document = collection.find_one({"_id": "s1"})

    assert document["thread"]["name"] == "Rentabilidade"
    assert document["turns"][0]["contents"][0] == {
        "type": "text",
        "text": "Qual a rentabilidade?",
    }


def test_plan_store_grava_os_dois_stores_logicos(database) -> None:

    store = MongoPlanStore(database, clock=lambda: TIMESTAMP)

    store.save_plans(
        trace_id="t1",
        analysis_plan=_analysis_plan(),
        calculation_plans=[_calculation_plan("calc_1"), _calculation_plan("calc_2")],
        catalog_version="v2",
    )

    analysis = database["analysis_store"].find_one({"_id": "t1:plan"})

    assert analysis["type"] == "plan"
    assert analysis["plan_id"] == "plan1"
    assert analysis["calculation_plan_ids"] == ["calc_1", "calc_2"]
    assert analysis["catalog_version"] == "v2"
    assert analysis["timestamp"].replace(tzinfo=dt.UTC) == TIMESTAMP
    assert analysis["plan_dsc"]["statistical_method"][0]["method"] == "mean"

    calculations = list(database["calculation_store"].find())

    assert [doc["_id"] for doc in calculations] == ["calc_1", "calc_2"]
    assert calculations[0]["type"] == "plan"
    assert calculations[0]["plan_dsc"]["metric"]["rule_id"] == "profitability"
    assert calculations[0]["plan_dsc"]["period"]["grain"] == "month"


def test_result_store_grava_decimal128_e_gruda_o_insight(database) -> None:

    store = MongoResultStore(database, clock=lambda: TIMESTAMP)

    store.save_result("t1", _analysis_result())
    store.save_insight("t1", "Explicação verificada.", "| tabela |")

    documents = list(database["analysis_store"].find())

    assert len(documents) == 1

    document = documents[0]

    assert document["_id"] == "t1:result"
    assert document["type"] == "result"
    assert document["plan_id"] == "plan1"
    assert document["dataset_version"] == "ds1"
    assert document["insight"] == "Explicação verificada."
    assert document["verified_table"] == "| tabela |"

    stored = document["result_dsc"]["statistical_method"][0]["values"][0]

    assert stored["values"]["value"] == Decimal128("0.132")
    assert from_bson_safe(stored["values"]["value"]) == Decimal("0.132")


def test_artifact_store_grava_metadados(database) -> None:

    store = MongoArtifactStore(database, clock=lambda: TIMESTAMP)

    store.save_artifacts(
        "t1",
        [
            ArtifactRef(
                artifact_id="art-1",
                kind=ArtifactKind.CHART,
                location="minio://cantabria/t1/chart.html",
            )
        ],
    )

    document = database["artifacts"].find_one({"_id": "art-1"})

    assert document["type"] == "artifact"
    assert document["kind"] == "chart"
    assert document["trace_id"] == "t1"
    assert document["location"] == "minio://cantabria/t1/chart.html"


def test_outbox_grava_todos_os_tipos_de_evento(database) -> None:

    dispatcher = EventDispatcher()
    seen: list[str] = []

    dispatcher.subscribe(
        QuestionSubmitted, lambda event: seen.append(type(event).__name__)
    )
    MongoEventOutbox(database).subscribe(dispatcher)

    dispatcher.publish(
        [
            QuestionSubmitted(aggregate_id="s1", trace_id="t1"),
            PlanProposed(
                aggregate_id="t1",
                route=InterpretationRoute.ANALYTICAL,
                calculation_plan_ids=("calc_1",),
                analysis_plan_id="plan1",
            ),
        ]
    )

    documents = {doc["event"]: doc for doc in database["events"].find()}

    assert seen == ["QuestionSubmitted"]
    assert set(documents) == {"QuestionSubmitted", "PlanProposed"}
    assert documents["QuestionSubmitted"]["aggregate_id"] == "s1"
    assert documents["QuestionSubmitted"]["payload"] == {"trace_id": "t1"}
    assert documents["PlanProposed"]["payload"]["route"] == "analytical"


def test_outbox_nao_derruba_o_turno_quando_a_escrita_falha(
    database, monkeypatch
) -> None:

    def _boom(document):

        raise RuntimeError("mongo fora do ar")

    monkeypatch.setattr(database["events"], "insert_one", _boom)

    dispatcher = EventDispatcher()
    MongoEventOutbox(database).subscribe(dispatcher)

    dispatcher.publish([QuestionSubmitted(aggregate_id="s1", trace_id="t1")])


def test_data_layer_lista_conversas_do_usuario(database) -> None:

    store = MongoConversationStore(database)
    store.save(_conversation())

    layer = CantabriaDataLayer(database)

    asyncio.run(layer.update_thread("s1", name="Rentabilidade", user_id="ana@banco"))

    page = asyncio.run(
        layer.list_threads(Pagination(first=10), ThreadFilter(userId="ana@banco"))
    )

    assert [thread["id"] for thread in page.data] == ["s1"]
    assert page.data[0]["name"] == "Rentabilidade"
    assert page.data[0]["userIdentifier"] == "ana@banco"
    assert asyncio.run(layer.get_thread_author("s1")) == "ana@banco"

    other = asyncio.run(
        layer.list_threads(Pagination(first=10), ThreadFilter(userId="bia@banco"))
    )

    assert other.data == []


def test_data_layer_deriva_passos_dos_turnos(database) -> None:

    store = MongoConversationStore(database)
    store.save(_conversation())

    layer = CantabriaDataLayer(database)
    thread = asyncio.run(layer.get_thread("s1"))

    assert thread is not None
    assert [step["type"] for step in thread["steps"]] == [
        "user_message",
        "assistant_message",
        "user_message",
        "assistant_message",
    ]
    assert thread["steps"][0]["output"] == "Qual a rentabilidade?"
    assert thread["name"] == "Qual a rentabilidade?"


def test_data_layer_pagina_com_cursor(database) -> None:

    store = MongoConversationStore(database)
    layer = CantabriaDataLayer(database)

    for index in range(3):
        conversation = Conversation(f"s{index}", "u1")
        conversation.submit_question(f"t{index}", [Text(text=f"Pergunta {index}")])
        conversation.deliver_response(f"t{index}", [Text(text="Resposta")])
        conversation.pull_events()
        store.save(conversation)
        asyncio.run(layer.update_thread(f"s{index}", user_id="ana@banco"))

    first = asyncio.run(
        layer.list_threads(Pagination(first=2), ThreadFilter(userId="ana@banco"))
    )

    assert [thread["id"] for thread in first.data] == ["s2", "s1"]
    assert first.pageInfo.hasNextPage is True
    assert first.pageInfo.endCursor

    second = asyncio.run(
        layer.list_threads(
            Pagination(first=2, cursor=first.pageInfo.endCursor),
            ThreadFilter(userId="ana@banco"),
        )
    )

    assert [thread["id"] for thread in second.data] == ["s0"]
    assert second.pageInfo.hasNextPage is False


def test_data_layer_apaga_a_conversa(database) -> None:

    store = MongoConversationStore(database)
    store.save(_conversation())

    layer = CantabriaDataLayer(database)
    asyncio.run(layer.delete_thread("s1"))

    assert store.load("s1") is None


def test_mongo_config_vem_do_ambiente(monkeypatch) -> None:

    monkeypatch.setenv("MONGO_URL", "mongodb://db:27017/cantabria")

    assert MongoConfig.from_env() == MongoConfig(url="mongodb://db:27017/cantabria")

    monkeypatch.delenv("MONGO_URL")

    assert MongoConfig.from_env() is None


def test_wiring_usa_mongo_quando_o_banco_existe(database) -> None:

    wiring = build_event_wiring(database)

    assert isinstance(wiring.plan_store, MongoPlanStore)
    assert isinstance(wiring.result_store, MongoResultStore)
    assert isinstance(wiring.artifact_store, MongoArtifactStore)
    assert isinstance(wiring.conversations, MongoConversationStore)
    assert isinstance(build_chainlit_data_layer(database), CantabriaDataLayer)


def test_wiring_sem_banco_fica_em_memoria() -> None:

    wiring = build_event_wiring()

    assert isinstance(wiring.plan_store, InMemoryPlanStore)
    assert isinstance(wiring.result_store, InMemoryResultStore)
    assert wiring.artifact_store is None
    assert isinstance(wiring.conversations, InMemoryConversationStore)
    assert build_chainlit_data_layer(None) is None


def test_check_mongo_sem_url_esta_desabilitado(monkeypatch) -> None:

    monkeypatch.delenv("MONGO_URL", raising=False)

    assert check_mongo() == "disabled (in-memory)"


def test_check_mongo_nao_levanta_quando_o_servidor_falha(monkeypatch) -> None:

    monkeypatch.setenv("MONGO_URL", "mongodb://db:27017/cantabria")

    def _boom(config):

        raise RuntimeError("sem rota para o servidor")

    monkeypatch.setattr("cross_cutting.mongo.open_database", _boom)

    assert check_mongo().startswith("error:")
