#!/usr/bin/env bash
# Renders the Langfuse stack secrets from infrastructure/.env and starts the
# `observability` profile of the root compose.yaml.
#
#   cp infrastructure/.env.example infrastructure/.env  # fill in the values
#   ./scripts/langfuse_up.sh
#
# Run from anywhere inside the repository checkout on the Docker host, outside
# the devcontainer, so the compose bind mounts resolve to paths the daemon
# can see. Rendered secret files are gitignored; only *.example is committed.
# The root .env must exist too: compose interpolates the whole file, and the
# `core` services require the CLICKHOUSE_* passwords even when not started.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA="$ROOT/infrastructure"
ENV_FILE="$INFRA/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE." >&2
  echo "Copy the template and fill in the values:" >&2
  echo "  cp infrastructure/.env.example infrastructure/.env" >&2
  exit 1
fi

TEMPLATES=(
  "docker/langfuse/common.env"
  "docker/langfuse/web.env"
  "docker/postgres/password.txt"
  "docker/minio/root_user"
  "docker/minio/root_password"
  "docker/redis/redis.conf"
  "docker/clickhouse/users.d/01-langfuse-user.xml"
)

python3 - "$ENV_FILE" "${TEMPLATES[@]}" <<'EOF'
import re
import sys
from pathlib import Path

infra = Path(sys.argv[1]).parent
env_file = Path(sys.argv[1])
values: dict[str, str] = {}

for line in env_file.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    values[key.strip()] = value.strip().strip("\"'")

pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def render(template: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        if name in values and values[name]:
            return values[name]
        if default is not None:
            return default
        raise SystemExit(f"error: {name} is empty in {env_file}")

    return pattern.sub(replace, template)


for name in sys.argv[2:]:
    source = infra / f"{name}.example"
    target = infra / name
    target.write_text(render(source.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"rendered {target.relative_to(infra.parent)}")
EOF

if [[ ! -f "$ROOT/.env" ]]; then
  echo "Missing $ROOT/.env (compose interpolates it): cp .env.example .env" >&2
  exit 1
fi

cd "$ROOT"
docker compose --profile observability up -d
