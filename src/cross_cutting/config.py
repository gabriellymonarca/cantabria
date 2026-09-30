from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from cross_cutting.resources import resolve_data_dir


class ConfigError(Exception):
    """Raised when the application configuration is missing or invalid."""


# Versão padrão de cada contrato de prompt (`data/prompts/<purpose>/vN/`).
# Mudar um prompt é criar um novo diretório e apontar aqui; a versão efetiva
# pode ser sobreposta por `*_prompts_dir` no config.yaml ou por ambiente.
_INTERPRETATION_PROMPT_VERSION = "v1"
_INSIGHT_PROMPT_VERSION = "v3"
_DOCUMENTAL_PROMPT_VERSION = "v1"


class LlmConfig(BaseModel):
    """Settings of the OpenAI-compatible language model endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    base_url: str
    api_key: str
    temperature: float
    timeout: float
    headers: dict[str, str]
    session_header: str


class EmbeddingsConfig(BaseModel):
    """Settings of the OpenAI-compatible embedding endpoint (semantic RAG)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    base_url: str | None = None
    api_key: str | None = None


class AuthConfig(BaseModel):
    """Settings of the auth context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_domains: list[str]
    local_login_enabled: bool = False
    users_file: str = "data/auth/users.yaml"
    role_map: dict[str, list[str]] = {}
    default_roles: list[str] = []


class LoggingConfig(BaseModel):
    """Settings of the console logging."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    level: str


class ObservabilityConfig(BaseModel):
    """Settings of the Langfuse tracing integration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool
    host: str
    public_key: str
    secret_key: str
    environment: str
    release: str

    @model_validator(mode="after")
    def _require_credentials_when_enabled(self) -> ObservabilityConfig:

        if not self.enabled:
            return self

        missing = [
            field
            for field in ("host", "public_key", "secret_key")
            if not getattr(self, field).strip()
        ]

        if missing:
            raise ValueError(
                "observability.enabled is true but "
                f"{', '.join(missing)} is empty; "
                "see infrastructure/.env.example and config.example.yaml."
            )

        return self


class DataConfig(BaseModel):
    """Location of the governed data files.

    Every field is optional: `None` resolves to the default derived from
    the data dir. Relative paths resolve against the config file directory.
    Environment variables override the file, one field at a time.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    data_dir: Path | None = None
    catalogs_dir: Path | None = None
    interpretation_prompts_dir: Path | None = None
    insight_prompts_dir: Path | None = None
    documental_prompts_dir: Path | None = None
    capabilities_file: Path | None = None

    def resolved_data_dir(self) -> Path:

        if self.data_dir is not None:
            return self.data_dir

        return resolve_data_dir()

    def resolved_catalogs_dir(self) -> Path:

        if self.catalogs_dir is not None:
            return self.catalogs_dir

        return self.resolved_data_dir() / "catalogs"

    def resolved_interpretation_prompts_dir(self) -> Path:

        if self.interpretation_prompts_dir is not None:
            return self.interpretation_prompts_dir

        return (
            self.resolved_data_dir()
            / "prompts"
            / "interpretation"
            / _INTERPRETATION_PROMPT_VERSION
        )

    def resolved_insight_prompts_dir(self) -> Path:

        if self.insight_prompts_dir is not None:
            return self.insight_prompts_dir

        return (
            self.resolved_data_dir() / "prompts" / "insight" / _INSIGHT_PROMPT_VERSION
        )

    def resolved_documental_prompts_dir(self) -> Path:

        if self.documental_prompts_dir is not None:
            return self.documental_prompts_dir

        return (
            self.resolved_data_dir()
            / "prompts"
            / "documental"
            / _DOCUMENTAL_PROMPT_VERSION
        )

    def resolved_capabilities_file(self) -> Path:

        if self.capabilities_file is not None:
            return self.capabilities_file

        return self.resolved_data_dir() / "auth" / "capabilities.yaml"

    def resolved_prompts_dirs(self) -> dict[str, Path]:
        """Diretório efetivo de cada contrato de prompt; o nome é a versão."""

        return {
            "interpretation": self.resolved_interpretation_prompts_dir(),
            "insight": self.resolved_insight_prompts_dir(),
            "documental": self.resolved_documental_prompts_dir(),
        }


class AppConfig(BaseModel):
    """The whole application configuration, loaded from config.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    llm: LlmConfig
    embeddings: EmbeddingsConfig | None = None
    auth: AuthConfig
    logging: LoggingConfig
    observability: ObservabilityConfig
    data: DataConfig = DataConfig()

    def resolved_embeddings(self) -> EmbeddingsConfig | None:
        """Embeddings com endpoint/chave herdados do `llm` quando ausentes.

        Sem a seção `embeddings` o RAG semântico fica desligado e a busca
        lexical (BM25) assume — a demo continua offline.
        """

        if self.embeddings is None:
            return None

        return EmbeddingsConfig(
            model=self.embeddings.model,
            base_url=self.embeddings.base_url or self.llm.base_url,
            api_key=self.embeddings.api_key or self.llm.api_key,
        )


_DATA_ENV_OVERRIDES = (
    ("data_dir", "CANTABRIA_DATA_DIR"),
    ("catalogs_dir", "CANTABRIA_CATALOGS_DIR"),
    ("interpretation_prompts_dir", "CANTABRIA_INTERPRETATION_PROMPTS_DIR"),
    ("insight_prompts_dir", "CANTABRIA_INSIGHT_PROMPTS_DIR"),
    ("documental_prompts_dir", "CANTABRIA_DOCUMENTAL_PROMPTS_DIR"),
    ("capabilities_file", "CANTABRIA_CAPABILITIES_FILE"),
)


def _resolve_data_path(value: str | Path, base: Path) -> Path:

    expanded = Path(os.path.expandvars(str(value))).expanduser()

    if expanded.is_absolute():
        return expanded

    return base / expanded


def load_config(path: str | Path = "config.yaml") -> AppConfig:

    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"Configuration file not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"Configuration must be a YAML mapping: {config_path}")

    data = dict(raw.get("data") or {})
    base = config_path.resolve().parent

    for field, env in _DATA_ENV_OVERRIDES:
        if os.environ.get(env):
            data[field] = os.environ[env]

    for field, value in list(data.items()):
        if value is not None:
            data[field] = str(_resolve_data_path(value, base))

    raw = {**raw, "data": data}

    try:
        return AppConfig.model_validate(raw)
    except ValidationError as error:
        raise ConfigError(
            f"Invalid configuration in {config_path}:\n{error}"
        ) from error
