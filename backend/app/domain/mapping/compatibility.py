"""Assinatura estrutural e verificação de compatibilidade com perfis aprovados.

A compatibilidade é decidida pelas colunas (nomes normalizados) e tipos, nunca
pelo nome do arquivo.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from app.domain.mapping.entries import MappingEntry
from app.domain.values import normalize_name

CompatStatus = Literal["identical", "compatible", "review_required", "incompatible"]
_COMPATIBLE_TYPES = [{"integer", "decimal"}, {"text", "code"}, {"tax_id", "text", "code"}]


def structure_signature(column_names: list[str]) -> str:
    norm = sorted(normalize_name(c) for c in column_names)
    return hashlib.sha256("\x1f".join(norm).encode()).hexdigest()


def _types_compatible(a: str, b: str) -> bool:
    if a == b or "empty" in (a, b):
        return True
    return any(a in group and b in group for group in _COMPATIBLE_TYPES)


def check_compatibility(
    profile_columns: list[dict[str, Any]],
    entries: list[MappingEntry],
    file_columns: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compara a estrutura de um arquivo com a de uma versão de perfil.

    Retorna status e diferenças. ``incompatible`` e ``review_required`` exigem
    revisão humana antes de processar.
    """
    prof = {normalize_name(c["name"]): c for c in profile_columns}
    new = {normalize_name(c["name"]): c for c in file_columns}
    mapped = {normalize_name(e.source_column): e for e in entries if e.target_field and e.status != "ignored"}

    missing_mapped = [mapped[n].source_column for n in mapped if n not in new]
    missing_unmapped = [prof[n]["name"] for n in prof if n not in new and n not in mapped]
    added = [new[n]["name"] for n in new if n not in prof]
    type_changes = []
    for n, entry in mapped.items():
        if n in new and n in prof:
            old_t, new_t = prof[n].get("inferred_type", "text"), new[n].get("inferred_type", "text")
            if not _types_compatible(old_t, new_t):
                type_changes.append({"column": entry.source_column, "expected": old_t, "found": new_t})

    order_changed = [normalize_name(c["name"]) for c in profile_columns if normalize_name(c["name"]) in new] != [
        n for n in (normalize_name(c["name"]) for c in file_columns) if n in prof
    ]

    status: CompatStatus
    if missing_mapped:
        status = "incompatible"
    elif type_changes:
        status = "review_required"
    elif added or missing_unmapped or order_changed:
        status = "compatible"
    else:
        status = "identical"

    messages = []
    if missing_mapped:
        messages.append(f"Colunas mapeadas ausentes no arquivo: {', '.join(missing_mapped)}.")
    if type_changes:
        messages.append("Tipos de dados diferentes em colunas mapeadas: "
                        + ", ".join(f"{t['column']} ({t['expected']} → {t['found']})" for t in type_changes) + ".")
    if added:
        messages.append(f"Novas colunas (não mapeadas): {', '.join(added)}.")
    if missing_unmapped:
        messages.append(f"Colunas não mapeadas ausentes: {', '.join(missing_unmapped)}.")
    if order_changed:
        messages.append("A ordem das colunas mudou (não afeta o processamento).")
    return {
        "status": status,
        "requires_review": status in ("incompatible", "review_required"),
        "missing_mapped_columns": missing_mapped,
        "missing_unmapped_columns": missing_unmapped,
        "added_columns": added,
        "type_changes": type_changes,
        "order_changed": order_changed,
        "messages": messages,
    }
