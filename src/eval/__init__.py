"""Harness de avaliação do Cantábria — offline por padrão, sem LLM.

Camadas: `engine` (motor × oráculo independente), `redteam` (guardrails de
entrada e recusas contra o catálogo real, sem LLM) e as camadas generativas
(`planner`, `routing`, `explanation`, `e2e`), que ficam `skipped (offline)` sem
`--live` e usam o `LlmPort` configurado quando explícito.

Uso: `python -m eval --layer all --split dev --report reports/`.
"""
