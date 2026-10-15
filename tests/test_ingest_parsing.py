import csv
from pathlib import Path

import pytest

from marketingiq.ingest.parsing import FileError, parse_file
from marketingiq.ingest.rows import ERROR_CODES
from marketingiq.ingest.sources import SOURCES
from marketingiq.ingest.staging import STAGING_TABLES
from synthetic.export import generate

DIRTY = Path(__file__).parent / "fixtures" / "dirty"
BY_ENTITY = {source.entity: source for source in SOURCES}


def expected_errors() -> set[tuple[str, int, str]]:
    with (DIRTY / "expected_errors.csv").open(encoding="utf-8", newline="") as handle:
        return {(r["path"], int(r["row_number"]), r["code"]) for r in csv.DictReader(handle)}


@pytest.fixture(scope="module")
def generated(tmp_path_factory) -> Path:
    return generate("tiny", 7, tmp_path_factory.mktemp("dataset"))


def test_each_invalid_row_gets_its_error_code():
    found = set()
    for source in SOURCES:
        for rejection in parse_file(source, DIRTY / source.path).rejected:
            assert len(rejection.errors) == 1, rejection
            found.add((source.path, rejection.row_number, rejection.errors[0]["code"]))

    assert found == expected_errors()


def test_every_expected_code_is_part_of_the_contract():
    codes = {code for _, _, code in expected_errors()}

    assert codes <= set(ERROR_CODES)
    assert "invalid_value" not in codes  # the catch-all would hide a missing translation


def test_identical_rows_are_counted_as_duplicates_not_errors():
    parsed = parse_file(BY_ENTITY["meta_insights_daily"], DIRTY / "meta/insights_daily.csv")

    assert parsed.duplicates == 1
    assert [number for number, _ in parsed.rows] == [1, 10]
    assert parsed.read == 10


def test_rejections_keep_the_raw_values_and_name_the_column():
    parsed = parse_file(BY_ENTITY["sf_leads"], DIRTY / "salesforce/leads.csv")
    bad_date = next(r for r in parsed.rejected if r.row_number == 3)

    assert bad_date.raw["CreatedDate"] == "yesterday"
    assert bad_date.errors[0]["field"] == "CreatedDate"


def test_values_are_kept_exactly_as_typed():
    parsed = parse_file(BY_ENTITY["sf_leads"], DIRTY / "salesforce/leads.csv")
    cities = {row.city for _, row in parsed.rows}

    # Cleaning cities is the core step's job; staging keeps what the source sent.
    assert "Mississauga ON" in cities


def test_a_missing_required_column_fails_the_whole_file(tmp_path):
    path = tmp_path / "leads.csv"
    path.write_text("Id,Status,IsConverted\n00Q000000000001EAA,New,false\n", encoding="utf-8")

    with pytest.raises(FileError, match="CreatedDate"):
        parse_file(BY_ENTITY["sf_leads"], path)


def test_a_generated_dataset_parses_without_rejections(generated):
    for source in SOURCES:
        parsed = parse_file(source, generated / source.path)
        assert parsed.rejected == [], source.path


def test_generated_ga4_duplicates_match_the_ground_truth(generated):
    parsed = parse_file(BY_ENTITY["ga4_sessions"], generated / "ga4/sessions.csv")
    with (generated / "truth/sessions.csv").open(encoding="utf-8", newline="") as handle:
        exported = sum(1 for r in csv.DictReader(handle) if r["in_ga4_export"] == "true")

    assert len(parsed.rows) == exported
    assert parsed.read == exported + parsed.duplicates


def test_staging_tables_mirror_the_row_models():
    for source in SOURCES:
        columns = {column.name for column in STAGING_TABLES[source.entity].columns}
        assert columns == {"load_batch_id", "source_row", *source.row_model.model_fields}


def test_the_loader_never_reads_ground_truth():
    assert not any(source.path.startswith("truth/") for source in SOURCES)
