"""Sugestão determinística de mapeamento coluna de origem -> campo canônico.

A confiança é uma pontuação heurística (0-1), não uma probabilidade calibrada.
Sugestões abaixo do limiar ou com alertas sempre exigem confirmação humana.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, Field

from app.domain.canonical_fields import CANONICAL_FIELDS, CanonicalField
from app.domain.values import normalize_name

_STOPWORDS = {"de", "da", "do", "dos", "das", "r", "rs", "e", "em"}
_TYPE_COMPAT: dict[str, set[str]] = {
    "decimal": {"decimal", "integer", "empty"},
    "integer": {"integer", "empty"},
    "date": {"date", "empty"},
    "tax_id": {"tax_id", "text", "code", "integer", "empty"},
    "text": {"text", "code", "empty", "boolean", "tax_id", "integer"},
    "code": {"text", "code", "integer", "empty", "tax_id"},
    "boolean": {"boolean", "text", "empty"},
}


class MappingSuggestion(BaseModel):
    """Contrato de saída de uma sugestão (heurística ou IA)."""

    source_column: str
    target_field: str | None
    confidence: float = Field(ge=0, le=1)
    rationale: str
    warnings: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    alternatives: list[str] = Field(default_factory=list)
    source: str = "heuristic"


def _tokens(text: str) -> set[str]:
    return {t for t in text.split() if t not in _STOPWORDS}


def _score_field(norm: str, f: CanonicalField) -> tuple[float, str]:
    names = {normalize_name(s) for s in f.synonyms} | {normalize_name(f.label), normalize_name(f.key.replace("_", " "))}
    if norm in names:
        return 0.95, "nome idêntico a um sinônimo conhecido"
    toks = _tokens(norm)
    best, why = 0.0, ""
    for name in names:
        other = _tokens(name)
        if toks and other:
            jac = len(toks & other) / len(toks | other)
            if jac * 0.85 > best:
                best, why = jac * 0.85, f"termos em comum com '{name}'"
        ratio = SequenceMatcher(None, norm, name).ratio() * 0.8
        if ratio > best:
            best, why = ratio, f"nome semelhante a '{name}'"
    return best, why


def suggest_mappings(columns: list[dict[str, Any]], *, threshold: float = 0.85) -> list[MappingSuggestion]:
    """``columns``: itens do relatório de inspeção (name, normalized, inferred_type)."""
    ranked: list[list[tuple[float, str, str]]] = []
    for col in columns:
        norm = col.get("normalized") or normalize_name(col["name"])
        inferred = col.get("inferred_type", "text")
        scores = []
        for f in CANONICAL_FIELDS:
            score, why = _score_field(norm, f)
            if score <= 0:
                continue
            if inferred not in _TYPE_COMPAT.get(f.data_type, {inferred}):
                score -= 0.3
                why += f"; tipo inferido '{inferred}' incompatível com '{f.data_type}'"
            elif inferred != "empty":
                score = min(0.99, score + 0.03)
            scores.append((round(score, 3), f.key, why))
        scores.sort(reverse=True)
        ranked.append(scores)

    # Resolução de conflitos: cada campo canônico só pode receber uma coluna.
    taken: dict[str, int] = {}
    choice: list[int] = [0] * len(columns)
    order = sorted(range(len(columns)), key=lambda i: -(ranked[i][0][0] if ranked[i] else 0))
    conflicts: dict[int, str] = {}
    for i in order:
        while choice[i] < len(ranked[i]) and ranked[i][choice[i]][1] in taken and ranked[i][choice[i]][0] >= 0.5:
            conflicts.setdefault(i, ranked[i][choice[i]][1])
            choice[i] += 1
        if choice[i] < len(ranked[i]) and ranked[i][choice[i]][0] >= 0.5:
            taken[ranked[i][choice[i]][1]] = i

    out = []
    for i, col in enumerate(columns):
        warnings: list[str] = []
        cands = ranked[i]
        pick = cands[choice[i]] if choice[i] < len(cands) else None
        if pick is None or pick[0] < 0.5:
            alts = [c[1] for c in cands[:3] if c[0] >= 0.35]
            out.append(MappingSuggestion(
                source_column=col["name"], target_field=None, confidence=0.0,
                rationale="Nenhum campo canônico correspondente encontrado; a coluna será ignorada se não for mapeada.",
                warnings=["coluna desconhecida"] if not alts else [], requires_confirmation=True, alternatives=alts))
            continue
        score, target, why = pick
        if i in conflicts:
            warnings.append(f"o campo '{conflicts[i]}' já foi atribuído a outra coluna com pontuação maior")
        nxt = next((c for c in cands if c[1] != target), None)
        if nxt and score - nxt[0] < 0.05 and nxt[0] >= 0.5:
            warnings.append(f"mapeamento ambíguo entre '{target}' e '{nxt[1]}'")
        if "incompatível" in why:
            warnings.append("tipo de dado incompatível com o campo sugerido")
        out.append(MappingSuggestion(
            source_column=col["name"], target_field=target, confidence=score, rationale=why.capitalize(),
            warnings=warnings, requires_confirmation=bool(warnings) or score < threshold,
            alternatives=[c[1] for c in cands[1:4] if c[0] >= 0.35 and c[1] != target]))
    return out
