"""CLI do harness: `python -m eval --layer ... --split dev --report reports/`.

Offline por padrão: `engine` e `redteam` rodam de ponta a ponta sem rede; as
camadas generativas e o controle `baseline` só rodam com `--live` explícito (e
exigem config válido). O relatório sai em Markdown e JSON (mais
`baseline-<split>.md` quando o controle rodou); a execução devolve exit code 1
se houver falha.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from eval.baseline import render_baseline_table, run_baseline_layer
from eval.dataset import EvalDataset, load_dataset
from eval.engine import run_engine_layer
from eval.fixture_repository import fixture_path
from eval.live import LiveUnavailableError
from eval.llm_layers import LLM_LAYERS, run_llm_layer
from eval.redteam import redteam_path, run_redteam_layer
from eval.report import LayerOutcome, RunReport, git_commit, write_report

LAYERS = (
    "planner",
    "routing",
    "engine",
    "explanation",
    "e2e",
    "redteam",
    "baseline",
    "all",
)
_DETERMINISTIC_LAYERS = ("engine", "redteam")
_BASELINE_LAYER = "baseline"


def main(argv: list[str] | None = None) -> int:

    parser = argparse.ArgumentParser(
        prog="python -m eval",
        description=(
            "Harness de avaliação do Cantábria. Offline por padrão: engine e "
            "redteam rodam sem rede; planner/routing/explanation/e2e e o "
            "controle baseline exigem --live e o LlmPort configurado."
        ),
    )
    parser.add_argument("--layer", choices=LAYERS, default="all")
    parser.add_argument("--split", default="dev")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="diretório (ex.: reports/) ou arquivo .md do relatório",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="caminho do YAML do split (default: data/eval/<split>.yaml)",
    )
    parser.add_argument("--oracle", type=Path, default=None)
    parser.add_argument(
        "--live",
        action="store_true",
        help="habilita as camadas generativas com o LlmPort configurado",
    )
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args(argv)

    dataset_path = args.dataset or _dataset_path(args.split)

    if not dataset_path.is_file():
        print(
            f"erro: dataset '{dataset_path}' não encontrado "
            f"(split '{args.split}') — o split `test` exige aprovação humana.",
            file=sys.stderr,
        )
        return 2

    dataset = load_dataset(dataset_path)
    catalog_adapter = YamlSemanticCatalogAdapter()
    catalog = catalog_adapter.load_active()
    oracle_path = args.oracle or fixture_path()

    layers = _expand(args.layer)
    outcomes: list[LayerOutcome] = []

    for layer in layers:
        if layer == "engine":
            outcomes.append(run_engine_layer(dataset, oracle_path))
        elif layer == "redteam":
            outcomes.append(
                run_redteam_layer(catalog, catalog.catalog_version, redteam_path())
            )
        else:
            try:
                outcomes.append(
                    _run_live_layer(
                        layer,
                        dataset,
                        oracle_path,
                        live=args.live,
                        config_path=args.config,
                    )
                )
            except LiveUnavailableError as error:
                print(f"erro: {error}", file=sys.stderr)

                return 2

    report = RunReport(
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        split=dataset.split,
        live=bool(args.live),
        dataset_path=str(dataset_path),
        catalog_version=catalog.catalog_version,
        oracle_path=str(oracle_path),
        commit=git_commit(),
        layers=tuple(outcomes),
    )

    _print_summary(report)

    if args.report is not None:
        md_path, json_path = write_report(report, args.report)

        print(f"relatório: {md_path}")
        print(f"json:      {json_path}")

        baseline_path = _write_baseline_table(report, dataset, md_path.parent)

        if baseline_path is not None:
            print(f"baseline:  {baseline_path}")

    return 1 if report.failed else 0


def _run_live_layer(
    layer: str,
    dataset: EvalDataset,
    oracle_path: Path,
    *,
    live: bool,
    config_path: str,
) -> LayerOutcome:

    if layer == _BASELINE_LAYER:
        return run_baseline_layer(
            dataset, oracle_path, live=live, config_path=config_path
        )

    return run_llm_layer(layer, dataset, live=live, config_path=config_path)


def _write_baseline_table(
    report: RunReport, dataset: EvalDataset, directory: Path
) -> Path | None:
    """Grava `baseline-<split>.md` só quando o controle rodou live."""

    if not report.live:
        return None

    for layer in report.layers:
        if layer.layer == _BASELINE_LAYER:
            path = directory / f"baseline-{report.split}.md"

            path.write_text(render_baseline_table(layer, dataset), encoding="utf-8")

            return path

    return None


def _dataset_path(split: str) -> Path:

    from cross_cutting.resources import find_repo_root

    root = find_repo_root()

    return (root or Path.cwd()) / "data" / "eval" / f"{split}.yaml"


def _expand(layer: str) -> tuple[str, ...]:

    if layer == "all":
        return (*_DETERMINISTIC_LAYERS, *LLM_LAYERS, _BASELINE_LAYER)

    return (layer,)


def _print_summary(report: RunReport) -> None:

    print(
        f"eval — split {report.split} · modo "
        f"{'live' if report.live else 'offline'} · catálogo "
        f"{report.catalog_version}"
    )

    for layer in report.layers:
        counts = layer.counts
        state = "ok" if layer.ok else "FALHOU"

        print(
            f"  {layer.layer:<12} pass={counts['pass']:<3} fail={counts['fail']:<3} "
            f"skip={counts['skip']:<3} {state}"
        )

    if report.ok:
        print("resultado: sem falhas.")
    else:
        print(f"resultado: {len(report.failed)} falha(s).")

        for layer_name, outcome in report.failed:
            print(f"  [{layer_name}] {outcome.case_id}: {outcome.detail}")


if __name__ == "__main__":
    raise SystemExit(main())
