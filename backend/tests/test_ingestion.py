import io
import zipfile
from pathlib import Path

import openpyxl
import pytest

from app.core.errors import FileRejected
from app.domain.ingestion.detect import detect_format
from app.domain.ingestion.inspect import inspect_file
from app.domain.ingestion.readers import ReadOptions, detect_delimiter

LIMIT = 400 * 1024 * 1024


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _inspect(path: Path, **opts):
    return inspect_file(path, detect_format(path, path.name, max_uncompressed=LIMIT), ReadOptions(**opts))


def test_valid_csv_structure(demo_files):
    r = _inspect(demo_files["contas_pagar_2024_09.csv"])
    assert r.options["delimiter"] == ";" and r.options["encoding"] == "utf-8" and r.options["header_row"] == 1
    assert r.row_count == 61
    types = {c["name"]: c["inferred_type"] for c in r.columns}
    assert types["Valor"] == "decimal" and types["Emissão"] == "date" and types["CNPJ"] == "tax_id"
    assert next(c for c in r.columns if c["name"] == "Valor")["number_style"] == "br"
    assert r.ambiguities == []


def test_preview_masks_tax_ids(demo_files):
    r = _inspect(demo_files["contas_pagar_2024_09.csv"])
    idx = [c["name"] for c in r.columns].index("CNPJ")
    assert all("*" in row[idx] for row in r.preview if row[idx])


def test_alternative_delimiter_and_cp1252(demo_files):
    r = _inspect(demo_files["fornecedores_cp1252.csv"])
    assert r.options["delimiter"] == ","
    assert r.options["encoding"] == "cp1252"
    assert any(w["code"] == "encoding_guess" for w in r.warnings)
    assert r.columns[1]["name"] == "Razão Social"  # acentos preservados


def test_utf8_bom_and_tab_delimiter(tmp_path):
    p = _write(tmp_path, "a.tsv", "﻿Documento\tValor\nA1\t10,00\nA2\t20,00\n".encode())
    r = _inspect(p)
    assert r.options["encoding"] == "utf-8-sig" and r.options["delimiter"] == "\t"
    assert r.columns[0]["name"] == "Documento"


def test_xlsx_multiple_sheets_title_rows_and_merged(demo_files):
    r = _inspect(demo_files["contas_pagar_alternativo_2024_09.xlsx"])
    assert r.options["sheet"] == "Lançamentos"   # aba com mais dados
    assert r.options["header_row"] == 3           # duas linhas de título ignoradas
    assert {a["code"] for a in r.ambiguities} == {"multiple_sheets"}
    codes = {w["code"] for w in r.warnings}
    assert {"merged_cells", "title_rows"} <= codes
    assert r.row_count == 30


def test_xlsx_explicit_sheet_selection(demo_files):
    r = _inspect(demo_files["contas_pagar_alternativo_2024_09.xlsx"], sheet="Instruções")
    assert r.options["sheet"] == "Instruções"
    with pytest.raises(FileRejected):
        _inspect(demo_files["contas_pagar_alternativo_2024_09.xlsx"], sheet="Inexistente")


def test_empty_file_rejected(tmp_path):
    with pytest.raises(FileRejected) as e:
        detect_format(_write(tmp_path, "vazio.csv", b""), "vazio.csv", max_uncompressed=LIMIT)
    assert e.value.code == "empty_file"


def test_blank_csv_rejected(tmp_path):
    p = _write(tmp_path, "branco.csv", b"\n\n;;\n")
    with pytest.raises(FileRejected) as e:
        _inspect(p)
    assert e.value.code == "empty_file"


def test_corrupted_xlsx_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<x/>")
        zf.writestr("xl/workbook.xml", "não é xml válido")
    p = _write(tmp_path, "quebrado.xlsx", buf.getvalue())
    with pytest.raises(FileRejected) as e:
        _inspect(p)
    assert e.value.code == "corrupted_file"


@pytest.mark.parametrize(("name", "content", "code"), [
    ("planilha.csv", b"%PDF-1.4 conteudo", "content_mismatch"),
    ("planilha.xlsx", b"Documento;Valor\nA;1\n", "content_mismatch"),
    ("planilha.csv", b"MZ\x90\x00binario", "content_mismatch"),
    ("planilha.csv", b"PK\x03\x04qualquer", "content_mismatch"),
    ("planilha.xlsx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1antigo", "unsupported_format"),
    ("planilha.exe", b"Documento;Valor\n", "unsupported_extension"),
    ("dados.csv", b"a\x00b\x00c\x00" * 50, "content_mismatch"),
])
def test_extension_content_mismatch(tmp_path, name, content, code):
    with pytest.raises(FileRejected) as e:
        detect_format(_write(tmp_path, name, content), name, max_uncompressed=LIMIT)
    assert e.value.code == code


def test_macro_enabled_workbook_rejected(tmp_path, demo_files):
    src = demo_files["erp_titulos_2024_09.csv"]
    wb = openpyxl.Workbook()
    wb.active.append(["a"])
    base = tmp_path / "base.xlsx"
    wb.save(base)
    out = tmp_path / "macro.xlsx"
    with zipfile.ZipFile(base) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item))
        zout.writestr("xl/vbaProject.bin", src.read_bytes())
    with pytest.raises(FileRejected) as e:
        detect_format(out, out.name, max_uncompressed=LIMIT)
    assert e.value.code == "macro_rejected"


def test_decompression_bomb_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<x/>")
        zf.writestr("xl/workbook.xml", "<x/>")
        zf.writestr("xl/worksheets/sheet1.xml", "0" * 5_000_000)
    p = _write(tmp_path, "bomba.xlsx", buf.getvalue())
    with pytest.raises(FileRejected) as e:
        detect_format(p, p.name, max_uncompressed=LIMIT)
    assert e.value.code == "decompression_limit"


def test_header_with_known_column_names_wins_over_text_row(tmp_path):
    content = "Relatório A;Relatório B;Relatório C\nFornecedor;Vencimento;Valor\nX;10/01/2024;1,00\nW;11/01/2024;2,00\n"
    r = _inspect(_write(tmp_path, "h.csv", content.encode()))
    assert r.options["header_row"] == 2
    assert not any(a["code"] == "ambiguous_header" for a in r.ambiguities)


def test_ambiguous_header_is_reported_not_silently_decided(tmp_path):
    content = "Alfa;Beta;Gama\nDelta;Epsilon;Zeta\nEta;Teta;Iota\nKapa;Lambda;Mi\n"
    r = _inspect(_write(tmp_path, "amb.csv", content.encode()))
    amb = next(a for a in r.ambiguities if a["code"] == "ambiguous_header")
    assert 1 in amb["options"] and 2 in amb["options"]
    # O usuário pode confirmar explicitamente a linha do cabeçalho
    r2 = _inspect(_write(tmp_path, "amb2.csv", content.encode()), header_row=2)
    assert [c["name"] for c in r2.columns] == ["Delta", "Epsilon", "Zeta"]
    assert r2.row_count == 2


def test_duplicate_and_empty_columns_are_renamed_and_reported(tmp_path):
    r = _inspect(_write(tmp_path, "dup.csv", b"Valor;Valor;;Doc\n1;2;3;A\n4;5;6;B\n"))
    assert [c["name"] for c in r.columns] == ["Valor", "Valor (2)", "Coluna 3", "Doc"]
    codes = [w["code"] for w in r.warnings]
    assert "duplicate_column" in codes and "empty_header" in codes


def test_malformed_rows_detected(tmp_path):
    r = _inspect(_write(tmp_path, "mal.csv", b"a;b;c\n1;2;3\n1;2\n1;2;3;4\n"))
    assert r.malformed_rows["count"] == 2
    assert [e["row"] for e in r.malformed_rows["examples"]] == [3, 4]


def test_ambiguous_delimiter_detected():
    sample = "a,b;c\n1,2;3\n4,5;6\n"
    _, scored, ambiguous = detect_delimiter(sample)
    assert ambiguous and {s["delimiter"] for s in scored[:2]} == {",", ";"}


def test_us_date_format_flagged(tmp_path):
    r = _inspect(_write(tmp_path, "us.csv", b"Doc;Data\nA;01/31/2024\nB;12/25/2024\n"))
    col = r.columns[1]
    assert col["date_format"] == "mm/dd/yyyy"
    assert any(w["code"] == "us_date_format" for w in r.warnings)
