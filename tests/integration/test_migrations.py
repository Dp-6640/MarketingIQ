import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from marketingiq.schema import SCHEMAS, STAGING_TABLES, metadata

APP_ROLE = "miq_app"

pytestmark = pytest.mark.integration


def test_upgrade_creates_schemas_and_tables(migrated):
    insp = inspect(migrated)

    assert set(SCHEMAS) <= set(insp.get_schema_names())
    for schema in ("core", "staging"):
        defined = {table.name for table in metadata.sorted_tables if table.schema == schema}
        assert set(insp.get_table_names(schema=schema)) == defined
    assert {"organizations", "load_batches", "leads", "web_sessions"} <= set(
        insp.get_table_names(schema="core")
    )
    assert set(insp.get_table_names(schema="staging")) == set(STAGING_TABLES)


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
        diff = compare_metadata(ctx, metadata)

    assert diff == []


def test_app_role_can_read_core_but_not_write_or_see_staging(migrated):
    with migrated.connect() as conn:

        def check(sql: str) -> bool:
            return conn.execute(text(sql), {"role": APP_ROLE}).scalar_one()

        assert check("SELECT has_table_privilege(:role, 'core.organizations', 'SELECT')")
        assert not check("SELECT has_table_privilege(:role, 'core.organizations', 'INSERT')")
        assert not check("SELECT has_table_privilege(:role, 'core.load_batches', 'DELETE')")
        assert not check("SELECT has_schema_privilege(:role, 'staging', 'USAGE')")
        assert not check("SELECT has_table_privilege(:role, 'staging.sf_leads', 'SELECT')")
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


def test_every_foreign_key_has_a_supporting_index():
    """Rebuilds delete whole tables. Without an index on a referencing column, Postgres
    checks each deleted row with a full scan of the referencing table: a rebuild of 138,000
    sessions took over five minutes before these indexes existed. Organizations are never
    deleted, so their foreign keys are exempt."""
    missing = []
    for table in metadata.sorted_tables:
        indexed = [tuple(c.name for c in index.columns) for index in table.indexes]
        indexed += [
            tuple(c.name for c in constraint.columns)
            for constraint in table.constraints
            if constraint.__class__.__name__ in ("PrimaryKeyConstraint", "UniqueConstraint")
        ]
        for fk in table.foreign_key_constraints:
            columns = tuple(c.name for c in fk.columns)
            if columns == ("org_id",):
                continue
            if not any(index[: len(columns)] == columns for index in indexed):
                missing.append(f"{table.fullname}.{','.join(columns)}")

    assert missing == []
