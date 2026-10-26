"""Cada processo (API, worker, CLI) deve registrar todas as tabelas, mesmo importado isoladamente."""

import subprocess
import sys

import pytest

CHECK = (
    "import importlib, sys; importlib.import_module(sys.argv[1]);"
    "from app.infrastructure.database.base import Base;"
    "from sqlalchemy.orm import configure_mappers; configure_mappers();"
    "[fk.column for t in Base.metadata.tables.values() for fk in t.foreign_keys];"
    "print(len(Base.metadata.tables))"
)


@pytest.mark.parametrize("module", ["app.worker", "app.cli", "app.main"])
def test_entrypoint_registers_all_tables(module):
    out = subprocess.run([sys.executable, "-c", CHECK, module], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    assert int(out.stdout.strip().splitlines()[-1]) == 17
