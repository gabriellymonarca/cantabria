"""Adapter outbound que recupera trechos aprovados do acervo local em disco.

O acervo vive em `data/knowledge/*.md`: um arquivo por documento ficticio,
com frontmatter YAML (document_id, title, version, status, locale) e secoes
`##`. Somente documentos com `status: approved` sao indexados. A busca e
lexical e deterministica (BM25 sobre tokens normalizados pt-BR), sem rede nem
embeddings.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from contexts.financial_analysis.ports.outbound.knowledge_port import (
    KnowledgeExcerpt,
    KnowledgePort,
)
from cross_cutting.resources import resolve_data_dir

_KNOWLEDGE_SUBDIR = Path("knowledge")
_K1 = 1.2
_B = 0.75
_MIN_SCORE = 1.6

_STOPWORDS = frozenset(
    {
        "o",
        "a",
        "os",
        "as",
        "um",
        "uma",
        "uns",
        "umas",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "no",
        "na",
        "nos",
        "nas",
        "em",
        "por",
        "para",
        "com",
        "sem",
        "que",
        "qual",
        "quais",
        "como",
        "quando",
        "onde",
        "porque",
        "se",
        "e",
        "ou",
        "mas",
        "nao",
        "sim",
        "este",
        "esta",
        "esse",
        "essa",
        "aquele",
        "aquela",
        "isto",
        "isso",
        "aquilo",
        "ele",
        "ela",
        "eles",
        "elas",
        "seu",
        "sua",
        "seus",
        "suas",
        "meu",
        "minha",
        "teu",
        "tua",
        "ha",
        "tem",
        "sao",
        "foi",
        "foram",
        "era",
        "eram",
        "sera",
        "estou",
        "estamos",
        "estao",
        "muito",
        "mais",
        "menos",
        "cada",
        "todo",
        "toda",
        "todos",
        "todas",
        "algum",
        "alguma",
        "nenhum",
        "nenhuma",
        "outro",
        "outra",
        "mesmo",
        "mesma",
        "entre",
        "sobre",
        "sob",
        "ate",
        "desde",
        "ainda",
        "tambem",
        "so",
        "apenas",
        "quanto",
        "quantos",
        "qualquer",
        "algo",
        "nada",
        "me",
        "te",
        "lhe",
        "lhes",
        "vos",
        "dessa",
        "desse",
        "desta",
        "deste",
        "num",
        "numa",
        "dum",
        "duma",
        "pelo",
        "pela",
        "pelos",
        "pelas",
        "ser",
        "ter",
        "saber",
        "fazer",
        "dizer",
    }
)

_HEADING = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class _IndexedExcerpt:
    document_id: str
    title: str
    section: str
    text: str
    version: str | None
    tokens: tuple[str, ...]


class LocalKnowledgeAdapter(KnowledgePort):
    """Recupera trechos aprovados do acervo local com BM25 deterministico."""

    def __init__(self, knowledge_dir: Path | None = None):

        data_dir = resolve_data_dir()
        self._knowledge_dir = knowledge_dir or (data_dir / _KNOWLEDGE_SUBDIR)
        self._indexed: list[_IndexedExcerpt] | None = None

    def retrieve(
        self,
        question: str,
        *,
        locale: str,
        limit: int = 5,
    ) -> Sequence[KnowledgeExcerpt]:

        if limit <= 0:
            return []

        if not _locale_supported(locale):
            return []

        indexed = self._load()

        if not indexed:
            return []

        query = _tokenize(question)

        if not query:
            return []

        scored = _score(query, indexed)

        return [
            KnowledgeExcerpt(
                document_id=item.document_id,
                title=item.title,
                section=item.section,
                text=item.text,
                version=item.version,
            )
            for item in scored[:limit]
        ]

    def _load(self) -> list[_IndexedExcerpt]:

        if self._indexed is not None:
            return self._indexed

        indexed: list[_IndexedExcerpt] = []

        if self._knowledge_dir.is_dir():
            for path in sorted(self._knowledge_dir.glob("*.md")):
                indexed.extend(_parse_document(path))

        self._indexed = indexed

        return indexed


def _locale_supported(locale: str) -> bool:

    normalized = locale.lower().replace("_", "-")

    return normalized == "pt-br" or normalized.startswith("pt-") or normalized == "pt"


def _normalize(text: str) -> str:

    decomposed = unicodedata.normalize("NFKD", text.lower())

    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _tokenize(text: str) -> tuple[str, ...]:

    return tuple(
        token
        for token in _TOKEN.findall(_normalize(text))
        if len(token) >= 2 and token not in _STOPWORDS
    )


def _score(
    query: tuple[str, ...],
    indexed: list[_IndexedExcerpt],
) -> list[_IndexedExcerpt]:

    doc_count = len(indexed)
    doc_freq: dict[str, int] = {}

    for item in indexed:
        for token in set(item.tokens):
            doc_freq[token] = doc_freq.get(token, 0) + 1

    avg_length = sum(len(item.tokens) for item in indexed) / doc_count

    ranked: list[tuple[float, _IndexedExcerpt]] = []

    for item in indexed:
        total = _bm25(query, item, doc_freq, doc_count, avg_length)

        if total >= _MIN_SCORE:
            ranked.append((total, item))

    ranked.sort(key=lambda pair: (-pair[0], pair[1].document_id, pair[1].section))

    return [item for _, item in ranked]


def _bm25(
    query: tuple[str, ...],
    item: _IndexedExcerpt,
    doc_freq: dict[str, int],
    doc_count: int,
    avg_length: float,
) -> float:

    counts: dict[str, int] = {}

    for token in item.tokens:
        counts[token] = counts.get(token, 0) + 1

    length = len(item.tokens)
    total = 0.0

    for token in set(query):
        freq = counts.get(token, 0)

        if freq == 0:
            continue

        df = doc_freq.get(token, 1)
        idf = math.log((doc_count - df + 0.5) / (df + 0.5) + 1.0)
        denom = freq + _K1 * (1.0 - _B + _B * length / avg_length)

        total += idf * freq * (_K1 + 1.0) / denom

    return total


def _parse_document(path: Path) -> list[_IndexedExcerpt]:

    front, body = _split_frontmatter(path.read_text(encoding="utf-8"))

    if front.get("status") != "approved":
        return []

    document_id = str(front.get("document_id", ""))

    if not document_id:
        return []

    title = str(front.get("title", document_id))
    version = front.get("version")
    sections = _split_sections(body)

    excerpts: list[_IndexedExcerpt] = []

    for section, text in sections:
        if not text.strip():
            continue

        tokens = _tokenize(f"{title} {section} {text}")

        if not tokens:
            continue

        excerpts.append(
            _IndexedExcerpt(
                document_id=document_id,
                title=title,
                section=section,
                text=text.strip(),
                version=str(version) if version is not None else None,
                tokens=tokens,
            )
        )

    return excerpts


def _split_frontmatter(raw: str) -> tuple[dict, str]:

    if not raw.startswith("---\n"):
        return {}, raw

    end = raw.find("\n---\n", 4)

    if end == -1:
        return {}, raw

    try:
        front = yaml.safe_load(raw[4:end]) or {}
    except yaml.YAMLError:
        return {}, raw

    if not isinstance(front, dict):
        return {}, raw

    return front, raw[end + 5 :]


def _split_sections(body: str) -> list[tuple[str, str]]:

    matches = list(_HEADING.finditer(body))

    if not matches:
        return [("geral", body.strip())]

    sections: list[tuple[str, str]] = []

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append((match.group(1).strip(), body[start:end].strip()))

    return sections
