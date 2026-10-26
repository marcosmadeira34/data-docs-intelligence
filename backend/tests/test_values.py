from datetime import date, datetime
from decimal import Decimal

import pytest

from app.domain.values import (
    is_valid_cnpj,
    is_valid_cpf,
    mask_value,
    normalize_name,
    parse_date,
    parse_decimal,
    parse_typed,
)


@pytest.mark.parametrize(("raw", "style", "expected"), [
    ("1.234,56", "auto", Decimal("1234.56")),
    ("1,234.56", "auto", Decimal("1234.56")),
    ("R$ 1.234,56", "auto", Decimal("1234.56")),
    ("-150,00", "auto", Decimal("-150.00")),
    ("(150,00)", "auto", Decimal("-150.00")),
    ("150,00-", "auto", Decimal("-150.00")),
    ("1.234", "auto", Decimal("1234")),        # ambíguo: milhar no padrão brasileiro
    ("1.5", "auto", Decimal("1.5")),
    ("1.234", "us", Decimal("1.234")),
    ("10", "br", Decimal("10")),
    (12.5, "auto", Decimal("12.5")),
])
def test_parse_decimal_valid(raw, style, expected):
    assert parse_decimal(raw, style) == expected


@pytest.mark.parametrize("raw", ["abc", "", "1,2,3", "12.34.5,6x", "--", None, True, "1.23.4"])
def test_parse_decimal_invalid(raw):
    assert parse_decimal(raw, "br") is None


@pytest.mark.parametrize(("raw", "fmt", "expected"), [
    ("31/01/2024", None, date(2024, 1, 31)),
    ("2024-01-31", None, date(2024, 1, 31)),
    ("31.01.2024", None, date(2024, 1, 31)),
    ("2024-01-31 10:30:00", None, date(2024, 1, 31)),
    ("01/31/2024", "mm/dd/yyyy", date(2024, 1, 31)),
    (datetime(2024, 1, 31, 8, 0), None, date(2024, 1, 31)),
    (45322, None, date(2024, 1, 31)),  # serial do Excel
])
def test_parse_date_valid(raw, fmt, expected):
    assert parse_date(raw, fmt) == expected


@pytest.mark.parametrize("raw", ["31/02/2024", "2024-13-01", "texto", "", None, "01/31/2024"])
def test_parse_date_invalid(raw):
    assert parse_date(raw) is None


def test_cpf_cnpj_check_digits():
    assert is_valid_cpf("529.982.247-25")
    assert not is_valid_cpf("529.982.247-26")
    assert not is_valid_cpf("111.111.111-11")
    assert is_valid_cnpj("11.222.333/0001-81")
    assert not is_valid_cnpj("11.222.333/0001-80")
    assert not is_valid_cnpj("123")


def test_parse_typed_never_invents_values():
    assert parse_typed("", "decimal") == (None, True)
    assert parse_typed("abc", "decimal") == (None, False)
    assert parse_typed("10,5", "integer") == (None, False)
    assert parse_typed("10", "integer") == (10, True)


def test_mask_value_hides_document_digits():
    assert mask_value("529.982.247-25") == "***.982.***-**"
    assert mask_value("11222333000181") == "**.222.***/0001-**"
    assert mask_value("joao@exemplo.com") == "j***@exemplo.com"
    assert mask_value("x" * 200).endswith("…")


def test_normalize_name():
    assert normalize_name("  Nº Doc. ") == "no doc"
    assert normalize_name("Vlr. Título (R$)") == "vlr titulo r"
