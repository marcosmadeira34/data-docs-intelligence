from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.mapping.entries import MappingEntry, RecordBuilder
from app.domain.validation.conditions import ConditionGroup, evaluate
from app.domain.validation.engine import RuleSpec, ValidationEngine
from app.domain.validation.rules import REGISTRY, RuleContext, catalog, parse_params, validate_safe_regex

COLUMNS = ["doc", "nome", "cnpj", "emissao", "venc", "pagto", "valor", "status", "total", "item", "grupo"]
FIELDS = ["document_number", "counterparty_name", "counterparty_tax_id", "issue_date", "due_date", "payment_date", "amount",
          "status", "total_amount", "item_amount", "category"]
BUILDER = RecordBuilder(COLUMNS, [MappingEntry(source_column=c, target_field=f, status="approved", number_style="br")
                                  for c, f in zip(COLUMNS, FIELDS, strict=True)])


def row(**kw):
    base = {"doc": "D1", "nome": "Fornecedor", "cnpj": "11.222.333/0001-81", "emissao": "01/01/2024", "venc": "10/01/2024",
            "pagto": "", "valor": "100,00", "status": "Aberto", "total": "", "item": "", "grupo": ""}
    base.update(kw)
    return [base[c] for c in COLUMNS]


def run(specs, rows, ctx=None, max_per_rule=5000, mapped=None):
    found = []
    engine = ValidationEngine(specs, mapped_fields=set(mapped or FIELDS), sink=found.append, ctx=ctx,
                              max_findings_per_rule=max_per_rule)
    result = engine.run(BUILDER.build(i + 2, r) for i, r in enumerate(rows))
    return found, result


def spec(rtype, params, severity="error", key=None, **kw):
    return RuleSpec(rule_key=key or rtype, rule_type=rtype, params=params, severity=severity, **kw)


def test_required():
    found, _ = run([spec("required", {"field": "counterparty_name"})], [row(), row(nome=""), row(nome="  ")])
    assert [f.row_number for f in found] == [3, 4]


def test_required_unmapped_field_yields_single_dataset_finding():
    found, result = run([spec("required", {"field": "invoice_number"})], [row(), row()])
    assert len(found) == 1 and found[0].row_number is None
    assert result.rules[0].skipped_reason


def test_data_type():
    found, _ = run([spec("data_type", {"field": "amount", "type": "decimal"})], [row(), row(valor="abc"), row(valor="")])
    assert [f.row_number for f in found] == [3] and found[0].observed_value == "abc"


@pytest.mark.parametrize(("fmt", "good", "bad"), [
    ("cnpj", "11.222.333/0001-81", "11.222.333/0001-80"),
    ("cpf_cnpj", "529.982.247-25", "123"),
])
def test_format(fmt, good, bad):
    found, _ = run([spec("format", {"field": "counterparty_tax_id", "format": fmt})], [row(cnpj=good), row(cnpj=bad)])
    assert [f.row_number for f in found] == [3]
    assert "*" in (found[0].observed_value or "") or len(bad) < 11  # documentos são mascarados


def test_range_and_severity():
    found, result = run([spec("range", {"field": "amount", "min": "0", "exclusive_min": True}, severity="warning")],
                        [row(valor="0"), row(valor="10"), row(valor="-5")])
    assert [f.row_number for f in found] == [2, 4]
    assert result.counts["warning"] == 2 and result.counts["error"] == 0


def test_valid_date_with_bounds():
    found, _ = run([spec("valid_date", {"field": "issue_date", "min_date": "2024-01-01", "max_date": "2024-12-31"})],
                   [row(), row(emissao="31/02/2024"), row(emissao="01/01/2023")])
    assert [(f.row_number, f.message) for f in found] == [(3, "Data inválida ou inexistente."), (4, "Data fora do período permitido.")]


def test_allowed_values_case_insensitive_by_default():
    found, _ = run([spec("allowed_values", {"field": "status", "values": ["Aberto", "Pago"]})],
                   [row(status="ABERTO"), row(status="pago"), row(status="Estornado")])
    assert [f.row_number for f in found] == [4]


def test_duplicate_combination():
    found, _ = run([spec("duplicate", {"fields": ["document_number", "amount"]})],
                   [row(), row(valor="200,00"), row(), row()])
    assert [f.row_number for f in found] == [4, 5] and found[0].evidence["first_row"] == 2


def test_unique_key_missing_and_repeated():
    found, _ = run([spec("unique_key", {"fields": ["document_number"]})], [row(), row(doc=""), row(doc="d1")])
    assert [(f.row_number, f.evidence.get("missing_fields")) for f in found] == [(3, ["document_number"]), (4, None)]


def test_regex_restricted():
    found, _ = run([spec("regex", {"field": "document_number", "pattern": r"[A-Z]\d+"})], [row(), row(doc="x-1")])
    assert [f.row_number for f in found] == [3]
    for dangerous in [r"(a+)+$", r"(\w)\1", r"(?=a)", "a{10000}", "x" * 201, "("]:
        with pytest.raises((ValueError, ValidationError)):
            parse_params("regex", {"field": "document_number", "pattern": dangerous})
    assert validate_safe_regex(r"\d{3}")


def test_dependency_between_fields():
    rule = spec("dependency", {"when": {"all": [{"field": "status", "op": "eq", "value": "pago"}]},
                               "then": {"all": [{"field": "payment_date", "op": "not_null"}]}})
    found, _ = run([rule], [row(status="Pago", pagto="05/01/2024"), row(status="Pago"), row(status="Aberto")])
    assert [f.row_number for f in found] == [3] and found[0].field == "payment_date"


def test_total_consistency_row_and_group():
    row_rule = spec("total_consistency", {"mode": "row", "total_field": "total_amount", "item_fields": ["amount", "item_amount"]})
    found, _ = run([row_rule], [row(total="150,00", item="50,00"), row(total="150,00", item="49,00")])
    assert [f.row_number for f in found] == [3] and found[0].evidence["difference"] == "-1.00"
    group_rule = spec("total_consistency", {"mode": "group", "group_by": ["document_number"], "item_field": "item_amount",
                                            "total_field": "total_amount", "tolerance": "0.01"}, key="g")
    rows = [row(doc="N1", item="10,00", total="30,00"), row(doc="N1", item="20,00", total="30,00"),
            row(doc="N2", item="10,00", total="25,00"), row(doc="N3", item="1,00", total="1,00"), row(doc="N3", item="1,00", total="2,00")]
    found, _ = run([group_rule], rows)
    msgs = {f.evidence["group"]: f.message for f in found}
    assert set(msgs) == {"n2", "n3"} and "diferentes" in msgs["n3"]


def test_cross_file_reference():
    ctx = RuleContext(reference_sets={"ref": {"FORNECEDOR", "OUTRO"}})
    rule = spec("cross_file", {"field": "counterparty_name", "reference_file_id": "x", "reference_column": "Nome"}, key="ref")
    found, _ = run([rule], [row(), row(nome=" fornecedor "), row(nome="Desconhecido")], ctx=ctx)
    assert [f.row_number for f in found] == [4]


def test_completeness():
    found, _ = run([spec("completeness", {"field": "payment_date", "min_ratio": 0.5}, severity="info")],
                   [row(pagto="01/01/2024"), row(), row()])
    assert len(found) == 1 and found[0].row_number is None and found[0].evidence["filled"] == 1


def test_custom_rule_field_vs_field():
    rule = spec("custom", {"assert": {"all": [{"field": "due_date", "op": "gte", "value_field": "issue_date"}]}})
    found, _ = run([rule], [row(), row(venc="01/12/2023")])
    assert [f.row_number for f in found] == [3]


def test_applies_when_condition():
    rule = spec("required", {"field": "payment_date"}, applies_when={"all": [{"field": "status", "op": "in", "value": ["pago"]}]})
    found, _ = run([rule], [row(), row(status="Pago")])
    assert [f.row_number for f in found] == [3]


def test_rule_skipped_when_fields_not_mapped():
    found, result = run([spec("range", {"field": "amount", "min": "0"})], [row()], mapped=["document_number"])
    assert found == [] and "amount" in result.rules[0].skipped_reason


def test_findings_capped_per_rule_but_counted():
    found, result = run([spec("required", {"field": "counterparty_name"})], [row(nome="")] * 10, max_per_rule=3)
    assert len(found) == 3 and result.rules[0].violations == 10 and result.counts["error"] == 10


def test_record_key_attached_to_findings():
    found, _ = run([spec("required", {"field": "counterparty_name"})], [row(doc="NF-77", nome="")])
    assert found[0].record_key == "NF-77"


def test_conditions_validation_and_operators():
    with pytest.raises(ValidationError):
        ConditionGroup.model_validate({"all": [{"field": "amount", "op": "gt"}]})
    with pytest.raises(ValidationError):
        ConditionGroup.model_validate({"all": [], "any": []})
    deep = {"all": [{"all": [{"all": [{"all": [{"field": "amount", "op": "is_null"}]}]}]}]}
    with pytest.raises(ValidationError):
        ConditionGroup.model_validate(deep)
    rec = BUILDER.build(2, row(valor="1.000,00", emissao="01/01/2024"))
    assert evaluate(ConditionGroup.model_validate({"all": [{"field": "amount", "op": "gte", "value": "999.99"}]}), rec)
    assert evaluate(ConditionGroup.model_validate({"any": [{"field": "issue_date", "op": "lt", "value": "2023-01-01"},
                                                           {"field": "status", "op": "starts_with", "value": "abe"}]}), rec)
    assert not evaluate(ConditionGroup.model_validate({"all": [{"field": "issue_date", "op": "gt", "value": str(date(2024, 6, 1))}]}), rec)


def test_every_rule_type_has_catalog_entry_and_rejects_bad_params():
    types = {c["type"] for c in catalog()}
    assert types == set(REGISTRY) and len(types) == 14
    for t in REGISTRY:
        with pytest.raises((ValidationError, ValueError)):
            parse_params(t, {"field": "Campo Inválido!", "fields": [], "mode": "x", "min_ratio": 5})
