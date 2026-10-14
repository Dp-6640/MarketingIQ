import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from marketingiq.models import SCHEMAS, Base

pytestmark = pytest.mark.integration

APP_ROLE = "miq_app"


def _reset(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {', '.join(SCHEMAS)} CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS public.alembic_version"))


@pytest.fixture
def alembic_cfg(test_engine) -> Config:
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = test_engine.url.render_as_string(hide_password=False)
    cfg.attributes["app_db_role"] = APP_ROLE
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture
def migrated(test_engine, alembic_cfg):
    _reset(test_engine)
    command.upgrade(alembic_cfg, "head")
    yield test_engine
    _reset(test_engine)


def test_upgrade_creates_schemas_and_tables(migrated):
    insp = inspect(migrated)

    assert set(SCHEMAS) <= set(insp.get_schema_names())
    assert set(insp.get_table_names(schema="core")) == {
        "organizations",
        "load_batches",
        "rejected_rows",
    }


def test_downgrade_and_upgrade_round_trip(migrated, alembic_cfg):
    command.downgrade(alembic_cfg, "base")
    assert not set(SCHEMAS) & set(inspect(migrated).get_schema_names())

    command.upgrade(alembic_cfg, "head")
    assert "organizations" in inspect(migrated).get_table_names(schema="core")


def test_models_match_migrations(migrated):
    def include_name(name, type_, parent_names):
        return name in SCHEMAS if type_ == "schema" else True

    with migrated.connect() as conn:
        ctx = MigrationContext.configure(
            conn, opts={"include_schemas": True, "include_name": include_name}
        )
        diff = compare_metadata(ctx, Base.metadata)

    assert diff == []


def test_app_role_can_read_core_but_not_write_or_see_staging(migrated):
    with migrated.connect() as conn:

        def check(sql: str) -> bool:
            return conn.execute(text(sql), {"role": APP_ROLE}).scalar_one()

        assert check("SELECT has_table_privilege(:role, 'core.organizations', 'SELECT')")
        assert not check("SELECT has_table_privilege(:role, 'core.organizations', 'INSERT')")
        assert not check("SELECT has_table_privilege(:role, 'core.load_batches', 'DELETE')")
        assert not check("SELECT has_schema_privilege(:role, 'staging', 'USAGE')")
        assert check("SELECT has_schema_privilege(:role, 'mart', 'USAGE')")


def test_succeeded_file_cannot_be_loaded_twice(migrated):
    with migrated.begin() as conn:
        org_id = conn.execute(
            text(
                "INSERT INTO core.organizations (slug, name, reporting_tz, currency, is_synthetic)"
                " VALUES ('demo', 'Demo', 'America/Toronto', 'CAD', true) RETURNING id"
            )
        ).scalar_one()
        insert_batch = text(
            "INSERT INTO core.load_batches (org_id, source_system, entity, source_file,"
            " file_sha256, status) VALUES (:org, 'ga4', 'stg_ga4_sessions', 'f.csv', :sha, :status)"
        )
        # A failed attempt doesn't block a retry of the same file.
        conn.execute(insert_batch, {"org": org_id, "sha": "a" * 64, "status": "failed"})
        conn.execute(insert_batch, {"org": org_id, "sha": "a" * 64, "status": "succeeded"})

    with pytest.raises(Exception, match="uq_load_batches_succeeded_file"), migrated.begin() as conn:
        conn.execute(insert_batch, {"org": org_id, "sha": "a" * 64, "status": "succeeded"})
