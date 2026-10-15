import csv
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from synthetic.__main__ import main
from synthetic.export import generate
from synthetic.recording import salesforce_id

TORONTO = ZoneInfo("America/Toronto")
SOURCE_FILES = (
    "meta/insights_daily.csv",
    "ga4/sessions.csv",
    "salesforce/leads.csv",
    "salesforce/events.csv",
    "salesforce/opportunities.csv",
    "clarity/page_daily.csv",
    "annotations.csv",
    "reference/campaign_mappings.csv",
)
TRUTH_FILES = (
    "truth/households.csv",
    "truth/sessions.csv",
    "truth/journeys.csv",
    "truth/scenarios.json",
)
PERSONAL_DATA_COLUMNS = {
    "FirstName",
    "LastName",
    "Name",
    "Email",
    "Phone",
    "MobilePhone",
    "Street",
    "Address",
    "PostalCode",
    "Message",
    "Description",
    "Comments",
}


@pytest.fixture(scope="module")
def dataset(tmp_path_factory) -> Path:
    return generate("tiny", 7, tmp_path_factory.mktemp("synthetic"))


def read(folder: Path, name: str) -> list[dict[str, str]]:
    with (folder / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def header(folder: Path, name: str) -> list[str]:
    with (folder / name).open(encoding="utf-8", newline="") as handle:
        return next(csv.reader(handle))


def hashes(folder: Path) -> dict[str, str]:
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def test_same_seed_writes_byte_identical_files(tmp_path):
    first = generate("tiny", 11, tmp_path / "a")
    second = generate("tiny", 11, tmp_path / "b")

    assert hashes(first) == hashes(second)


def test_a_different_seed_changes_the_data(tmp_path, dataset):
    other = generate("tiny", 8, tmp_path)

    assert hashes(other)["salesforce/leads.csv"] != hashes(dataset)["salesforce/leads.csv"]


def test_manifest_matches_the_files(dataset):
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    on_disk = hashes(dataset)

    assert manifest["synthetic"] is True
    assert set(manifest["files"]) == set(SOURCE_FILES) | set(TRUTH_FILES)
    for path, info in manifest["files"].items():
        assert info["sha256"] == on_disk[path]
        if info["rows"] is not None:
            assert info["rows"] == len(read(dataset, path))


def test_no_file_has_personal_data_columns(dataset):
    for name in (*SOURCE_FILES, *TRUTH_FILES):
        if name.endswith(".csv"):
            assert not PERSONAL_DATA_COLUMNS & set(header(dataset, name)), name


def test_truth_columns_never_appear_in_source_files(dataset):
    truth_only = {"need", "intent", "true_class", "household_id", "retargeted"}

    for name in SOURCE_FILES:
        assert not truth_only & set(header(dataset, name)), name


def test_salesforce_ids_are_well_formed_and_unique(dataset):
    assert salesforce_id("00Q", 1) == "00Q000000000001EAA"
    for name, prefix in (
        ("salesforce/leads.csv", "00Q"),
        ("salesforce/events.csv", "00U"),
        ("salesforce/opportunities.csv", "006"),
    ):
        ids = [row["Id"] for row in read(dataset, name)]
        assert ids
        assert len(set(ids)) == len(ids)
        assert all(len(i) == 18 and i.startswith(prefix) for i in ids)


def test_salesforce_references_resolve(dataset):
    leads = read(dataset, "salesforce/leads.csv")
    lead_ids = {row["Id"] for row in leads}
    opportunity_ids = {row["Id"] for row in read(dataset, "salesforce/opportunities.csv")}
    converted = [row["ConvertedOpportunityId"] for row in leads if row["ConvertedOpportunityId"]]

    assert {row["WhoId"] for row in read(dataset, "salesforce/events.csv")} <= lead_ids
    assert sorted(converted) == sorted(opportunity_ids)  # each opportunity from exactly one lead
    for row in leads:
        assert (row["IsConverted"] == "true") == bool(row["ConvertedOpportunityId"])


def test_records_fall_inside_the_export_window(dataset):
    start = datetime(2026, 1, 1, tzinfo=TORONTO)
    end = datetime(2026, 4, 1, tzinfo=TORONTO)

    assert all(start <= utc(r["CreatedDate"]) < end for r in read(dataset, "salesforce/leads.csv"))
    sessions = read(dataset, "ga4/sessions.csv")
    assert all(start <= utc(r["session_start_utc"]) < end for r in sessions)
    meta_days = {date.fromisoformat(r["date"]) for r in read(dataset, "meta/insights_daily.csv")}
    assert min(meta_days) >= date(2026, 1, 1)
    assert max(meta_days) <= date(2026, 3, 31)


def test_meta_rows_and_mapping_sheet(dataset):
    rows = read(dataset, "meta/insights_daily.csv")
    mapped = {
        row["platform_campaign_id"] for row in read(dataset, "reference/campaign_mappings.csv")
    }

    assert all(0 <= int(r["inline_link_clicks"]) <= int(r["impressions"]) for r in rows)
    assert all(float(r["spend"]) > 0 for r in rows)
    assert {r["account_timezone"] for r in rows} == {"America/Los_Angeles"}
    unmapped = {r["campaign_id"] for r in rows} - mapped
    assert unmapped == {"120200000000000111"}  # the summer test campaign (S09)


def test_captured_ga_client_ids_mostly_match_exported_sessions(dataset):
    pseudo_ids = {row["user_pseudo_id"] for row in read(dataset, "ga4/sessions.csv")}
    captured = [
        r["GA_Client_Id__c"] for r in read(dataset, "salesforce/leads.csv") if r["GA_Client_Id__c"]
    ]

    assert captured
    # Some journeys started before the export window, so not every id has exported sessions.
    assert sum(c in pseudo_ids for c in captured) / len(captured) > 0.8


def test_capture_outage_blanks_hidden_fields(dataset):
    hidden = (
        "UTM_Source__c",
        "UTM_Campaign__c",
        "Click_Id_Type__c",
        "GA_Client_Id__c",
        "Form_Page_Path__c",
    )
    during = [
        row
        for row in read(dataset, "salesforce/leads.csv")
        if date(2026, 3, 10)
        <= utc(row["CreatedDate"]).astimezone(TORONTO).date()
        <= date(2026, 3, 15)
        and row["Entry_Point__c"] in ("Quote Form", "Callback Form", "Booking", "Web Chat")
    ]

    assert during
    assert all(not row[field] for row in during for field in hidden)


def test_truth_describes_every_lead(dataset):
    lead_ids = [row["Id"] for row in read(dataset, "salesforce/leads.csv")]
    journeys = read(dataset, "truth/journeys.csv")
    classes = {"acquisition", "existing_customer_sales", "service_demand", "non_marketing", "junk"}

    assert [row["lead_id"] for row in journeys] == lead_ids
    assert {row["true_class"] for row in journeys} <= classes


def test_duplicates_share_the_person_key_of_an_earlier_lead(dataset):
    leads = {row["Id"]: row for row in read(dataset, "salesforce/leads.csv")}
    duplicates = [row for row in read(dataset, "truth/journeys.csv") if row["duplicate_of"]]

    assert duplicates
    for row in duplicates:
        duplicate, original = leads[row["lead_id"]], leads[row["duplicate_of"]]
        assert duplicate["Person_Key__c"] == original["Person_Key__c"]
        gap = utc(duplicate["CreatedDate"]) - utc(original["CreatedDate"])
        assert 0 < gap.total_seconds() < 72 * 3600


def test_cli_writes_a_dataset(tmp_path, capsys):
    assert main(["generate", "--config", "tiny", "--seed", "3", "--out", str(tmp_path)]) == 0

    assert (tmp_path / "tiny-seed-3" / "manifest.json").exists()
    assert "synthetic, seed 3" in capsys.readouterr().out


def test_refuses_to_overwrite_a_folder_it_did_not_create(tmp_path):
    foreign = tmp_path / "tiny-seed-5"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(FileExistsError):
        generate("tiny", 5, tmp_path)
    assert (foreign / "notes.txt").exists()


def test_regenerating_replaces_its_own_output(tmp_path):
    folder = generate("tiny", 5, tmp_path)
    (folder / "stale.csv").write_text("old", encoding="utf-8")

    generate("tiny", 5, tmp_path)

    assert not (folder / "stale.csv").exists()
