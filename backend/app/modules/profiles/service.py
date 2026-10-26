from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Conflict, ValidationFailed
from app.domain.mapping.compatibility import check_compatibility, structure_signature
from app.domain.mapping.entries import MappingEntry, validate_entries
from app.modules.billing import service as billing
from app.modules.files.models import FileAsset
from app.modules.profiles.models import DatasetProfile, DatasetProfileVersion, MappingProfile

_STATUS_ORDER = {"identical": 0, "compatible": 1, "review_required": 2, "incompatible": 3}


def entries_of(version: DatasetProfileVersion) -> list[MappingEntry]:
    return [MappingEntry.model_validate(e) for e in (version.mapping.entries if version.mapping else [])]


def file_columns(file: FileAsset) -> list[dict[str, Any]]:
    if not file.inspection:
        raise ValidationFailed("O arquivo não possui inspeção disponível (conteúdo excluído).")
    return file.inspection["columns"]


def compatibility(version: DatasetProfileVersion, file: FileAsset) -> dict[str, Any]:
    result = check_compatibility(version.columns, entries_of(version), file_columns(file))
    if version.source_format != file.detected_format:
        result["messages"].append(f"Formato diferente do perfil ({version.source_format} → {file.detected_format}); "
                                  "as colunas são compatíveis, então o perfil pode ser aplicado.")
    return result


def match_profiles(db: Session, org_id: uuid.UUID, file: FileAsset, limit: int = 20) -> list[dict[str, Any]]:
    if not file.inspection:
        return []
    rows = db.execute(
        select(DatasetProfile, DatasetProfileVersion)
        .join(DatasetProfileVersion, DatasetProfileVersion.id == DatasetProfile.current_version_id)
        .where(DatasetProfile.organization_id == org_id, DatasetProfile.status == "active",
               DatasetProfileVersion.approval_status == "approved",
               or_(DatasetProfile.client_account_id == file.client_account_id, DatasetProfile.client_account_id.is_(None)))
        .limit(limit)
    ).all()
    out = []
    for profile, version in rows:
        comp = compatibility(version, file)
        out.append({"profile_id": str(profile.id), "profile_name": profile.name, "version_id": str(version.id),
                    "version": version.version, "client_account_id": str(profile.client_account_id) if profile.client_account_id else None,
                    "compatibility": comp})
    out.sort(key=lambda m: (_STATUS_ORDER[m["compatibility"]["status"]], m["profile_name"]))
    return out


def _validate_for_file(entries: list[MappingEntry], file: FileAsset, approve: bool) -> None:
    errors = validate_entries(entries)
    names = {c["name"] for c in file_columns(file)}
    unknown = [e.source_column for e in entries if e.source_column not in names]
    if unknown:
        errors.append(f"colunas inexistentes no arquivo: {', '.join(unknown)}")
    if not any(e.target_field and e.status != "ignored" for e in entries):
        errors.append("mapeie pelo menos uma coluna")
    if approve:
        pending = [e.source_column for e in entries if e.status == "suggested"]
        if pending:
            errors.append("para aprovar, confirme ou ignore todas as sugestões pendentes: " + ", ".join(pending))
    if errors:
        raise ValidationFailed("Mapeamento inválido.", details=errors)


def _new_version(db: Session, profile: DatasetProfile, file: FileAsset, entries: list[MappingEntry], *, number: int,
                 user_id: uuid.UUID, approve: bool, change_note: str | None, suggestion_source: str) -> DatasetProfileVersion:
    opts = file.read_options or {}
    cols = [{"name": c["name"], "inferred_type": c.get("inferred_type"), "number_style": c.get("number_style"),
             "date_format": c.get("date_format")} for c in file_columns(file)]
    now = datetime.now(UTC)
    version = DatasetProfileVersion(
        profile_id=profile.id, organization_id=profile.organization_id, version=number, source_format=file.detected_format,
        sheet_name=opts.get("sheet"), header_row=opts.get("header_row") or 1, delimiter=opts.get("delimiter"),
        encoding=opts.get("encoding"), columns=cols, structure_signature=structure_signature([c["name"] for c in cols]),
        structural_rules={"allow_extra_columns": True}, approval_status="approved" if approve else "draft",
        approved_by=user_id if approve else None, approved_at=now if approve else None, created_by=user_id,
        change_note=change_note, source_file_id=file.id)
    db.add(version)
    db.flush()
    db.add(MappingProfile(
        profile_version_id=version.id, organization_id=profile.organization_id,
        entries=[e.model_dump(mode="json") for e in entries], suggestion_source=suggestion_source,
        confirmation_threshold=get_settings().mapping_confirmation_threshold,
        approved_by=user_id if approve else None, approved_at=now if approve else None))
    if approve:
        _promote(db, profile, version)
    db.flush()
    db.refresh(version)
    return version


def _promote(db: Session, profile: DatasetProfile, version: DatasetProfileVersion) -> None:
    if profile.current_version_id and profile.current_version_id != version.id:
        prev = db.get(DatasetProfileVersion, profile.current_version_id)
        if prev is not None:
            prev.approval_status = "superseded"
    profile.current_version_id = version.id


def create_profile(db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, name: str, description: str | None,
                   client_id: uuid.UUID | None, file: FileAsset, entries: list[MappingEntry], approve: bool,
                   suggestion_source: str) -> DatasetProfile:
    _validate_for_file(entries, file, approve)
    if client_id is not None and client_id != file.client_account_id:
        raise ValidationFailed("O arquivo de referência pertence a outra empresa.")
    if db.scalar(select(DatasetProfile.id).where(DatasetProfile.organization_id == org_id, DatasetProfile.name == name)):
        raise Conflict("Já existe um perfil com este nome.")
    _, limits = billing.get_limits(db, org_id)
    count = db.scalar(select(func.count()).select_from(DatasetProfile).where(
        DatasetProfile.organization_id == org_id, DatasetProfile.status == "active")) or 0
    billing.check_count_limit("profiles", count, limits)
    profile = DatasetProfile(organization_id=org_id, client_account_id=client_id, name=name, description=description,
                             created_by=user_id)
    db.add(profile)
    db.flush()
    _new_version(db, profile, file, entries, number=1, user_id=user_id, approve=approve, change_note="Versão inicial",
                 suggestion_source=suggestion_source)
    return profile


def add_version(db: Session, *, profile: DatasetProfile, user_id: uuid.UUID, file: FileAsset, entries: list[MappingEntry],
                approve: bool, change_note: str | None, suggestion_source: str) -> DatasetProfileVersion:
    _validate_for_file(entries, file, approve)
    if profile.client_account_id is not None and profile.client_account_id != file.client_account_id:
        raise ValidationFailed("O arquivo pertence a outra empresa.")
    last = db.scalar(select(func.max(DatasetProfileVersion.version)).where(DatasetProfileVersion.profile_id == profile.id)) or 0
    return _new_version(db, profile, file, entries, number=last + 1, user_id=user_id, approve=approve,
                        change_note=change_note, suggestion_source=suggestion_source)


def approve_version(db: Session, profile: DatasetProfile, version: DatasetProfileVersion, user_id: uuid.UUID) -> None:
    if version.approval_status != "draft":
        raise Conflict("Somente versões em rascunho podem ser aprovadas.")
    pending = [e.source_column for e in entries_of(version) if e.status == "suggested"]
    if pending:
        raise ValidationFailed("Confirme ou ignore todas as sugestões antes de aprovar.", details=pending)
    now = datetime.now(UTC)
    version.approval_status = "approved"
    version.approved_by, version.approved_at = user_id, now
    if version.mapping:
        version.mapping.approved_by, version.mapping.approved_at = user_id, now
    _promote(db, profile, version)
