"""Fiação dos modos `--live`: o `LlmPort` configurado, sem tocar o armazém.

As camadas generativas usam exatamente os adapters do app: o prompt localizado
do planner, o catálogo do checkout e as capacidades do Auth. O handler roda
SEM pipeline — a proposta estruturada volta como `Structured`, que é o bastante
para comparar rota, planos, métodos e operações. Explicação e e2e completos
exigem o pipeline de execução (cálculo + redator) e são reportados como
pendentes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import uuid4

from contexts.auth.adapters.outbound.yaml_capabilities import YamlCapabilitiesAdapter
from contexts.auth.application.queries.authorize import AuthorizeQuery
from contexts.auth.domain.user import Role, User
from contexts.financial_analysis.adapters.outbound.auth_capacity_acl import (
    AuthCapacityAcl,
)
from contexts.financial_analysis.adapters.outbound.langchain_llm import (
    LangChainLlmAdapter,
)
from contexts.financial_analysis.adapters.outbound.localized_interpretation_prompt import (
    LocalizedInterpretationPromptAdapter,
)
from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from contexts.financial_analysis.application.commands.answer_question import (
    AnswerQuestionCommand,
    AnswerQuestionHandler,
)
from contexts.financial_analysis.application.commands.interpretation_schema import (
    InterpretationProposal,
)
from contexts.financial_analysis.ports.inbound.user_request import (
    ConversationContext,
    Structured,
)
from contexts.financial_analysis.ports.outbound.reference_date_port import (
    ReferenceDatePort,
)
from contexts.financial_analysis.ports.outbound.semantic_catalog_port import (
    SemanticCatalogPort,
)
from cross_cutting.config import ConfigError, load_config

DEFAULT_CONFIG = "config.yaml"


class LiveUnavailableError(RuntimeError):
    """O modo `--live` foi pedido, mas o LLM/prompt não está configurado."""


@dataclass(frozen=True)
class _CatalogReferenceDate(ReferenceDatePort):
    """Data de referência do catálogo: determinística e sem ClickHouse."""

    reference_date: date | None

    def latest_reference_date(self) -> date | None:

        return self.reference_date


class LivePlanner:
    """O planner real (`LlmPort` + prompt + catálogo), sem pipeline."""

    def __init__(self, config_path: Path | str = DEFAULT_CONFIG):

        try:
            config = load_config(config_path)
        except (ConfigError, OSError, ValueError) as error:
            raise LiveUnavailableError(
                f"configuração do LLM indisponível em '{config_path}': {error}. "
                "Crie o config.yaml (veja config.example.yaml) para usar --live."
            ) from error

        self._llm = LangChainLlmAdapter(config.llm)
        self._prompt = LocalizedInterpretationPromptAdapter(
            prompts_dir=config.data.resolved_interpretation_prompts_dir(),
            catalogs_dir=config.data.resolved_catalogs_dir(),
        )
        self._catalog: SemanticCatalogPort = YamlSemanticCatalogAdapter(
            catalogs_dir=config.data.resolved_catalogs_dir()
        )
        self._reference_date = _CatalogReferenceDate(
            self._catalog.load_active().reference_date
        )
        self._auth = AuthCapacityAcl(
            AuthorizeQuery(
                YamlCapabilitiesAdapter(
                    config_path=config.data.resolved_capabilities_file()
                )
            )
        )
        self._handler = AnswerQuestionHandler(
            llm=self._llm,
            prompt=self._prompt,
            reference_date=self._reference_date,
            catalog=self._catalog,
            auth_capacity=self._auth,
        )
        self._user = User(
            id="eval",
            name="Avaliação (harness)",
            email="eval@cantabria.invalid",
            roles=(Role(id="admin", name="admin"),),
        )

    def propose(self, question: str, case_id: str) -> InterpretationProposal | None:
        """Propõe para UMA pergunta; `None` quando o guardrail recusa na entrada."""

        contents = asyncio.run(self._propose(question, case_id))

        for content in contents:
            if isinstance(content, Structured):
                return InterpretationProposal.model_validate(content.data)

        return None

    async def _propose(self, question: str, case_id: str):
        context = ConversationContext(
            session_id=f"eval-{case_id}",
            messages=[],
            locale="pt-BR",
            trace_id=uuid4().hex,
        )

        return await self._handler.handle(
            AnswerQuestionCommand(user=self._user, context=context, request=question)
        )
