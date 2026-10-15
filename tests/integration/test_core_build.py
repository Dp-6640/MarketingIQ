"""The core build, checked against the generator's ground truth."""

import csv
from pathlib import Path

import pytest
from sqlalchemy import text

from marketingiq.core.build import build_core
from marketingiq.ingest.loader import load_dataset
from synthetic.export import generate

pytestmark = pytest.mark.integration

ORG = "synthetic-home-services"


@pytest.fixture(scope="module")
def built(migrated_module, tmp_path_factory):
    dataset = generate("tiny", 7, tmp_path_factory.mktemp("dataset"))
    load_dataset(migrated_module, dataset)
    result = build_core(migrated_module, ORG)
    return migrated_module, dataset, result


def rows(engine, sql: str, **params) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql), params)]


def scalar(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def truth(dataset: Path, name: str) -> list[dict[str, str]]:
    with (dataset / "truth" / f"{name}.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def classes(engine) -> dict[str, str]:
    return dict(rows(engine, "SELECT source_id, lead_class FROM core.leads"))


def test_duplicates_match_the_ground_truth(built):
    engine, dataset, _ = built
    found = set(
        rows(
            engine,
            "SELECT d.source_id, o.source_id FROM core.leads d"
            " JOIN core.leads o ON o.id = d.duplicate_of",
        )
    )

    expected = {
        (r["lead_id"], r["duplicate_of"]) for r in truth(dataset, "journeys") if r["duplicate_of"]
    }
    assert found == expected
    assert found  # the tiny world does contain duplicates


def test_test_leads_and_spam_become_junk(built):
    engine, dataset, _ = built
    junk = dict(
        rows(engine, "SELECT source_id, junk_reason FROM core.leads WHERE lead_class = 'junk'")
    )

    for row in truth(dataset, "journeys"):
        if row["is_test"] == "true":
            assert junk[row["lead_id"]] == "test"
        elif row["true_class"] == "junk" and not row["duplicate_of"]:
            assert junk[row["lead_id"]] == "invalid"  # spam, marked by its CRM status


def test_billing_and_repair_leads_never_count_as_acquisition(built):
    engine, dataset, _ = built
    classified = classes(engine)
    request = {r["household_id"]: r["request"] for r in truth(dataset, "households")}
    not_sales = ("billing", "customer_service", "repair_service", "maintenance")

    leaked = [
        row["lead_id"]
        for row in truth(dataset, "journeys")
        if row["household_id"]
        and request[row["household_id"]] in not_sales
        and classified[row["lead_id"]] == "acquisition"
    ]
    assert leaked == []


def test_only_non_sales_forms_sent_through_the_quote_form_leak_into_acquisition(built):
    """Known limitation of the U-20 default: the quote form has no request-type field, so a
    nomination sent through it looks like a quote request. Only its free-text message
    (never read, by design) would tell them apart."""
    engine, dataset, _ = built
    leads = {
        source_id: (entry_point, request_source)
        for source_id, entry_point, request_source in rows(
            engine,
            "SELECT source_id, entry_point, request_type_source FROM core.leads"
            " WHERE lead_class = 'acquisition'",
        )
    }
    request = {r["household_id"]: r["request"] for r in truth(dataset, "households")}
    sales = ("acquisition", "existing_customer_sales")

    leaks = [
        (request[row["household_id"]], *leads[row["lead_id"]])
        for row in truth(dataset, "journeys")
        if row["lead_id"] in leads and row["true_class"] not in sales
    ]
    assert set(leaks) <= {("non_sales_form", "web_quote_form", "entry_point_default")}
    assert len(leaks) / len(leads) < 0.03


def test_acquisition_classification_is_precise(built):
    engine, dataset, _ = built
    classified = classes(engine)
    true_class = {row["lead_id"]: row["true_class"] for row in truth(dataset, "journeys")}

    acquisition = [lead for lead, c in classified.items() if c == "acquisition"]
    sales = ("acquisition", "existing_customer_sales")
    precision = sum(true_class[lead] in sales for lead in acquisition) / len(acquisition)
    really_acquisition = [lead for lead, c in true_class.items() if c == "acquisition"]
    recall = sum(classified[lead] == "acquisition" for lead in really_acquisition) / len(
        really_acquisition
    )

    # Nearly every lead classified as acquisition really asked to buy something (new or
    # existing customer: the quote form can't tell them apart). Some real acquisition leads
    # land in `unknown` because no request type was recorded (phone, chat, Messenger).
    assert precision > 0.97
    assert recall > 0.75


def test_recognized_cities_resolve_to_the_true_region(built):
    engine, dataset, _ = built
    household_region = {r["household_id"]: r["region"] for r in truth(dataset, "households")}
    lead_household = {r["lead_id"]: r["household_id"] for r in truth(dataset, "journeys")}
    regions = rows(engine, "SELECT source_id, region FROM core.leads WHERE region IS NOT NULL")

    assert regions
    for lead, region in regions:
        if lead_household[lead]:  # test leads belong to no household
            assert region == household_region[lead_household[lead]]


def test_every_first_lead_has_one_evidence_tier_and_duplicates_none(built):
    engine, _, _ = built

    assert (
        scalar(
            engine,
            "SELECT count(*) FROM core.leads"
            " WHERE (duplicate_of IS NULL) = (evidence_tier IS NULL)",
        )
        == 0
    )


def test_tier_one_leads_have_a_session_inside_the_lookback(built):
    engine, _, _ = built

    without_journey = scalar(
        engine,
        "SELECT count(*) FROM core.leads l WHERE l.evidence_tier = 'T1_journey' AND NOT EXISTS ("
        " SELECT 1 FROM core.web_sessions s WHERE s.org_id = l.org_id"
        " AND s.user_pseudo_id = l.ga_client_id"
        " AND s.started_at BETWEEN l.created_at - interval '30 days' AND l.created_at)",
    )
    assert scalar(engine, "SELECT count(*) FROM core.leads WHERE evidence_tier = 'T1_journey'") > 0
    assert without_journey == 0


def test_platform_native_leads_are_meta_leads_with_a_campaign_id(built):
    engine, _, _ = built

    found = rows(
        engine,
        "SELECT DISTINCT entry_point, meta_campaign_source_id IS NOT NULL FROM core.leads"
        " WHERE evidence_tier = 'T3_platform_native'",
    )
    assert set(found) <= {("meta_lead_form", True), ("meta_messaging_agent", True)}
    assert found


def test_unmapped_campaign_has_spend_but_its_visits_stay_unlinked(built):
    engine, _, result = built

    campaign = rows(
        engine,
        "SELECT key, in_mapping_sheet, has_spend_feed FROM core.campaigns"
        " WHERE platform_campaign_id = '120200000000000111'",
    )
    linked = scalar(
        engine,
        "SELECT count(*) FROM core.web_sessions"
        " WHERE campaign_value = 'meta_prospecting_summer_test' AND campaign_id IS NOT NULL",
    )
    assert campaign == [("meta:120200000000000111", False, True)]
    assert linked == 0
    assert list(result.summary["sessions"]["unmapped_campaign_values"]) == [
        "meta_prospecting_summer_test"
    ]


def test_utm_case_variants_still_link_to_their_campaign(built):
    engine, _, _ = built

    variants = scalar(
        engine,
        "SELECT count(*) FROM staging.ga4_sessions WHERE campaign <> lower(campaign)",
    )
    assert variants > 0  # the generator types some UTMs in a different case
    assert (
        scalar(
            engine,
            "SELECT count(*) FROM core.web_sessions s JOIN core.campaigns c ON c.id = s.campaign_id"
            " WHERE s.campaign_value <> c.utm_campaign",
        )
        == 0
    )


def test_appointments_and_opportunities_link_to_their_leads(built):
    engine, _, _ = built

    assert scalar(engine, "SELECT count(*) FROM core.appointments WHERE lead_id IS NULL") == 0
    assert scalar(engine, "SELECT count(*) FROM core.opportunities WHERE lead_id IS NULL") == 0
    mismatched = scalar(
        engine,
        "SELECT count(*) FROM core.opportunities o JOIN core.leads l ON l.id = o.lead_id"
        " WHERE l.converted_opportunity_source_id <> o.source_id",
    )
    assert mismatched == 0


def test_the_meta_time_zone_mismatch_is_reported(built):
    _, _, result = built

    assert result.summary["timezones"] == {
        "reporting": "America/Toronto",
        "meta_accounts": ["America/Los_Angeles"],
        "mismatch": True,
    }


def test_each_build_records_its_batches_and_unverified_rules(built):
    engine, _, result = built
    batches, rule_versions = rows(
        engine, "SELECT batches, rules FROM core.build_runs WHERE id = :id", id=result.run_id
    )[0]

    assert set(batches) == {
        "meta_insights_daily",
        "ga4_sessions",
        "sf_leads",
        "sf_events",
        "sf_opportunities",
        "campaign_mapping_sheet",
        "annotations",
    }
    assert rule_versions["salesforce"]["verified"] is False


def test_rebuilding_gives_the_same_result(built):
    engine, _, first = built
    tables = ("campaigns", "web_sessions", "leads", "appointments", "opportunities")

    def counts():
        return {name: scalar(engine, f"SELECT count(*) FROM core.{name}") for name in tables}

    before = counts()
    second = build_core(engine, ORG)

    assert counts() == before
    assert second.summary == first.summary
    assert second.run_id != first.run_id


def test_the_app_role_can_read_the_core_model(built):
    engine, _, _ = built

    assert scalar(engine, "SELECT has_table_privilege('miq_app', 'core.leads', 'SELECT')")
    assert not scalar(engine, "SELECT has_table_privilege('miq_app', 'core.leads', 'DELETE')")
