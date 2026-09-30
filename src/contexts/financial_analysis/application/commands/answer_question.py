"""Comando `AnswerQuestion`: interpreta, valida, executa e explica um turno.

O handler cria o agregado `AnalysisRequest` no início do turno, conduz suas
transições (propose → approve/reject → complete → explain, ou refuse/
ask_clarification), salva o agregado e publica os eventos que ele registrou.
Interpretação e validação são locais e determinísticas; a execução é delegada
a um `AnalysisPipeline` injetado. Sem pipeline o handler ainda propõe a rota e
os planos governados (útil nos testes do planner), mas a resposta real vem do
pipeline.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import uuid4

import structlog

from contexts.auth.ports.inbound.authorize_port import User, UserCapabilities
from contexts.financial_analysis.application.commands.execute_pipeline import (
    AnalysisPipeline,
)
from contexts.financial_analysis.application.commands.interpretation_schema import (
    InterpretationProposal,
)
from contexts.financial_analysis.domain.analysis_request import AnalysisRequest
from contexts.financial_analysis.domain.errors import (
    AnalysisExecutionError,
    PlanValidationError,
)
from contexts.financial_analysis.domain.insight_presentation import (
    sanitize_user_text,
)
from contexts.financial_analysis.domain.interpretation import (
    InterpretationRoute,
    RefusalReason,
)
from contexts.financial_analysis.domain.semantic_catalog import SemanticCatalog
from contexts.financial_analysis.domain.services.describe_capabilities import (
    describe_capabilities,
)
from contexts.financial_analysis.domain.services.describe_method import (
    METHOD_NOTE_TITLE,
    describe_method,
)
from contexts.financial_analysis.domain.services.input_guard import (
    PHYSICAL_FIELD,
    PROMPT_INJECTION,
    SQL_FRAGMENT,
    TOO_LONG,
    GuardAction,
    GuardVerdict,
    guard_input,
)
from contexts.financial_analysis.domain.services.provenance import (
    is_provenance_footer,
    provenance_footer,
)
from contexts.financial_analysis.domain.services.validate_plan import (
    ValidatedPlan,
    validate_plan,
)
from contexts.financial_analysis.ports.inbound.user_request import (
    Content,
    ConversationContext,
    MessageRole,
    MethodNote,
    ProcessUserRequestPort,
    Structured,
    Text,
)
from contexts.financial_analysis.ports.outbound.analysis_request_repository_port import (
    AnalysisRequestRepository,
)
from contexts.financial_analysis.ports.outbound.auth_capacity_port import (
    AuthCapacityPort,
)
from contexts.financial_analysis.ports.outbound.interpretation_prompt_port import (
    InterpretationPromptPort,
)
from contexts.financial_analysis.ports.outbound.llm_port import (
    LlmMessage,
    LlmPort,
    LlmRole,
    StructuredOutputError,
)
from contexts.financial_analysis.ports.outbound.reference_date_port import (
    ReferenceDatePort,
)
from contexts.financial_analysis.ports.outbound.semantic_catalog_port import (
    SemanticCatalogPort,
)
from contexts.financial_calculation.ports.inbound.execute_calculations_port import (
    CalculationError,
)
from shared.domain_events import EventDispatcher, EventPublisher

logger = structlog.get_logger(__name__)

_EXECUTION_FAILED = "Não consegui concluir o cálculo sobre os dados oficiais: {detail}"

_SCHEMA_RETRY_NOTE = (
    "A resposta anterior não era um JSON válido para o schema da ferramenta "
    "InterpretationProposal (campo ausente, tipo errado, valor fora dos enums ou "
    "plano malformado: janela invertida, snapshot com datas diferentes, quebra "
    "repetida ou ausente). Detalhe: {detail}. Responda de novo preenchendo "
    "apenas os campos do schema, com os valores permitidos, sem texto fora da "
    "estrutura."
)

_SCHEMA_CLARIFICATION = (
    "Não consegui estruturar sua pergunta com segurança. Pode reformular "
    "indicando a métrica (rentabilidade, saldo, contratos ou clientes), o recorte "
    "(segmento, produto...) e o período?"
)

# Recusas do guardrail de entrada: mensagem fixa por código de recusa.
_INPUT_REFUSALS: dict[str, str] = {
    PHYSICAL_FIELD: (
        "Não posso atender pedidos que referenciem campos físicos da base; use os "
        "termos de negócio (segmento, produto, rentabilidade, saldo)."
    ),
    SQL_FRAGMENT: (
        "Não posso executar instruções ou SQL; faça a pergunta em linguagem de negócio."
    ),
    PROMPT_INJECTION: (
        "Não posso alterar as regras de funcionamento; faça a pergunta analítica "
        "que deseja."
    ),
    TOO_LONG: (
        "Sua mensagem é longa demais para uma pergunta; resuma o que deseja saber "
        "em poucas frases."
    ),
}

_REDACTION_NOTICE = (
    "Removi dados pessoais da sua pergunta antes de processá-la ({kinds})."
)

_KIND_LABELS: dict[str, str] = {
    "cpf": "CPF",
    "cnpj": "CNPJ",
    "email": "e-mail",
    "phone": "telefone",
}

_ROLE_MESSAGES: dict[MessageRole, LlmRole] = {
    MessageRole.USER: "user",
    MessageRole.ASSISTANT: "assistant",
}

_MAX_HISTORY_MESSAGES = 10
_MAX_MESSAGE_CHARS = 2000

_PLANNER_STEP = "planner"


@dataclass(frozen=True)
class AnswerQuestionCommand:
    """Responder à pergunta de um usuário dentro de uma conversa."""

    user: User
    context: ConversationContext
    request: str


# Financial analysis entry point: create plan, validate, execute, retrieve
# knowledge and generate the insight. Interpretation and validation are local
# and deterministic; execution is delegated to an injected `AnalysisPipeline`.
class AnswerQuestionHandler(ProcessUserRequestPort):
    """Conduz o `AnalysisRequest` de um turno do recebimento à resposta."""

    def __init__(
        self,
        llm: LlmPort,
        prompt: InterpretationPromptPort,
        reference_date: ReferenceDatePort,
        catalog: SemanticCatalogPort,
        auth_capacity: AuthCapacityPort,
        pipeline: AnalysisPipeline | None = None,
        repository: AnalysisRequestRepository | None = None,
        publisher: EventPublisher | None = None,
    ):

        self._llm = llm
        self._prompt = prompt
        self._reference_date = reference_date
        self._catalog = catalog
        self._auth_capacity = auth_capacity
        self._pipeline = pipeline
        self._repository = repository
        self._publisher = publisher or EventDispatcher()

    async def execute(
        self,
        user: User,
        context: ConversationContext,
        request: str,
    ) -> list[Content]:

        return await self.handle(
            AnswerQuestionCommand(user=user, context=context, request=request)
        )

    async def handle(self, command: AnswerQuestionCommand) -> list[Content]:

        # O guardrail decide antes de qualquer chamada ao modelo: recusa por
        # código tipificado (o texto nunca vai ao log) ou redige os dados
        # pessoais; só o texto redigido segue para o planner e para o agregado.
        verdict = guard_input(command.request)

        analysis = AnalysisRequest(
            trace_id=command.context.trace_id or uuid4().hex,
            session_id=command.context.session_id,
            user_id=command.user.id,
            question=verdict.text,
        )

        contents = await self._answer_guarded(analysis, command, verdict)

        if self._repository is not None:
            self._repository.save(analysis)

        self._publisher.publish(analysis.pull_events())

        return contents

    async def _answer_guarded(
        self,
        analysis: AnalysisRequest,
        command: AnswerQuestionCommand,
        verdict: GuardVerdict,
    ) -> list[Content]:

        if verdict.action is GuardAction.REFUSE:
            analysis.refuse(RefusalReason.INPUT_POLICY)

            logger.warning(
                "Request refused by input policy",
                refusal_reason=RefusalReason.INPUT_POLICY,
                policy=verdict.reason,
            )
            return [Text(text=_input_refusal(verdict))]

        contents = await self._interpret(analysis, command.user, command.context)

        if verdict.action is GuardAction.REDACT:
            logger.info(
                "Request redacted before the planner", kinds=sorted(verdict.kinds)
            )
            return [Text(text=_redaction_notice(verdict)), *contents]

        return contents

    async def _interpret(
        self,
        analysis: AnalysisRequest,
        user: User,
        context: ConversationContext,
    ) -> list[Content]:
        """Interpreta a pergunta já liberada pelo guardrail e produz a resposta."""

        reference_date = self._reference_date.latest_reference_date()
        system_prompt = self._prompt.build_system_prompt(context.locale, reference_date)
        messages = [LlmMessage(role="system", content=system_prompt)]
        messages.extend(_context_messages(context.messages))
        messages.append(LlmMessage(role="user", content=analysis.question))

        started = time.perf_counter()

        # Uma falha de schema no primeiro passo ganha um retry em `_propose`;
        # no retry semântico o orçamento já acabou. Nos dois casos o usuário
        # recebe um pedido de reformulação.
        try:
            proposal = await self._propose(messages, context.session_id)
            analysis.propose(proposal.route, proposal.analysis, proposal.calculations)

            if proposal.route is InterpretationRoute.ANALYTICAL:
                proposal = await self._validated_or_retried(
                    analysis, proposal, user, context, messages
                )

            if proposal.route is InterpretationRoute.CLARIFY:
                proposal = self._authorize_clarification(proposal, user)
        except StructuredOutputError as error:
            analysis.ask_clarification(_SCHEMA_CLARIFICATION)

            logger.warning(
                "Planner output never matched the schema; asking to rephrase",
                attempts=error.attempts,
            )
            return [Text(text=sanitize_user_text(_SCHEMA_CLARIFICATION))]

        _settle_route(analysis, proposal)

        interpretation_ms = (time.perf_counter() - started) * 1000

        logger.info(
            "Request interpreted",
            route=proposal.route,
            calculations=len(proposal.calculations),
            interpretation_ms=round(interpretation_ms, 1),
            history_messages=len(messages) - 2,
            statistical_methods=(
                len(proposal.analysis.statistical_method)
                if proposal.analysis is not None
                else 0
            ),
        )

        if self._pipeline is not None:
            return await self._answer(analysis, proposal, context)

        return [Structured(data=proposal.model_dump(mode="json"))]

    async def _propose(
        self,
        messages: list[LlmMessage],
        session_id: str | None,
    ) -> InterpretationProposal:
        """Pede a proposta; falha de schema ganha um retry com nota, e só um."""

        try:
            return await self._llm.generate_structured(
                messages,
                InterpretationProposal,
                session_id=session_id,
                step=_PLANNER_STEP,
            )
        except StructuredOutputError as error:
            logger.warning(
                "Planner output failed the schema; retrying once",
                attempts=error.attempts,
            )
            detail = error.detail

        retry_messages = [
            *messages,
            LlmMessage(role="user", content=_SCHEMA_RETRY_NOTE.format(detail=detail)),
        ]

        try:
            return await self._llm.generate_structured(
                retry_messages,
                InterpretationProposal,
                session_id=session_id,
                step=_PLANNER_STEP,
            )
        except StructuredOutputError as final:
            raise StructuredOutputError(
                attempts=final.attempts + 1, detail=final.detail
            ) from final

    async def _answer(
        self,
        analysis: AnalysisRequest,
        proposal: InterpretationProposal,
        context: ConversationContext,
    ) -> list[Content]:
        """Produz a resposta ao usuário para cada rota interpretada."""

        if proposal.route is InterpretationRoute.CLARIFY:
            return [
                Text(text=sanitize_user_text(proposal.clarification_question or ""))
            ]

        if proposal.route is InterpretationRoute.REFUSE:
            detail = proposal.refusal_message or str(proposal.refusal_reason)
            return [Text(text=sanitize_user_text(detail))]

        # Escopo/capacidade: texto determinístico do catálogo, sem plano nem
        # gate de lastro.
        if proposal.route is InterpretationRoute.CAPABILITY:
            capabilities = describe_capabilities(self._catalog.load_active())
            return [Text(text=sanitize_user_text(capabilities))]

        if proposal.route is InterpretationRoute.DOCUMENTAL:
            answer = await self._pipeline.documental(
                question=analysis.question, locale=context.locale
            )
            return [Text(text=sanitize_user_text(answer))]

        if proposal.analysis is None:
            return [Text(text="Não consegui montar um plano executável.")]

        return await self._answer_analytical(analysis, proposal, context)

    async def _answer_analytical(
        self,
        analysis: AnalysisRequest,
        proposal: InterpretationProposal,
        context: ConversationContext,
    ) -> list[Content]:
        """Executa o pacote selado e monta a resposta analítica."""

        catalog = self._catalog.load_active()

        # O pacote SELADO é o que executa e o que renderiza: a apresentação
        # incompatível já foi degradada para `table` no `validate_plan`.
        validated = analysis.validated
        plan = validated.analysis_plan if validated is not None else proposal.analysis
        calculations = (
            validated.calculations if validated is not None else proposal.calculations
        )

        try:
            outcome = await self._pipeline.run(
                question=analysis.question,
                locale=context.locale,
                session_id=context.session_id,
                analysis_plan=plan,
                calculations=calculations,
                catalog=catalog,
                assumptions=proposal.assumptions,
                trace_id=analysis.trace_id,
            )
        except (CalculationError, AnalysisExecutionError) as error:
            logger.warning("Analysis execution failed", error=str(error))
            return [Text(text=_EXECUTION_FAILED.format(detail=error))]

        analysis.complete(outcome.result)
        analysis.explain(
            outcome.insight,
            outcome.verified_table,
            grounded=outcome.grounded,
            attempts=outcome.insight_attempts,
        )

        # O rodapé de procedência e a nota "Como calculei" são blocos próprios,
        # fora do texto do insight: a sanitização e o gate de lastro validam só o
        # texto do redator. Dataframe/Plotly são determinísticos.
        return [
            Text(text=sanitize_user_text(outcome.insight)),
            Text(text=provenance_footer(outcome.result)),
            MethodNote(
                title=METHOD_NOTE_TITLE,
                text=describe_method(plan, calculations, outcome.result, catalog),
            ),
            *outcome.contents,
        ]

    async def _validated_or_retried(
        self,
        analysis: AnalysisRequest,
        proposal: InterpretationProposal,
        user: User,
        context: ConversationContext,
        messages: list[LlmMessage],
    ) -> InterpretationProposal:
        """Valida o pacote; recusa o LLM uma vez; sem correção, recusa tipificada."""

        catalog = self._catalog.load_active()
        capabilities = self._auth_capacity.capabilities_for(user)

        try:
            analysis.approve(_validate(proposal, catalog, capabilities))
            return proposal
        except PlanValidationError as error:
            analysis.reject(error.reason, str(error))

            logger.warning(
                "Plan rejected; retrying once",
                reason=error.reason,
                error=str(error),
            )
            reason, message = error.reason, str(error)

        retry_messages = [
            *messages,
            LlmMessage(role="assistant", content=proposal.model_dump_json()),
            LlmMessage(role="user", content=_retry_instruction(reason, message)),
        ]

        retry = await self._llm.generate_structured(
            retry_messages,
            InterpretationProposal,
            session_id=context.session_id,
            step=_PLANNER_STEP,
        )
        analysis.propose(retry.route, retry.analysis, retry.calculations)

        if retry.route is not InterpretationRoute.ANALYTICAL:
            return retry

        try:
            analysis.approve(_validate(retry, catalog, capabilities))
            return retry
        except PlanValidationError as final:
            analysis.reject(final.reason, str(final))

            logger.warning(
                "Plan rejected again; refusing",
                reason=final.reason,
                error=str(final),
            )
            return _refusal(final, retry)

    def _authorize_clarification(
        self,
        proposal: InterpretationProposal,
        user: User,
    ) -> InterpretationProposal:
        """Nega antes de esclarecer o que o usuário não pode ver.

        Na rota `clarify` não há plano para `validate_plan`; a autorização é
        decidida sobre os termos já resolvidos em `resolved_terms`.
        """

        catalog = self._catalog.load_active()
        capabilities = self._auth_capacity.capabilities_for(user)

        denial = _denied_term(proposal, catalog, capabilities)

        if denial is None:
            return proposal

        logger.warning("Clarification denied by authorization", reason=denial)

        return _refusal(
            PlanValidationError(RefusalReason.UNAUTHORIZED, denial),
            proposal,
        )


def _settle_route(
    analysis: AnalysisRequest,
    proposal: InterpretationProposal,
) -> None:
    """Fecha o agregado na rota final: recusa tipificada ou esclarecimento."""

    if proposal.route is InterpretationRoute.REFUSE:
        analysis.refuse(proposal.refusal_reason or RefusalReason.OUT_OF_SCOPE)

    elif proposal.route is InterpretationRoute.CLARIFY:
        analysis.ask_clarification(proposal.clarification_question or "")


def _denied_term(
    proposal: InterpretationProposal,
    catalog: SemanticCatalog,
    capabilities: UserCapabilities,
) -> str | None:
    """Mensagem de recusa se o que foi pedido exigir acesso que o usuário não tem."""

    if not capabilities.can_use_financial_analysis:
        return "Seu perfil não tem acesso à análise financeira."

    for term in proposal.resolved_terms:
        canonical = term.canonical

        if catalog.metric(canonical) is not None:
            if not capabilities.allows_metric(canonical):
                return f"Seu perfil não tem acesso à métrica '{term.term}'."

            continue

        axis = _axis_key(canonical)

        if axis is None:
            continue

        axis_type, level = axis

        if catalog.axis(axis_type, level) is not None and not capabilities.allows_axis(
            axis_type, level
        ):
            return f"Seu perfil não tem acesso à quebra '{term.term}'."

    return None


def _axis_key(canonical: str) -> tuple[str, str] | None:

    token = canonical.split("=", 1)[0].strip()

    if "." not in token:
        return None

    axis_type, _, level = token.partition(".")

    return axis_type, level


def _validate(
    proposal: InterpretationProposal,
    catalog: SemanticCatalog,
    capabilities: UserCapabilities,
) -> ValidatedPlan:

    if proposal.analysis is None:
        raise PlanValidationError(
            RefusalReason.NOT_EXPRESSIBLE,
            "a rota analytical exige um AnalysisPlan.",
        )

    return validate_plan(
        proposal.analysis, proposal.calculations, catalog, capabilities
    )


def _retry_instruction(reason: RefusalReason, message: str) -> str:

    return (
        "A validação determinística recusou o plano anterior. "
        f"Motivo: {reason}. Detalhe: {message}. "
        "Proponha de novo corrigindo o problema, usando apenas ids e valores do "
        "catálogo. Se a pergunta não for expressável, use a rota adequada "
        "(clarify ou refuse)."
    )


def _refusal(
    error: PlanValidationError,
    proposal: InterpretationProposal,
) -> InterpretationProposal:

    return InterpretationProposal(
        route=InterpretationRoute.REFUSE,
        refusal_reason=error.reason,
        refusal_message=str(error),
        assumptions=proposal.assumptions,
        resolved_terms=proposal.resolved_terms,
    )


def _input_refusal(verdict: GuardVerdict) -> str:
    """Mensagem fixa ao usuário para o código de recusa do guardrail."""

    reason = verdict.reason or PROMPT_INJECTION

    return sanitize_user_text(_INPUT_REFUSALS[reason])


def _redaction_notice(verdict: GuardVerdict) -> str:

    kinds = ", ".join(_KIND_LABELS.get(kind, kind) for kind in sorted(verdict.kinds))

    return _REDACTION_NOTICE.format(kinds=kinds)


def _context_messages(
    history: list[tuple[MessageRole, list[Content]]],
) -> list[LlmMessage]:

    messages: list[LlmMessage] = []

    # O rodapé de procedência é metadado do turno e fica fora do histórico
    # enviado ao planner.
    for role, contents in _without_refused_turns(history)[-_MAX_HISTORY_MESSAGES:]:
        text = "\n\n".join(
            content.text
            for content in contents
            if isinstance(content, Text) and not is_provenance_footer(content.text)
        )

        if not text:
            continue

        messages.append(
            LlmMessage(role=_ROLE_MESSAGES[role], content=text[:_MAX_MESSAGE_CHARS])
        )

    return messages


def _without_refused_turns(
    history: list[tuple[MessageRole, list[Content]]],
) -> list[tuple[MessageRole, list[Content]]]:
    """Remove os pares pergunta/recusa do guardrail de entrada.

    O texto barrado antes do LLM (SQL, injeção, campo físico, mensagem longa)
    não pode voltar ao planner disfarçado de histórico no turno seguinte.
    """

    refusals = {sanitize_user_text(text) for text in _INPUT_REFUSALS.values()}
    kept: list[tuple[MessageRole, list[Content]]] = []

    for role, contents in history:
        refused = role == MessageRole.ASSISTANT and any(
            isinstance(content, Text) and content.text in refusals
            for content in contents
        )

        if refused and kept and kept[-1][0] == MessageRole.USER:
            kept.pop()
            continue

        if refused:
            continue

        kept.append((role, contents))

    return kept
