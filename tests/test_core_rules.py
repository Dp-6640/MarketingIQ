import tomllib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from marketingiq.core.rules import (
    RULES_PATH,
    CityMatch,
    EvidenceInput,
    LeadKey,
    Page,
    RuleBook,
    Rules,
    find_duplicates,
    load_rulebook,
)

NOON = datetime(2026, 3, 10, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def rules() -> Rules:
    return Rules(load_rulebook())


def lead(**overrides) -> EvidenceInput:
    values = {
        "created_at": NOON,
        "entry_point": "web_quote_form",
        "ga_client_id": None,
        "meta_campaign_id": None,
        "utm_source": None,
        "utm_medium": None,
        "utm_campaign": None,
        "click_id_type": None,
        "lead_source": "Web",
    }
    return EvidenceInput(**(values | overrides))


def test_every_rule_section_is_versioned_and_unverified():
    versions = load_rulebook().versions()

    assert set(versions) == {
        "channels",
        "campaign_mapping",
        "site",
        "geography",
        "salesforce",
        "classification",
        "attribution",
    }
    assert not any(section["verified"] for section in versions.values())


def test_rule_book_rejects_non_canonical_values():
    raw = tomllib.loads(RULES_PATH.read_text(encoding="utf-8"))
    raw["salesforce"]["entry_points"]["Quote Form"] = "web_form"

    with pytest.raises(ValidationError, match="aren't canonical"):
        RuleBook.model_validate(raw)


@pytest.mark.parametrize(
    ("source", "medium", "channel"),
    [
        ("google", "organic", "organic_search"),
        ("google", "cpc", "paid_search"),
        ("facebook", "paid_social", "paid_social"),
        ("(direct)", "(none)", "direct"),
        ("newsletter", "email", "email"),
        ("m.facebook.com", "referral", "organic_social"),
        ("homestars.com", "referral", "referral"),
        ("somewhere", "banner", "other"),
        (" Google ", "CPC", "paid_search"),
    ],
)
def test_channel_grouping(rules, source, medium, channel):
    assert rules.channel(source, medium) == channel


def test_campaign_values_are_case_insensitive_and_placeholders_mean_none(rules):
    assert rules.campaign_value("META_Prospecting_Furnace ") == "meta_prospecting_furnace"
    assert rules.campaign_value("(organic)") is None
    assert rules.campaign_value("") is None
    assert rules.campaign_value(None) is None


@pytest.mark.parametrize(
    ("path", "page"),
    [
        ("/", Page("home")),
        ("/get-a-quote/", Page("quote")),
        ("/heating/furnaces/", Page("service", service_line="furnace")),
        ("/offers/air-conditioner/", Page("offer", service_line="air_conditioner")),
        ("/locations/st-catharines/", Page("location", city="St. Catharines")),
        ("/locations/atlantis/", Page("location")),
        ("/blog/winter-tips/", Page("blog")),
        ("/something-new/", Page("other")),
    ],
)
def test_page_map(rules, path, page):
    assert rules.page(path) == page


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Toronto", CityMatch("Toronto", "gta", "exact")),
        (" Kenora ", CityMatch("Kenora", "northern_other", "normalized")),
        ("Mississauga ON", CityMatch("Mississauga", "gta", "normalized")),
        ("toronto, Ontario", CityMatch("Toronto", "gta", "normalized")),
        ("LONDON", CityMatch("London", "london_windsor", "normalized")),
        ("London", CityMatch("London", "london_windsor", "exact")),  # not "Lond" + "on"
        ("T.O.", CityMatch("Toronto", "gta", "alias")),
        ("St Catharines", CityMatch("St. Catharines", "hamilton_niagara", "alias")),
        ("KW", CityMatch(None, "kw_guelph", "region_only")),
        ("asdf", CityMatch(None, None, "unrecognized")),
        ("", CityMatch(None, None, "blank")),
        (None, CityMatch(None, None, "blank")),
    ],
)
def test_city_normalization(rules, raw, expected):
    assert rules.city(raw) == expected


def test_request_type_prefers_the_crm_field_then_defaults(rules):
    assert rules.request_type("Service & Repair", "web_quote_form", None) == (
        "repair_service",
        "crm_field",
    )
    assert rules.request_type(None, "web_quote_form", None) == (
        "install_replace",
        "entry_point_default",
    )
    assert rules.request_type(None, "meta_lead_form", "lead_form") == (
        "install_replace",
        "campaign",
    )
    assert rules.request_type(None, "phone", None) == ("unknown", "unknown")


def test_customer_type_and_service_line_sources(rules):
    assert rules.customer_type("Yes") == ("existing", "self_reported")
    assert rules.customer_type("No") == ("new", "self_reported")
    assert rules.customer_type(None) == ("unknown", "unknown")
    assert rules.service_line("Heat Pump", "furnace", "furnace") == ("heat_pump", "crm_field")
    assert rules.service_line(None, "furnace", "water_heater") == ("furnace", "form_page")
    assert rules.service_line(None, None, "water_heater") == ("water_heater", "campaign")
    assert rules.service_line(None, None, None) == ("unknown", "unknown")


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"is_test": True, "stage": "invalid", "is_duplicate": True}, ("junk", "test")),
        ({"stage": "invalid", "is_duplicate": True}, ("junk", "invalid")),
        ({"is_duplicate": True, "request_type": "billing"}, ("junk", "duplicate")),
        ({"request_type": "billing"}, ("non_marketing", None)),
        ({"request_type": "maintenance", "customer_type": "existing"}, ("service_demand", None)),
        (
            {"request_type": "install_replace", "customer_type": "existing"},
            ("existing_customer_sales", None),
        ),
        ({"request_type": "install_replace", "customer_type": "unknown"}, ("acquisition", None)),
        ({"request_type": "sales_general", "customer_type": "new"}, ("acquisition", None)),
        ({"request_type": "other"}, ("unknown", None)),
    ],
)
def test_classification_rules_apply_in_order(rules, kwargs, expected):
    values = {
        "request_type": "install_replace",
        "customer_type": "new",
        "stage": "new",
        "is_test": False,
        "is_duplicate": False,
    }

    assert rules.classify(**(values | kwargs)) == expected


def test_a_journey_inside_the_lookback_is_tier_one(rules):
    journey = [NOON - timedelta(days=40), NOON - timedelta(days=3)]

    assert rules.evidence(lead(ga_client_id="1.2"), journey).tier == "T1_journey"


def test_a_journey_outside_the_lookback_falls_through(rules):
    journey = [NOON - timedelta(days=40), NOON + timedelta(hours=1)]
    result = rules.evidence(lead(ga_client_id="1.2", lead_source="Google"), journey)

    assert (result.tier, result.detail) == ("T4_self_reported_channel", "journey_outside_lookback")
    assert rules.evidence(lead(ga_client_id="1.2"), []).detail == "ga_id_unmatched"


def test_platform_native_id_beats_captured_utms(rules):
    result = rules.evidence(
        lead(entry_point="meta_lead_form", meta_campaign_id="1202", utm_campaign="x"), []
    )

    assert result.tier == "T3_platform_native"
    assert result.identifier == ("meta_campaign_id", "1202")


def test_captured_utms_name_the_campaign_but_a_click_id_only_the_channel(rules):
    tagged = rules.evidence(
        lead(utm_source="facebook", utm_medium="paid_social", utm_campaign="Meta_X"), []
    )
    click_only = rules.evidence(lead(click_id_type="gclid"), [])

    assert (tagged.tier, tagged.identifier, tagged.channel) == (
        "T2_captured_source",
        ("utm_campaign", "meta_x"),
        "paid_social",
    )
    assert (click_only.tier, click_only.identifier, click_only.channel) == (
        "T2_captured_source",
        None,
        "paid_search",
    )


def test_self_reported_channel_and_no_evidence(rules):
    assert rules.evidence(lead(entry_point="phone", lead_source="Google"), []).tier == (
        "T4_self_reported_channel"
    )
    assert rules.evidence(lead(entry_point="phone", lead_source="Phone"), []).tier == "T5_none"


def test_duplicates_attach_to_the_first_lead_of_a_window():
    hours = [0, 48, 80, 100]
    leads = [LeadKey(f"L{h}", "p1", NOON + timedelta(hours=h), False) for h in hours]
    leads += [
        LeadKey("T", "p1", NOON + timedelta(hours=1), True),  # test leads are ignored
        LeadKey("N", None, NOON, False),  # no person key, no dedupe
    ]

    duplicates = find_duplicates(leads, timedelta(hours=72))

    # 80h is past the first window, so it starts a new one; 100h falls inside it.
    assert duplicates == {"L48": "L0", "L100": "L80"}
