from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.domain.canonical_fields import field_type
from app.domain.comparison.engine import ComparisonConfig, ResultItem, Side, compare
from app.domain.ingestion.readers import iter_records
from app.domain.mapping.suggest import suggest_mappings
from app.modules.comparison.models import ComparisonJob, ComparisonResult
from app.modules.files import service as files_service
from app.modules.files.models import FileAsset
from app.modules.processing.queue import ConfigError

KEY_FIELDS = ("document_number", "invoice_number", "external_id")


def columns_of(file: FileAsset) -> list[dict[str, Any]]:
    if file.status == "deleted" or not file.inspection:
        raise ValidationFailed(f"O conteúdo do arquivo '{file.original_filename}' foi excluído.")
    return file.inspection["columns"]


def validate_config(config: ComparisonConfig, file_a: FileAsset, file_b: FileAsset) -> None:
    names_a = {c["name"] for c in columns_of(file_a)}
    names_b = {c["name"] for c in columns_of(file_b)}
    errors = []
    for p in [*config.key_pairs, *config.compare_pairs]:
        if p.column_a not in names_a:
            errors.append(f"coluna '{p.column_a}' não existe no arquivo A")
        if p.column_b not in names_b:
            errors.append(f"coluna '{p.column_b}' não existe no arquivo B")
    if errors:
        raise ValidationFailed("Configuração de comparação inválida.", details=errors)


def suggest_config(file_a: FileAsset, file_b: FileAsset) -> dict[str, Any]:
    """Sugere pares de colunas que mapeiam para o mesmo campo canônico. Requer confirmação do usuário."""
    cols_a, cols_b = columns_of(file_a), columns_of(file_b)
    sa = {s.target_field: s for s in suggest_mappings(cols_a) if s.target_field}
    sb = {s.target_field: s for s in suggest_mappings(cols_b) if s.target_field}
    common = [f for f in sa if f in sb]
    key = next((f for f in KEY_FIELDS if f in common), None)
    by_name_a = {c["name"]: c for c in cols_a}
    by_name_b = {c["name"]: c for c in cols_b}
    pairs = []
    for f in common:
        if f == key:
            continue
        ftype = field_type(f)
        kind = "number" if ftype in ("decimal", "integer") else "date" if ftype == "date" else "text"
        pair: dict[str, Any] = {"column_a": sa[f].source_column, "column_b": sb[f].source_column, "kind": kind,
                                "canonical_field": f}
        if kind == "number":
            pair.update(abs_tolerance="0.01",
                        number_style_a=by_name_a[sa[f].source_column].get("number_style") or "auto",
                        number_style_b=by_name_b[sb[f].source_column].get("number_style") or "auto")
        pairs.append(pair)
    # Campos de valor/data com nomes diferentes (ex.: "Valor" x "Valor Pago") também são sugeridos, com alerta.
    loose = []
    for fa, fb, kind in (("amount", "paid_amount", "number"), ("due_date", "payment_date", "date")):
        if fa in sa and fb in sb and fa not in sb:
            loose.append({"column_a": sa[fa].source_column, "column_b": sb[fb].source_column, "kind": kind,
                          "abs_tolerance": "0.01" if kind == "number" else "0",
                          "warning": f"'{fa}' x '{fb}' são campos diferentes; confirme se devem ser comparados."})
    return {
        "key_pairs": [{"column_a": sa[key].source_column, "column_b": sb[key].source_column}] if key else [],
        "compare_pairs": pairs,
        "loose_pairs": loose,
        "columns_a": [c["name"] for c in cols_a],
        "columns_b": [c["name"] for c in cols_b],
        "warnings": [] if key else ["Nenhuma chave de correspondência confiável foi identificada; selecione a chave manualmente."],
    }


def execute_comparison(db: Session, job: ComparisonJob) -> None:
    s = get_settings()
    started = time.monotonic()
    db.execute(delete(ComparisonResult).where(ComparisonResult.comparison_id == job.id))
    config = ComparisonConfig.model_validate(job.config)
    file_a = db.get(FileAsset, job.file_a_id)
    file_b = db.get(FileAsset, job.file_b_id)
    if file_a is None or file_b is None:
        raise ConfigError("Arquivos da comparação não encontrados.")
    buffer: list[dict[str, Any]] = []
    stored = 0

    def sink(item: ResultItem) -> None:
        nonlocal stored
        if stored >= s.max_comparison_rows_stored:
            return
        stored += 1
        buffer.append({"comparison_id": job.id, "organization_id": job.organization_id, "category": item.category,
                       "key_value": (item.key or "")[:250] or None, "row_a": item.row_a, "row_b": item.row_b,
                       "differences": item.differences, "note": item.note})
        if len(buffer) >= 1000:
            db.execute(insert(ComparisonResult), buffer)
            buffer.clear()

    with files_service.local_file(file_a) as pa, files_service.local_file(file_b) as pb:
        cols_a, rows_a = iter_records(pa, files_service.resolved_options(pa, file_a))
        cols_b, rows_b = iter_records(pb, files_service.resolved_options(pb, file_b))
        try:
            outcome = compare(config, Side(cols_a, rows_a), Side(cols_b, rows_b), sink)
        except ValueError as exc:  # colunas inexistentes (estrutura mudou)
            raise ConfigError(str(exc)) from exc
    if buffer:
        db.execute(insert(ComparisonResult), buffer)
    summary = outcome.summary()
    summary["duration_seconds"] = round(time.monotonic() - started, 3)
    job.summary = summary
    job.results_stored = stored
    job.results_truncated = stored < sum(v for k, v in summary.items() if k not in ("rows_a", "rows_b", "match", "field_divergences", "duration_seconds"))
    job.status = "succeeded"
    job.finished_at = datetime.now(UTC)
    job.locked_by = None


def cleanup(db: Session, job_id: uuid.UUID) -> None:
    db.execute(delete(ComparisonResult).where(ComparisonResult.comparison_id == job_id))
