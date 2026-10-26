"""Interpretação determinística de valores de células.

Todas as funções são puras: recebem um valor bruto (str, número, data) e
devolvem o valor interpretado ou ``None`` quando não é possível interpretar.
Nenhuma função "inventa" valores ausentes.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

NumberStyle = Literal["br", "us", "auto"]

_EXCEL_EPOCH = datetime(1899, 12, 30)
_NUM_CLEAN = re.compile(r"[\sR$ ]")


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.time() == datetime.min.time():
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_name(text: str) -> str:
    """Normaliza um nome de coluna: sem acentos, minúsculo, separadores únicos."""
    t = strip_accents(to_text(text)).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def digits_only(value: Any) -> str:
    return re.sub(r"\D", "", to_text(value))


# --------------------------------------------------------------------------- números


def parse_decimal(value: Any, style: NumberStyle = "auto") -> Decimal | None:
    """Interpreta números em formato brasileiro (1.234,56) ou americano (1,234.56).

    No modo ``auto`` a última ocorrência de separador decide; um único separador
    seguido de exatamente 3 dígitos (ex.: ``1.234``) é ambíguo e, no contexto
    brasileiro, é tratado como separador de milhar.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, Decimal):
        return value
    text = _NUM_CLEAN.sub("", str(value))
    if not text:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    if text.endswith("-"):
        negative, text = True, text[:-1]
    if text.startswith("-"):
        negative, text = not negative, text[1:]
    elif text.startswith("+"):
        text = text[1:]
    if not text or not re.fullmatch(r"[\d.,]+", text) or not re.search(r"\d", text):
        return None

    if style == "auto":
        style = _guess_style(text)
    if style == "br":
        if text.count(",") > 1:
            return None
        if "." in text and not re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d*)?", text):
            return None
        normalized = text.replace(".", "").replace(",", ".")
    else:
        if text.count(".") > 1:
            return None
        if "," in text and not re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d*)?", text):
            return None
        normalized = text.replace(",", "")
    try:
        result = Decimal(normalized)
    except InvalidOperation:
        return None
    return -result if negative else result


def _guess_style(text: str) -> Literal["br", "us"]:
    last_comma, last_dot = text.rfind(","), text.rfind(".")
    if last_comma == -1 and last_dot == -1:
        return "br"
    if last_comma > last_dot:
        return "br"
    # Apenas ponto(s): "1.234" é milhar BR; "1234.5" ou "1.5" é decimal.
    if last_comma == -1:
        parts = text.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            return "br"
        return "us"
    return "us"


def number_style_evidence(text: str) -> Literal["br", "us", "ambiguous", "none"]:
    """Classifica um texto numérico quanto ao estilo, sem decidir casos ambíguos."""
    t = _NUM_CLEAN.sub("", text).lstrip("-+(").rstrip(")-")
    if not re.fullmatch(r"[\d.,]+", t or "x"):
        return "none"
    has_c, has_d = "," in t, "." in t
    if has_c and has_d:
        return "br" if t.rfind(",") > t.rfind(".") else "us"
    if has_c:
        return "ambiguous" if re.fullmatch(r"\d{1,3}(,\d{3})+", t) else "br"
    if has_d:
        return "ambiguous" if re.fullmatch(r"\d{1,3}(\.\d{3})+", t) else "us"
    return "none"


# --------------------------------------------------------------------------- datas

DATE_FORMATS: dict[str, str] = {
    "dd/mm/yyyy": "%d/%m/%Y",
    "yyyy-mm-dd": "%Y-%m-%d",
    "dd-mm-yyyy": "%d-%m-%Y",
    "dd.mm.yyyy": "%d.%m.%Y",
    "dd/mm/yy": "%d/%m/%y",
    "mm/dd/yyyy": "%m/%d/%Y",
    "yyyy/mm/dd": "%Y/%m/%d",
    "yyyymmdd": "%Y%m%d",
}
# Ordem padrão para o contexto brasileiro: dia antes do mês.
DEFAULT_DATE_ORDER = ["dd/mm/yyyy", "yyyy-mm-dd", "dd-mm-yyyy", "dd.mm.yyyy", "dd/mm/yy", "yyyy/mm/dd"]


def parse_date(value: Any, fmt: str | None = None) -> date | None:
    """Interpreta datas. ``fmt`` é uma chave de ``DATE_FORMATS`` ou ``excel_serial``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        if fmt in (None, "excel_serial") and 1 <= value < 2958466:
            return (_EXCEL_EPOCH + timedelta(days=float(value))).date()
        if fmt == "yyyymmdd":
            value = str(int(value))
        else:
            return None
    text = str(value).strip()
    if not text:
        return None
    # Remove componente de hora: "2024-01-31 00:00:00" / "2024-01-31T10:00"
    text = re.split(r"[ T](?=\d{1,2}:\d{2})", text, maxsplit=1)[0]
    formats = [fmt] if fmt and fmt != "excel_serial" else DEFAULT_DATE_ORDER
    for key in formats:
        pattern = DATE_FORMATS.get(key)
        if not pattern:
            continue
        try:
            parsed = datetime.strptime(text, pattern).date()
        except ValueError:
            continue
        if key == "yyyymmdd" and len(text) != 8:
            continue
        return parsed
    return None


def date_format_evidence(text: str) -> set[str]:
    """Formatos de data compatíveis com o texto (usado na inferência de colunas)."""
    text = re.split(r"[ T](?=\d{1,2}:\d{2})", text.strip(), maxsplit=1)[0]
    matches = set()
    for key, pattern in DATE_FORMATS.items():
        if key == "yyyymmdd" and not re.fullmatch(r"(19|20)\d{6}", text):
            continue
        try:
            datetime.strptime(text, pattern)
        except ValueError:
            continue
        matches.add(key)
    return matches


# --------------------------------------------------------------------------- documentos


def is_valid_cpf(value: Any) -> bool:
    d = digits_only(value)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(d[i]) * (size + 1 - i) for i in range(size))
        check = (total * 10) % 11 % 10
        if check != int(d[size]):
            return False
    return True


def is_valid_cnpj(value: Any) -> bool:
    d = digits_only(value)
    if len(d) != 14 or d == d[0] * 14:
        return False
    weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights2 = [6] + weights1
    for weights, pos in ((weights1, 12), (weights2, 13)):
        total = sum(int(d[i]) * w for i, w in enumerate(weights))
        rest = total % 11
        check = 0 if rest < 2 else 11 - rest
        if check != int(d[pos]):
            return False
    return True


_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$")
_UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}

FORMAT_CHECKS: dict[str, Any] = {
    "cpf": is_valid_cpf,
    "cnpj": is_valid_cnpj,
    "cpf_cnpj": lambda v: is_valid_cpf(v) or is_valid_cnpj(v),
    "email": lambda v: bool(_EMAIL.match(to_text(v))),
    "cep": lambda v: bool(re.fullmatch(r"\d{5}-?\d{3}", to_text(v))),
    "uf": lambda v: to_text(v).upper() in _UFS,
    "digits": lambda v: bool(re.fullmatch(r"\d+", to_text(v))),
    "phone_br": lambda v: len(digits_only(v)) in (10, 11, 12, 13),
}


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    t = strip_accents(to_text(value)).lower()
    if t in {"1", "sim", "s", "true", "verdadeiro", "yes", "y", "x"}:
        return True
    if t in {"0", "nao", "n", "false", "falso", "no"}:
        return False
    return None


def parse_typed(value: Any, data_type: str, *, number_style: NumberStyle = "auto", date_format: str | None = None) -> tuple[Any, bool]:
    """Converte para o tipo canônico. Retorna (valor, ok). Vazio => (None, True)."""
    if is_blank(value):
        return None, True
    if data_type in ("decimal", "money"):
        parsed = parse_decimal(value, number_style)
        return (parsed, parsed is not None)
    if data_type == "integer":
        parsed = parse_decimal(value, number_style)
        if parsed is None or parsed != parsed.to_integral_value():
            return None, False
        return int(parsed), True
    if data_type == "date":
        parsed_date = parse_date(value, date_format)
        return parsed_date, parsed_date is not None
    if data_type == "boolean":
        parsed_bool = parse_bool(value)
        return parsed_bool, parsed_bool is not None
    if data_type == "tax_id":
        d = digits_only(value)
        return (d, len(d) in (11, 14)) if d else (to_text(value), False)
    return to_text(value), True


def mask_value(value: Any, *, kind: str | None = None, max_len: int = 80) -> str:
    """Mascara valores potencialmente sensíveis para exibição em prévias e relatórios."""
    text = to_text(value)
    d = digits_only(text)
    if kind in ("tax_id", "cpf", "cnpj") or (len(d) in (11, 14) and len(d) >= len(text) - 4 and len(d) > 0):
        if len(d) == 11:
            return f"***.{d[3:6]}.***-**"
        if len(d) == 14:
            return f"**.{d[2:5]}.***/{d[8:12]}-**"
    if _EMAIL.match(text):
        user, _, domain = text.partition("@")
        return f"{user[:1]}***@{domain}"
    if kind == "account" and len(text) > 4:
        return "*" * (len(text) - 4) + text[-4:]
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text
