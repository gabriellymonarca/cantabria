# infra/ e infrastructure/

Dois diretórios com nomes parecidos e papéis diferentes:

| Diretório | Conteúdo | Usado por |
|---|---|---|
| `infra/clickhouse/` | ClickHouse **do app**: DDL dos dados oficiais (`init/00_schema.sql`), usuários (`users.d/users.xml`) e configuração (`config/config.d/cantabria.xml`) | `Dockerfile`, `compose.yaml` (profile `core`), `utils/seed_clickhouse.py`, `scripts/preflight.py`, CI |
| `infrastructure/` | Stack **opcional** de observabilidade e stores: Langfuse (com seu próprio Postgres, Redis e ClickHouse) e MinIO; `.env.example` dessa stack | `compose.yaml` (profiles `observability`, `stores`), `scripts/langfuse_up.sh`, `Makefile`, `docs/como-usar.md` |

Fundir os dois em `infra/` está na lista de próximos passos do `README.md`; exige validar
`docker compose config` e `make demo` numa máquina com Docker.
