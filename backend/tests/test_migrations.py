"""Migrations Alembic: aplicáveis do zero, reversíveis e alinhadas aos modelos (somente PostgreSQL)."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

URL = os.environ.get("DDI_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL.startswith("postgresql"), reason="requer DDI_TEST_DATABASE_URL (PostgreSQL)")


def test_upgrade_downgrade_and_no_drift(monkeypatch):
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext

    from app.core.config import get_settings
    from app.infrastructure.database.models import Base

    base = make_url(URL)
    name = f"ddi_mig_{uuid.uuid4().hex[:8]}"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    target = base.set(database=name).render_as_string(hide_password=False)
    try:
        monkeypatch.setattr(get_settings(), "database_url", target)
        cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "migrations"))
        command.upgrade(cfg, "head")
        engine = create_engine(target)
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
            assert diff == [], diff
            fk = conn.execute(text("select 1 from pg_constraint where conname = "
                                   "'fk_dataset_profiles_current_version_id_dataset_profile_versions'")).scalar()
            assert fk == 1
        command.downgrade(cfg, "base")
        with engine.connect() as conn:
            tables = conn.execute(text("select count(*) from information_schema.tables where table_schema='public' "
                                       "and table_name <> 'alembic_version'")).scalar()
            assert tables == 0
        engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
