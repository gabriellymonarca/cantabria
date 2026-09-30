"""Schema estruturado que o planner (LLM) preenche: a `InterpretationProposal`.

É o contrato de aplicação com o modelo: pydantic vive aqui para
gerar o JSON Schema da ferramenta e validar a resposta. Os tipos de plano são
os value objects do domínio — um plano malformado (janela invertida, quebra
repetida, referência órfã) falha na validação do schema e nem chega a existir.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    WithJsonSchema,
    model_validator,
)

from contexts.financial_analysis.domain.analysis_plan import (
    AnalysisPlan,
    safe_presentation,
)
from contexts.financial_analysis.domain.interpretation import (
    InterpretationRoute,
    RefusalReason,
)
from contexts.financial_calculation.ports.inbound.execute_calculations_port import (
    CalculationPlan,
)

# `input_policy` é reservado ao guardrail de entrada (código, não modelo): fica
# fora do schema que o LLM vê e é falha de schema se ele o emitir mesmo assim.
_LLM_REFUSAL_REASONS = tuple(
    reason for reason in RefusalReason if reason is not RefusalReason.INPUT_POLICY
)


def _llm_refusal_reason(reason: RefusalReason) -> RefusalReason:

    if reason is RefusalReason.INPUT_POLICY:
        raise ValueError(
            "refusal_reason 'input_policy' é reservado ao guardrail de entrada."
        )

    return reason


LlmRefusalReason = Annotated[
    RefusalReason,
    AfterValidator(_llm_refusal_reason),
    WithJsonSchema(
        {"type": "string", "enum": [reason.value for reason in _LLM_REFUSAL_REASONS]}
    ),
]


class ResolvedTerm(BaseModel):
    """A user term and the governed id it resolved to."""

    term: str
    canonical: str


def _presentation_payload(raw: object) -> dict[str, str]:
    """Payload de apresentação que o domínio aceita: inválido vira `table`."""

    fields = raw if isinstance(raw, dict) else {}

    presentation = safe_presentation(
        presentation_type=fields.get("type"),
        axis=fields.get("axis"),
        title=fields.get("title"),
    )

    return {
        "type": presentation.type.value,
        "axis": presentation.axis.value,
        "title": presentation.title,
    }


class InterpretationProposal(BaseModel):
    """Rota da interpretação e o que ela exige.

    `analytical` carrega o AnalysisPlan e os CalculationPlan; `documental` e
    `capability` não carregam nada; `clarify` carrega a pergunta de volta;
    `refuse` carrega o motivo tipificado. Os campos são planos (sem união
    discriminada) porque o output estruturado do provedor é feito por tool
    calling.
    """

    route: InterpretationRoute = Field(
        description=(
            "O que a pergunta exige: analytical, documental, capability, "
            "clarify ou refuse."
        )
    )
    analysis: AnalysisPlan | None = Field(
        default=None, description="Preenchido apenas na rota analytical."
    )
    calculations: list[CalculationPlan] = Field(
        default_factory=list,
        description="Um plano por métrica e janela; só na rota analytical.",
    )
    clarification_question: str | None = Field(
        default=None, description="Pergunta ao usuário; só na rota clarify."
    )
    refusal_reason: LlmRefusalReason | None = Field(
        default=None, description="Motivo tipificado; só na rota refuse."
    )
    refusal_message: str | None = Field(
        default=None, description="Explicação ao usuário; só na rota refuse."
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Defaults aplicados (declarados no catálogo), para eco ao usuário.",
    )
    resolved_terms: list[ResolvedTerm] = Field(
        default_factory=list,
        description="Termos do usuário e o id canônico em que resolveram.",
    )

    @model_validator(mode="before")
    @classmethod
    def _degrade_invalid_presentation(cls, data: object) -> object:
        """Apresentação inválida degrada para `table`.

        O campo é cosmético; o valor que chega ao domínio é sempre um membro do
        catálogo fechado (ou `None`, quando o modelo não propôs nada).
        """

        if not isinstance(data, dict):
            return data

        analysis = data.get("analysis")

        if not isinstance(analysis, dict) or analysis.get("presentation") is None:
            return data

        sanitized = dict(analysis)
        sanitized["presentation"] = _presentation_payload(analysis["presentation"])

        return {**data, "analysis": sanitized}

    @model_validator(mode="after")
    def _check_route(self) -> InterpretationProposal:

        has_plans = self.analysis is not None or bool(self.calculations)

        if self.route is InterpretationRoute.ANALYTICAL:
            if self.analysis is None or not self.calculations:
                raise ValueError(
                    "route 'analytical' exige analysis e calculations não vazios."
                )

            return self

        if has_plans:
            raise ValueError(
                f"route '{self.route}' não pode carregar analysis nem calculations."
            )

        # `capability` não carrega campo próprio: a resposta é gerada do
        # catálogo, como `documental` responde pela base aprovada.
        if self.route is InterpretationRoute.CAPABILITY:
            return self

        if self.route is InterpretationRoute.CLARIFY:
            if not self.clarification_question:
                raise ValueError("route 'clarify' exige clarification_question.")

            return self

        if self.route is InterpretationRoute.REFUSE and self.refusal_reason is None:
            raise ValueError("route 'refuse' exige refusal_reason.")

        return self
