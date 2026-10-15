import csv
import shutil
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from marketingiq.ingest.loader import ensure_organization, load_dataset
from synthetic.export import generate

pytestmark = pytest.mark.integration

DIRTY = Path(__file__).parent.parent / "fixtures" / "dirty"


@pytest.fixture(scope="module")
def dataset(tmp_path_factory) -> Path:
    return generate("tiny", 7, tmp_path_factory.mktemp("dataset"))


def rows_in(engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def csv_rows(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def dirty_org(engine) -> None:
    ensure_organization(
        engine,
        slug="dirty-test",
        name="Dirty fixtures",
        reporting_tz="America/Toronto",
        currency="CAD",
        is_synthetic=True,
        data_as_of=None,
    )


def test_a_generated_dataset_loads_completely(migrated, dataset):
    results = load_dataset(migrated, dataset)

    assert {r.status for r in results} == {"loaded"}
    assert sum(r.rows_rejected for r in results) == 0
    by_entity = {r.entity: r for r in results}
    assert rows_in(migrated, "staging.sf_leads") == csv_rows(dataset / "salesforce/leads.csv")
    ga4 = by_entity["ga4_sessions"]
    assert rows_in(migrated, "staging.ga4_sessions") == ga4.rows_loaded
    assert ga4.rows_read == csv_rows(dataset / "ga4/sessions.csv")
    with migrated.connect() as conn:
        org = conn.execute(
            text("SELECT slug, is_synthetic, data_as_of, reporting_tz FROM core.organizations")
        ).one()
        statuses = conn.execute(text("SELECT status, count(*) FROM core.load_batches GROUP BY 1"))
        assert dict(statuses.all()) == {"succeeded": 7}
    assert org == ("synthetic-home-services", True, date(2026, 3, 31), "America/Toronto")


def test_loading_the_same_files_again_changes_nothing(migrated, dataset):
    load_dataset(migrated, dataset)
    leads_before = rows_in(migrated, "staging.sf_leads")

    again = load_dataset(migrated, dataset)

    assert {r.status for r in again} == {"skipped"}
    assert rows_in(migrated, "staging.sf_leads") == leads_before
    assert rows_in(migrated, "core.load_batches") == 7


def test_invalid_rows_are_stored_with_their_error_codes(migrated):
    dirty_org(migrated)

    results = load_dataset(migrated, DIRTY, org_slug="dirty-test")

    assert {r.status for r in results} == {"loaded"}
    with migrated.connect() as conn:
        stored = conn.execute(
            text(
                "SELECT b.source_file, r.row_number, r.errors -> 0 ->> 'code'"
                " FROM core.rejected_rows r JOIN core.load_batches b ON b.id = r.load_batch_id"
            )
        ).all()
    with (DIRTY / "expected_errors.csv").open(encoding="utf-8", newline="") as handle:
        expected = {(r["path"], int(r["row_number"]), r["code"]) for r in csv.DictReader(handle)}
    assert set(stored) == expected
    meta = next(r for r in results if r.entity == "meta_insights_daily")
    assert (meta.rows_loaded, meta.rows_rejected, meta.rows_duplicate) == (2, 7, 1)


def test_a_broken_file_fails_alone_and_is_recorded(migrated, tmp_path):
    dirty_org(migrated)
    folder = tmp_path / "broken"
    shutil.copytree(DIRTY, folder)
    (folder / "salesforce/leads.csv").write_text(
        "Id,Status,IsConverted\n00Q000000000001EAA,New,false\n", encoding="utf-8"
    )

    results = {r.entity: r for r in load_dataset(migrated, folder, org_slug="dirty-test")}

    assert results["sf_leads"].status == "failed"
    assert "CreatedDate" in results["sf_leads"].error
    assert results["sf_events"].status == "loaded"
    with migrated.connect() as conn:
        failed = conn.execute(
            text("SELECT error FROM core.load_batches WHERE status = 'failed'")
        ).scalar_one()
    assert "CreatedDate" in failed


def test_a_folder_without_manifest_needs_a_known_organization(migrated):
    with pytest.raises(LookupError):
        load_dataset(migrated, DIRTY, org_slug="nobody")
    with pytest.raises(ValueError):
        load_dataset(migrated, DIRTY)
