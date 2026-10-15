from collections import Counter
from datetime import date, timedelta

import pytest

from synthetic.config import load_config
from synthetic.crm import true_class
from synthetic.entities import Household
from synthetic.generator import World, simulate


@pytest.fixture(scope="module")
def world() -> World:
    return simulate(load_config("tiny"), seed=7)


def _household(customer_type: str = "new") -> Household:
    return Household(
        key=(0,),
        person_key="0" * 16,
        region="gta",
        city="Toronto",
        need="planned_replacement",
        service_line="furnace",
        request="install_replace",
        customer_type=customer_type,
        intent=0.5,
        consent=True,
        device="mobile",
        system_age=10,
        origin_channel="organic_search",
        origin_campaign=None,
        origin_day=date(2026, 1, 1),
    )


@pytest.mark.parametrize(
    ("request_kind", "customer", "expected"),
    [
        ("install_replace", "new", "acquisition"),
        ("sales_general", "new", "acquisition"),
        ("install_replace", "existing", "existing_customer_sales"),
        ("repair_service", "new", "service_demand"),
        ("maintenance", "existing", "service_demand"),
        ("billing", "existing", "non_marketing"),
        ("non_sales_form", "new", "non_marketing"),
        ("spam", "new", "junk"),
    ],
)
def test_true_class_follows_what_the_household_wanted(request_kind, customer, expected):
    assert true_class(_household(customer), request_kind) == expected


def test_leads_fall_inside_the_export_window(world):
    calendar = world.context.calendar

    assert world.leads
    assert all(calendar.in_export_window(lead.created_at) for lead in world.leads)


def test_duplicates_follow_their_original_within_72_hours(world):
    duplicates = [lead for lead in world.leads if lead.duplicate_of is not None]
    assert duplicates

    for duplicate in duplicates:
        original = duplicate.duplicate_of
        assert duplicate.household is original.household
        assert timedelta(0) < duplicate.created_at - original.created_at < timedelta(hours=72)
        assert duplicate.true_class == "junk"
        assert duplicate.appointment is None and duplicate.opportunity is None


def test_resubmissions_come_back_later_as_real_leads(world):
    for lead in (lead for lead in world.leads if lead.resubmission):
        originals = [
            other
            for other in world.leads
            if other.household is lead.household
            and not other.resubmission
            and not other.duplicate_of
        ]
        assert lead.created_at - originals[0].created_at > timedelta(days=10)
        assert lead.true_class != "junk"


def test_test_leads_have_no_household(world):
    tests = [lead for lead in world.leads if lead.is_test]

    assert all(lead.household is None and lead.true_class == "junk" for lead in tests)


def test_lifecycle_events_happen_in_order(world):
    for lead in world.leads:
        if lead.qualified_at is not None:
            assert lead.qualified_at > lead.created_at
        appointment = lead.appointment
        if appointment is not None:
            assert appointment.booked_at >= lead.created_at
            assert appointment.scheduled_for > appointment.booked_at
            if lead.entry_point != "booking" and lead.qualified_at is not None:
                assert appointment.booked_at >= lead.qualified_at
        opportunity = lead.opportunity
        if opportunity is not None:
            assert opportunity.created_at > lead.created_at
            assert opportunity.close_at > opportunity.created_at
            assert opportunity.amount > 0


def test_statuses_describe_the_state_at_data_as_of(world):
    as_of_end = world.context.calendar.as_of_end_utc

    for lead in world.leads:
        opportunity_before = (
            lead.opportunity is not None and lead.opportunity.created_at < as_of_end
        )
        if lead.status == "Converted":
            assert opportunity_before
        if lead.status == "Qualified":
            assert lead.qualified_at is not None and lead.qualified_at < as_of_end
            assert not opportunity_before
        if lead.status == "Unqualified":
            assert lead.qualified_at is None


def test_lead_form_leads_qualify_less_often_than_quote_form_leads(world):
    as_of_end = world.context.calendar.as_of_end_utc
    decided = [
        lead
        for lead in world.leads
        if lead.true_class == "acquisition"
        and lead.duplicate_of is None
        and lead.decided_at is not None
        and lead.decided_at < as_of_end
    ]

    def qualified_share(entry: str) -> float:
        group = [lead for lead in decided if lead.entry_point == entry]
        return sum(lead.qualified_at is not None for lead in group) / len(group)

    assert qualified_share("meta_lead_form") < 0.6 * qualified_share("web_quote_form")


def test_meta_counts_every_native_lead_and_more(world):
    reported = Counter()
    for row in world.meta_days:
        reported[row.campaign] += row.reported_leads
    native = Counter(
        lead.household.origin_campaign
        for lead in world.leads
        if lead.household is not None
        and lead.entry_point in ("meta_lead_form", "meta_messaging_agent")
    )

    for campaign, count in native.items():
        assert reported[campaign] >= 0.95 * count
