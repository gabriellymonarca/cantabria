"""Resultado das camadas e relatório (Markdown legível + JSON máquina).

O relatório é o artefato da avaliação: resumo por camada (pass/fail/skip),
falhas com o id do caso e a reprodução. O JSON ao lado é o mesmo conteúdo em
forma estável para comparação entre execuções (baseline, v1 → v2).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

Status = Literal["pass", "fail", "skip"]

_STATUS_LABEL = {"pass": "pass", "fail": "fail", "skip": "skip"}


@dataclass(frozen=True)
class CaseOutcome:
    """O veredito de um caso (ou de uma sonda do redteam) numa camada."""

    case_id: str
    status: Status
    detail: str = ""


@dataclass(frozen=True)
class LayerOutcome:
    """O resultado de uma camada: casos avaliados e casos não avaliados."""

    layer: str
    summary: str
    outcomes: tuple[CaseOutcome, ...] = ()
    total_cases: int = 0
    skipped_cases: int = 0

    @property
    def failed(self) -> tuple[CaseOutcome, ...]:

        return tuple(item for item in self.outcomes if item.status == "fail")

    @property
    def counts(self) -> dict[str, int]:
        """pass/fail/skip, somando os skips implícitos (camada inteira pulada)."""

        counts = {"pass": 0, "fail": 0, "skip": self.skipped_cases}

        for outcome in self.outcomes:
            counts[outcome.status] += 1

        return counts

    @property
    def ok(self) -> bool:

        return not self.failed


@dataclass(frozen=True)
class RunReport:
    """Uma execução do harness: metadados, camadas e veredito global."""

    generated_at: str
    split: str
    live: bool
    dataset_path: str
    catalog_version: str
    oracle_path: str
    commit: str
    layers: tuple[LayerOutcome, ...]

    @property
    def failed(self) -> tuple[tuple[str, CaseOutcome], ...]:

        return tuple(
            (layer.layer, outcome) for layer in self.layers for outcome in layer.failed
        )

    @property
    def ok(self) -> bool:

        return not self.failed


def git_commit(root: Path | None = None) -> str:

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "desconhecido"

    return completed.stdout.strip() or "desconhecido"


def write_report(report: RunReport, target: Path) -> tuple[Path, Path]:
    """Escreve o `.md` e o `.json`; `target` pode ser diretório ou arquivo `.md`."""

    md_path = target if target.suffix == ".md" else target / f"eval-{report.split}.md"
    json_path = md_path.with_suffix(".json")

    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return md_path, json_path


def render_markdown(report: RunReport) -> str:

    mode = "live (LLM)" if report.live else "offline (sem rede, sem LLM)"
    lines = [
        "# Relatório de avaliação — Cantábria",
        "",
        f"- **Gerado em:** {report.generated_at}",
        f"- **Split:** `{report.split}` (`{report.dataset_path}`)",
        f"- **Modo:** {mode}",
        f"- **Catálogo:** `{report.catalog_version}` · "
        f"**Oráculo:** `{report.oracle_path}`",
        f"- **Commit:** `{report.commit}`",
        "",
        "## Resumo por camada",
        "",
        "| Camada | Casos | pass | fail | skip | Resultado |",
        "|---|---|---|---|---|---|",
    ]

    for layer in report.layers:
        counts = layer.counts
        result = "✅" if layer.ok else "❌"

        lines.append(
            f"| `{layer.layer}` | {layer.total_cases} | {counts['pass']} | "
            f"{counts['fail']} | {counts['skip']} | {result} |"
        )

    overall = "✅ sem falhas" if report.ok else f"❌ {len(report.failed)} falha(s)"

    lines.extend(["", f"**Resultado:** {overall}", "", "## Falhas", ""])

    if report.ok:
        lines.append("Nenhuma falha registrada nesta execução.")
    else:
        for layer_name, outcome in report.failed:
            lines.append(f"- `{layer_name}` · `{outcome.case_id}` — {outcome.detail}")

    lines.extend(["", "## Camadas", ""])

    for layer in report.layers:
        counts = layer.counts

        lines.append(f"### `{layer.layer}` — {layer.summary}")
        lines.append("")
        lines.append(
            f"pass: {counts['pass']} · fail: {counts['fail']} · skip: {counts['skip']}"
        )
        lines.append("")
        lines.extend(_layer_details(layer))

    lines.extend(
        [
            "## Como reproduzir",
            "",
            "```bash",
            "make eval                                        "
            "# todas as camadas offline do split dev",
            "python -m eval --layer engine --split dev --report reports/",
            "python -m eval --layer redteam --split dev --report reports/",
            "python -m eval --layer all --split dev --live     "
            "# camadas generativas exigem LLM configurado",
            "python -m eval --layer baseline --split dev --live --report reports/  "
            "# controle text-to-SQL → reports/baseline-dev.md",
            "```",
            "",
            "O split `test` existe apenas no checkout autorizado e não é usado",
            "para ajuste de prompt; a baseline text-to-SQL e a comparação de",
            "modelos ficam registradas em `docs/evaluation-report.md`.",
            "",
        ]
    )

    return "\n".join(lines)


def _layer_details(layer: LayerOutcome) -> list[str]:

    if not layer.outcomes:
        if layer.skipped_cases:
            return [
                f"- {layer.skipped_cases} caso(s) não avaliados: "
                "camada pulada nesta execução.",
                "",
            ]

        return ["- (sem casos)", ""]

    lines = []

    for outcome in layer.outcomes:
        if outcome.status == "fail":
            icon = "❌"
        elif outcome.status == "skip":
            icon = "⏭️"
        else:
            icon = "✅"

        lines.append(f"- {icon} `{outcome.case_id}` — {outcome.detail}")

    lines.append("")

    return lines
