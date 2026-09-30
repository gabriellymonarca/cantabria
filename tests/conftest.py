"""Configuração comum dos testes: coloca `src/` no path de import."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT):
    text = str(candidate)
    if text not in sys.path:
        sys.path.insert(0, text)

# Módulos excluídos da coleta.
collect_ignore = ["test_create_plan.py"]
