from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.mapping.compatibility import check_compatibility, structure_signature
from app.domain.mapping.entries import MappingEntry, RecordBuilder, validate_entries
from app.domain.mapping.suggest import suggest_mappings


def col(name, t="text"):
    return {"name": name, "inferred_type": t}


def by_source(suggestions):
    return {s.source_column: s for s in suggestions}


def test_exact_name_suggestion_high_confidence():
    s = by_source(suggest_mappings([col("Vencimento", "date"), col("Valor", "decimal")]))
    assert s["Vencimento"].target_field == "due_date" and s["Vencimento"].confidence >= 0.95
    assert not s["Valor"].requires_confirmation


def test_synonyms_and_abbreviations():
    s = by_source(suggest_mappings([col("Nº Doc."), col("Razão Social"), col("CPF/CNPJ", "tax_id"), col("Dt. Baixa", "date"),
                                    col("Vlr. Título (R$)", "decimal")]))
    assert s["Nº Doc."].target_field == "document_number"
    assert s["Razão Social"].target_field == "counterparty_name"
    assert s["CPF/CNPJ"].target_field == "counterparty_tax_id"
    assert s["Dt. Baixa"].target_field == "payment_date"
    assert s["Vlr. Título (R$)"].target_field == "amount"


def test_unknown_column_not_mapped():
    s = suggest_mappings([col("Xpto Interno 42")])[0]
    assert s.target_field is None and s.confidence == 0 and s.requires_confirmation


def test_incompatible_type_lowers_confidence_and_warns():
    s = suggest_mappings([col("Valor", "date")])[0]
    assert s.requires_confirmation
    assert any("incompat" in w for w in s.warnings) or s.target_field != "amount"


def test_conflict_same_target_resolved_with_warning():
    s = by_source(suggest_mappings([col("Valor", "decimal"), col("Valor Documento", "decimal")]))
    targets = [x.target_field for x in s.values() if x.target_field]
    assert len(targets) == len(set(targets)), "um campo canônico não pode receber duas colunas"
    loser = s["Valor Documento"] if s["Valor"].target_field == "amount" else s["Valor"]
    assert loser.target_field != "amount" and loser.requires_confirmation


def test_ambiguous_mapping_requires_confirmation():
    s = suggest_mappings([col("Data", "date")])[0]
    # "data" é genérico: deve exigir confirmação humana ou trazer alternativas
    assert s.requires_confirmation or s.alternatives


def test_mapping_entry_validation():
    with pytest.raises(ValidationError):
        MappingEntry(source_column="A", target_field="campo_inexistente")
    with pytest.raises(ValidationError):
        MappingEntry(source_column="A", target_field="amount", transforms=["eval"])
    with pytest.raises(ValidationError):
        MappingEntry(source_column="A", target_field=None, status="approved")
    assert MappingEntry(source_column="A", target_field="x_centro_lucro").target_field == "x_centro_lucro"
    ignored = MappingEntry(source_column="A", target_field="amount", status="ignored", required=True)
    assert ignored.target_field is None and not ignored.required


def test_validate_entries_detects_duplicates():
    errors = validate_entries([MappingEntry(source_column="A", target_field="amount", status="approved"),
                               MappingEntry(source_column="B", target_field="amount", status="approved"),
                               MappingEntry(source_column="A", target_field="due_date", status="approved")])
    assert len(errors) == 2


def test_record_builder_transforms_and_types():
    entries = [MappingEntry(source_column="Doc", target_field="document_number", status="approved", transforms=["trim", "upper"]),
               MappingEntry(source_column="Valor", target_field="amount", status="approved", number_style="br", transforms=["abs"]),
               MappingEntry(source_column="CNPJ", target_field="counterparty_tax_id", status="approved", transforms=["digits_only"]),
               MappingEntry(source_column="Ignorar", status="ignored")]
    rb = RecordBuilder(["Doc", "Valor", "CNPJ", "Ignorar"], entries)
    rec = rb.build(2, ["  ab-1 ", "-1.234,50", "11.222.333/0001-81", "x"])
    assert rec.get("document_number") == "AB-1"
    assert rec.get("amount") == Decimal("1234.50")
    assert rec.get("counterparty_tax_id") == "11222333000181"
    assert "Ignorar" not in {fv.source_column for fv in rec.fields.values()}
    bad = rb.build(3, ["x", "abc", "", ""])
    assert bad.fields["amount"].ok is False and bad.raw("amount") == "abc"


def test_record_builder_reports_missing_columns():
    rb = RecordBuilder(["Doc"], [MappingEntry(source_column="Valor", target_field="amount", status="approved")])
    assert rb.missing_columns == ["Valor"]


PROFILE_COLS = [col("Documento"), col("Valor", "decimal"), col("Vencimento", "date"), col("Obs")]
ENTRIES = [MappingEntry(source_column="Documento", target_field="document_number", status="approved"),
           MappingEntry(source_column="Valor", target_field="amount", status="approved"),
           MappingEntry(source_column="Vencimento", target_field="due_date", status="approved"),
           MappingEntry(source_column="Obs", status="ignored")]


def test_compatibility_identical_and_reordered():
    assert check_compatibility(PROFILE_COLS, ENTRIES, PROFILE_COLS)["status"] == "identical"
    reordered = [PROFILE_COLS[2], PROFILE_COLS[0], PROFILE_COLS[1], PROFILE_COLS[3]]
    r = check_compatibility(PROFILE_COLS, ENTRIES, reordered)
    assert r["status"] == "compatible" and r["order_changed"] and not r["requires_review"]


def test_compatibility_additions_and_unmapped_removal_are_compatible():
    new = [*PROFILE_COLS[:3], col("Nova coluna")]
    r = check_compatibility(PROFILE_COLS, ENTRIES, new)
    assert r["status"] == "compatible"
    assert r["added_columns"] == ["Nova coluna"] and r["missing_unmapped_columns"] == ["Obs"]


def test_structural_change_requires_review():
    renamed = [col("Documento"), col("Valor Líquido", "decimal"), col("Vencimento", "date")]
    r = check_compatibility(PROFILE_COLS, ENTRIES, renamed)
    assert r["status"] == "incompatible" and r["requires_review"] and r["missing_mapped_columns"] == ["Valor"]
    type_changed = [col("Documento"), col("Valor", "date"), col("Vencimento", "date")]
    r = check_compatibility(PROFILE_COLS, ENTRIES, type_changed)
    assert r["status"] == "review_required" and r["type_changes"][0]["column"] == "Valor"


def test_signature_ignores_order_and_case():
    assert structure_signature(["A", "Valor"]) == structure_signature(["valor", "a"])
    assert structure_signature(["A"]) != structure_signature(["B"])
