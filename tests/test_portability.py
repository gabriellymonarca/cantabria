"""Portabilidade: resolução de recursos, caminhos configuráveis e `.env`.

Garante que a aplicação roda fora do checkout original: o diretório de dados
é explícito (argumento > `CANTABRIA_*` > checkout), o `config.yaml` aceita
caminhos relativos e o `.env` é carregado antes da configuração.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml

from contexts.auth.adapters.outbound.yaml_capabilities import (
    YamlCapabilitiesAdapter,
)
from contexts.auth.application.queries.authorize import AuthorizeQuery
from contexts.auth.domain.user import Role, User
from contexts.financial_analysis.adapters.outbound.auth_capacity_acl import (
    AuthCapacityAcl,
)
from contexts.financial_analysis.adapters.outbound.langchain_insight import (
    LangChainInsightAdapter,
)
from contexts.financial_analysis.adapters.outbound.localized_interpretation_prompt import (
    LocalizedInterpretationPromptAdapter,
)
from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from contexts.financial_analysis.domain.analysis_result import AnalysisResult
from contexts.financial_analysis.ports.outbound.llm_port import (
    LlmMessage,
    LlmPort,
    LlmReply,
)
from cross_cutting import resources
from cross_cutting.config import load_config
from entrypoints import env as dotenv

_DATA_ENV_VARS = (
    "CANTABRIA_DATA_DIR",
    "CANTABRIA_CATALOGS_DIR",
    "CANTABRIA_INTERPRETATION_PROMPTS_DIR",
    "CANTABRIA_INSIGHT_PROMPTS_DIR",
    "CANTABRIA_DOCUMENTAL_PROMPTS_DIR",
    "CANTABRIA_CAPABILITIES_FILE",
)


@pytest.fixture(autouse=True)
def _isolated_data_env(monkeypatch):

    for var in _DATA_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _base_config() -> dict:

    return {
        "llm": {
            "model": "test-model",
            "base_url": "http://localhost:11434/v1",
            "api_key": "test",
            "temperature": 0.0,
            "timeout": 60.0,
            "headers": {"User-Agent": "cantabria-test/0.1.0"},
            "session_header": "",
        },
        "auth": {"allowed_domains": []},
        "logging": {"level": "INFO"},
        "observability": {
            "enabled": False,
            "host": "http://localhost:3000",
            "public_key": "pk",
            "secret_key": "sk",
            "environment": "test",
            "release": "",
        },
    }


def _write_config(path: Path, data: dict | None = None) -> Path:

    raw = _base_config()

    if data is not None:
        raw["data"] = data

    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    return path


def test_explicit_data_dir_wins_over_env(tmp_path, monkeypatch) -> None:

    monkeypatch.setenv("CANTABRIA_DATA_DIR", str(tmp_path / "env-data"))

    assert resources.resolve_data_dir(tmp_path / "explicit") == tmp_path / "explicit"


def test_env_data_dir_wins_over_default(tmp_path, monkeypatch) -> None:

    monkeypatch.setenv("CANTABRIA_DATA_DIR", str(tmp_path))

    assert resources.default_data_dir() == tmp_path


def test_default_data_dir_finds_checkout() -> None:

    data_dir = resources.default_data_dir()

    assert (data_dir / "catalogs" / "semantic_catalog_v3.yaml").is_file()
    assert (data_dir / "auth" / "capabilities.yaml").is_file()


def test_find_dotenv_walks_up_from_cwd(tmp_path) -> None:

    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (tmp_path / "a" / ".env").write_text("X=1\n", encoding="utf-8")

    assert dotenv.find_dotenv(start=nested) == tmp_path / "a" / ".env"


def test_load_dotenv_prefers_explicit_path(tmp_path, monkeypatch) -> None:

    monkeypatch.setenv("DOTENV_PATH", str(tmp_path / "other.env"))
    (tmp_path / "other.env").write_text("FROM_OTHER=1\n", encoding="utf-8")
    explicit = tmp_path / "explicit.env"
    explicit.write_text("FROM_EXPLICIT=1\n", encoding="utf-8")

    dotenv.load_dotenv(explicit)

    assert os.environ.get("FROM_EXPLICIT") == "1"
    assert "FROM_OTHER" not in os.environ


def test_load_dotenv_never_overrides_environment(tmp_path, monkeypatch) -> None:

    monkeypatch.setenv("KEEP", "shell")
    path = tmp_path / ".env"
    path.write_text("KEEP=dotenv\nNEW=dotenv\n", encoding="utf-8")

    dotenv.load_dotenv(path)

    assert os.environ["KEEP"] == "shell"
    assert os.environ["NEW"] == "dotenv"


def test_load_config_without_data_uses_checkout_defaults(tmp_path) -> None:

    config = load_config(_write_config(tmp_path / "config.yaml"))

    assert (config.data.resolved_catalogs_dir() / "semantic_catalog_v3.yaml").is_file()
    assert config.data.resolved_capabilities_file().is_file()
    assert config.data.resolved_insight_prompts_dir().is_dir()
    assert config.data.resolved_documental_prompts_dir().is_dir()


def test_load_config_env_overrides_file(tmp_path, monkeypatch) -> None:

    catalogs = tmp_path / "from-file"
    catalogs.mkdir()
    override = tmp_path / "from-env"
    override.mkdir()
    monkeypatch.setenv("CANTABRIA_CATALOGS_DIR", str(override))

    config = load_config(
        _write_config(tmp_path / "config.yaml", {"catalogs_dir": str(catalogs)})
    )

    assert config.data.resolved_catalogs_dir() == override


def test_load_config_relative_resolves_against_config_dir(tmp_path) -> None:

    nested = tmp_path / "conf"
    nested.mkdir()
    (nested / "rel").mkdir()

    config = load_config(_write_config(nested / "config.yaml", {"catalogs_dir": "rel"}))

    assert config.data.resolved_catalogs_dir() == nested / "rel"


def test_catalog_adapter_accepts_explicit_dir(tmp_path) -> None:

    shutil.copytree(resources.default_data_dir() / "catalogs", tmp_path / "catalogs")

    catalog = YamlSemanticCatalogAdapter(
        catalogs_dir=tmp_path / "catalogs"
    ).load_active()

    assert catalog.catalog_version == "v3"


def test_auth_capacity_accepts_explicit_file(tmp_path) -> None:

    path = tmp_path / "capabilities.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "default": {
                    "can_use_financial_analysis": True,
                    "metrics": ["profitability"],
                    "axes": [],
                }
            }
        ),
        encoding="utf-8",
    )

    user = User(
        id="u1", name="User", email="user@example.com", roles=[Role(id="x", name="X")]
    )
    capabilities = AuthCapacityAcl(
        AuthorizeQuery(YamlCapabilitiesAdapter(config_path=path))
    ).capabilities_for(user)

    assert capabilities.can_use_financial_analysis is True
    assert "profitability" in capabilities.metrics


def test_interpretation_prompt_accepts_explicit_dirs(tmp_path) -> None:

    data_dir = resources.default_data_dir()
    shutil.copytree(
        data_dir / "prompts" / "interpretation" / "v1", tmp_path / "prompts"
    )

    adapter = LocalizedInterpretationPromptAdapter(
        prompts_dir=tmp_path / "prompts",
        catalogs_dir=data_dir / "catalogs",
    )
    prompt = adapter.build_system_prompt("pt-BR")

    assert "v3" in prompt
    assert "pt-BR" in prompt


class _FakeLlm(LlmPort):
    def __init__(self):

        self.system: str | None = None

    async def generate(
        self,
        messages: Sequence[LlmMessage],
        session_id: str | None = None,
        step: str = "llm",
    ) -> LlmReply:

        self.system = next(
            message.content for message in messages if message.role == "system"
        )

        return LlmReply(text="ok", model="fake", usage=None)

    async def generate_structured(
        self,
        messages: Sequence[LlmMessage],
        schema,
        session_id: str | None = None,
        step: str = "llm",
    ):

        raise NotImplementedError


def test_insight_adapter_accepts_explicit_prompts_dir(tmp_path) -> None:

    (tmp_path / "base.md").write_text("SYSTEM", encoding="utf-8")

    llm = _FakeLlm()
    adapter = LangChainInsightAdapter(llm, prompts_dir=tmp_path)

    result = AnalysisResult(
        analysis_plan_id="a1",
        catalog_version="v2",
        dataset_version="d1",
        trace_id="t1",
    )

    assert asyncio.run(adapter.explain(question="q?", result=result)) == "ok"
    assert llm.system == "SYSTEM"
