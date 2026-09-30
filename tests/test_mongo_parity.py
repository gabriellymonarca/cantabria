"""Stores MongoDB contra um servidor real (testcontainers).

Sobe um MongoDB efêmero `mongo:7` (mesma versão do compose) e exercita os
adapters como a aplicação os usa: round-trip da conversa pelo BSON real,
documentos de plano/resultado com `Decimal128` (exatidão, não float), outbox e
o data layer da barra lateral do Chainlit.

Requer Docker. Rode: pytest -m integration
"""

from __future__ import annotations

import asyncio
import datetime as dt
from decimal import Decimal

import pytest
from bson.decimal128 import Decimal128
from chainlit.types import Pagination, ThreadFilter

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
from contexts.financial_analysis.ports.inbound.user_request import Dataframe, Text
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
from contexts.user_interaction.adapters.outbound.mongo_conversation_store import (
    MongoConversationStore,
)
from contexts.user_interaction.domain.conversation import Conversation
from contexts.user_interaction.domain.events import QuestionSubmitted
from cross_cutting.event_outbox import MongoEventOutbox
from cross_cutting.mongo import MongoConfig, from_bson_safe, open_database
from shared.domain_events import EventDispatcher

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def mongo():

    from testcontainers.community.mongodb import MongoDbContainer

    with MongoDbContainer("mongo:7") as container:
        yield container


@pytest.fixture(scope="module")
def database(mongo):

    client = mongo.get_connection_client()

    yield client["cantabria"]

    client.drop_database("cantabria")
    client.close()


def _conversation() -> Conversation:

    conversation = Conversation("s1", "u1")
    conversation.submit_question("t1", [Text(text="Qual a rentabilidade?")])
    conversation.deliver_response("t1", [Text(text="A rentabilidade é 16%.")])
    conversation.pull_events()

    return conversation


def test_conversa_round_trip_e_data_layer(database) -> None:

    store = MongoConversationStore(database)
    store.save(_conversation())

    loaded = store.load("s1")

    assert loaded is not None
    assert loaded.turns[1].contents == (Text(text="A rentabilidade é 16%."),)

    layer = CantabriaDataLayer(database)

    asyncio.run(layer.update_thread("s1", name="Rentabilidade", user_id="ana@banco"))

    page = asyncio.run(
        layer.list_threads(Pagination(first=10), ThreadFilter(userId="ana@banco"))
    )

    assert [thread["id"] for thread in page.data] == ["s1"]
    assert asyncio.run(layer.get_thread_author("s1")) == "ana@banco"

    thread = asyncio.run(layer.get_thread("s1"))

    assert thread is not None
    assert thread["steps"][0]["output"] == "Qual a rentabilidade?"

    asyncio.run(layer.delete_thread("s1"))

    assert store.load("s1") is None


def test_dataframe_com_decimal_no_bson_real(database) -> None:

    conversation = Conversation("dec1", "u1")
    conversation.submit_question("t1", [Text(text="Qual o share?")])
    conversation.deliver_response(
        "t1",
        [Dataframe(columns=["share"], rows=[[Decimal("0.16")]])],
    )
    conversation.pull_events()

    store = MongoConversationStore(database)
    store.save(conversation)

    loaded = store.load("dec1")

    assert loaded is not None
    assert loaded.turns[1].contents[0].rows == [[Decimal("0.16")]]

    database["conversations"].delete_one({"_id": "dec1"})


def test_data_layer_pagina_com_cursor_no_bson_real(database) -> None:

    store = MongoConversationStore(database)
    layer = CantabriaDataLayer(database)

    for index in range(3):
        conversation = Conversation(f"p{index}", "u1")
        conversation.submit_question(f"t{index}", [Text(text=f"Pergunta {index}")])
        conversation.deliver_response(f"t{index}", [Text(text="Resposta")])
        conversation.pull_events()
        store.save(conversation)
        asyncio.run(layer.update_thread(f"p{index}", user_id="ana-pagina@banco"))

    first = asyncio.run(
        layer.list_threads(Pagination(first=2), ThreadFilter(userId="ana-pagina@banco"))
    )

    assert [thread["id"] for thread in first.data] == ["p2", "p1"]
    assert first.pageInfo.hasNextPage is True

    second = asyncio.run(
        layer.list_threads(
            Pagination(first=2, cursor=first.pageInfo.endCursor),
            ThreadFilter(userId="ana-pagina@banco"),
        )
    )

    assert [thread["id"] for thread in second.data] == ["p0"]
    assert second.pageInfo.hasNextPage is False

    database["conversations"].delete_many({"_id": {"$in": ["p0", "p1", "p2"]}})


def test_planos_resultado_e_artefato_com_decimal_exato(database) -> None:

    timestamp = dt.datetime(2026, 9, 29, 12, 0, tzinfo=dt.UTC)
    calculation = CalculationPlan(
        calculation_plan_id="calc_1",
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
    analysis = AnalysisPlan(
        id="plan1",
        statistical_method=(
            StatisticalMethod(
                id="s1",
                method=StatisticalMethodType.MEAN,
                calculation_plan_ids=("calc_1",),
            ),
        ),
    )

    MongoPlanStore(database, clock=lambda: timestamp).save_plans(
        trace_id="t1",
        analysis_plan=analysis,
        calculation_plans=[calculation],
        catalog_version="v2",
    )
    MongoResultStore(database, clock=lambda: timestamp).save_result(
        "t1",
        AnalysisResult(
            analysis_plan_id="plan1",
            catalog_version="v2",
            dataset_version="ds1",
            trace_id="t1",
            statistical_method=[
                MethodResult(
                    id="s1",
                    method="mean",
                    values=[
                        MethodValue(
                            subjects={"customer_segmentation.segment": "Varejo PF"},
                            values={"value": Decimal("0.132")},
                        )
                    ],
                )
            ],
        ),
    )
    MongoArtifactStore(database, clock=lambda: timestamp).save_artifacts(
        "t1",
        [ArtifactRef("art-1", ArtifactKind.CHART, "minio://cantabria/art-1")],
    )

    analysis_docs = list(database["analysis_store"].find())

    assert {doc["type"] for doc in analysis_docs} == {"plan", "result"}

    result = next(doc for doc in analysis_docs if doc["type"] == "result")
    stored = result["result_dsc"]["statistical_method"][0]["values"][0]

    assert stored["values"]["value"] == Decimal128("0.132")
    assert from_bson_safe(stored["values"]["value"]) == Decimal("0.132")

    plan = database["calculation_store"].find_one({"_id": "calc_1"})
    start = plan["plan_dsc"]["period"]["start"]

    assert start.replace(tzinfo=dt.UTC) == dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

    artifact = database["artifacts"].find_one({"_id": "art-1"})

    assert artifact["kind"] == "chart"


def test_outbox_grava_eventos_de_contextos_diferentes(database) -> None:

    dispatcher = EventDispatcher()

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

    events = {doc["event"] for doc in database["events"].find()}

    assert events == {"QuestionSubmitted", "PlanProposed"}


def test_open_database_pinga_a_url_do_ambiente(mongo) -> None:

    opened = open_database(MongoConfig(url=mongo.get_connection_url()))

    assert opened.name == "cantabria"
    assert opened.command("ping")["ok"] == 1

    opened.client.close()
