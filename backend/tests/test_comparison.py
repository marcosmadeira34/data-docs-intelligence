import pytest
from pydantic import ValidationError

from app.domain.comparison.engine import ComparisonConfig, Side, compare


def side(rows, cols=("Doc", "Valor", "Data", "Nome")):
    return Side(list(cols), [(i + 2, list(r)) for i, r in enumerate(rows)])


def cfg(**kw):
    base = {"key_pairs": [{"column_a": "Doc", "column_b": "Doc"}],
            "compare_pairs": [{"column_a": "Valor", "column_b": "Valor", "kind": "number", "abs_tolerance": "0.01"},
                              {"column_a": "Data", "column_b": "Data", "kind": "date"},
                              {"column_a": "Nome", "column_b": "Nome"}]}
    base.update(kw)
    return ComparisonConfig.model_validate(base)


def run(config, a, b, include_matches=False):
    items = []
    out = compare(config, side(a), side(b), items.append, include_matches=include_matches)
    return out, items


def test_exact_matches_with_normalization():
    a = [["A1", "1.000,00", "01/02/2024", "Fornecedor X"]]
    b = [[" a1 ", 1000.0, "2024-02-01", "FORNECEDOR   x"]]
    out, items = run(cfg(), a, b, include_matches=True)
    assert out.counts["match"] == 1 and [i.category for i in items] == ["match"]


def test_records_only_in_each_side():
    out, items = run(cfg(), [["A1", "1", "", ""], ["A2", "1", "", ""]], [["A1", "1", "", ""], ["B9", "1", "", ""]])
    assert out.counts["only_a"] == 1 and out.counts["only_b"] == 1
    assert {(i.category, i.key) for i in items} == {("only_a", "A2"), ("only_b", "B9")}


def test_numeric_divergence_and_tolerances():
    a = [["A1", "100,00", "", ""], ["A2", "100,00", "", ""], ["A3", "100,00", "", ""]]
    b = [["A1", "100,005", "", ""], ["A2", "101,00", "", ""], ["A3", "100,50", "", ""]]
    out, items = run(cfg(), a, b)
    assert out.counts["match"] == 1 and out.counts["mismatch"] == 2
    d = next(i for i in items if i.key == "A2").differences[0]
    assert d["delta"] == "1.00" and d["reason"] == "diferença numérica"
    pct = cfg(compare_pairs=[{"column_a": "Valor", "column_b": "Valor", "kind": "number", "pct_tolerance": "0.006"}])
    out, _ = run(pct, a, b)
    assert out.counts["match"] == 2 and out.counts["mismatch"] == 1


def test_duplicate_keys_are_ambiguous_not_matched():
    out, items = run(cfg(), [["A1", "1", "", ""]], [["A1", "1", "", ""], ["A1", "1", "", ""]])
    assert out.counts["match"] == 0 and out.counts["duplicate_key_b"] == 2
    assert all(i.row_a == 2 for i in items)
    out, _ = run(cfg(), [["A1", "1", "", ""], ["A1", "2", "", ""]], [])
    assert out.counts["duplicate_key_a"] == 2 and out.counts["only_a"] == 0


def test_null_handling():
    a = [["A1", "", "", ""], ["A2", "", "", "Nome"]]
    b = [["A1", "", "", ""], ["A2", "", "", ""]]
    out, _ = run(cfg(), a, b)
    assert out.counts["match"] == 1 and out.counts["mismatch"] == 1
    out, _ = run(cfg(null_vs_value="ignore"), a, b)
    assert out.counts["match"] == 2


def test_missing_key_not_comparable():
    out, items = run(cfg(), [["", "1", "", ""]], [[None, "1", "", ""]])
    assert out.counts["missing_key_a"] == 1 and out.counts["missing_key_b"] == 1 and out.counts["only_a"] == 0
    assert items[0].note


def test_unsafe_values_reported_not_equated():
    out, items = run(cfg(), [["A1", "abc", "31/02/2024", ""]], [["A1", "abc", "31/02/2024", ""]])
    reasons = {d["reason"] for d in items[0].differences}
    assert out.counts["mismatch"] == 1 and any("insegura" in r for r in reasons)


def test_composite_key_and_config_validation():
    config = cfg(key_pairs=[{"column_a": "Doc", "column_b": "Doc"}, {"column_a": "Nome", "column_b": "Nome"}], compare_pairs=[])
    out, _ = run(config, [["A1", "", "", "X"], ["A1", "", "", "Y"]], [["A1", "", "", "x"]])
    assert out.counts["match"] == 1 and out.counts["only_a"] == 1
    with pytest.raises(ValidationError):
        ComparisonConfig.model_validate({"key_pairs": []})
    with pytest.raises(ValueError):
        compare(cfg(key_pairs=[{"column_a": "Inexistente", "column_b": "Doc"}]), side([]), side([]), lambda _: None)
