from collections import Counter
from datetime import date, timedelta

import pytest

from synthetic.config import WEB_ENTRY_POINTS, load_config
from synthetic.generator import World, simulate
from synthetic.traffic import EVENT_FOR_ENTRY


@pytest.fixture(scope="module")
def world() -> World:
    return simulate(load_config("tiny"), seed=7)


def test_journeys_are_ordered_and_start_from_the_origin(world):
    visited = [h for h in world.households if h.sessions]
    assert visited

    for household in visited:
        starts = [s.start for s in household.sessions]
        assert starts == sorted(starts)
        first = household.sessions[0]
        assert first.channel == household.origin_channel
        if household.origin_channel == "meta":
            assert first.campaign == household.origin_campaign
        assert {s.pseudo_id for s in household.sessions} == {household.pseudo_id}


def test_website_leads_happen_on_or_after_the_last_visit_with_its_event(world):
    web_leads = [h for h in world.households if h.converts and h.entry_point in WEB_ENTRY_POINTS]
    assert web_leads

    for household in web_leads:
        last = household.sessions[-1]
        assert household.lead_at >= last.start
        assert getattr(last, EVENT_FOR_ENTRY[household.entry_point]) == 1


def test_offline_households_never_visit_the_website(world):
    offline = [h for h in world.households if h.origin_channel == "offline"]
    assert offline
    assert all(not h.sessions and h.pseudo_id is None for h in offline)


def test_meta_native_leads_have_no_website_visits(world):
    native = [
        h for h in world.households if h.entry_point in ("meta_lead_form", "meta_messaging_agent")
    ]
    assert native

    for household in native:
        assert not household.sessions
        tactic = world.context.campaigns[household.origin_campaign].tactic
        assert tactic == ("lead_form" if household.entry_point == "meta_lead_form" else "messaging")


def test_retargeting_reaches_only_consenting_visitors_before_their_lead(world):
    retargeted = [h for h in world.households if h.retargeted]
    assert retargeted

    for household in retargeted:
        assert household.consent
        clicks = [s for s in household.sessions if s.campaign == "meta_retargeting_all"]
        assert clicks
        assert all(click.start > household.sessions[0].start for click in clicks)
        if household.converts:
            assert all(click.start < household.lead_at for click in clicks)


def test_retargeting_prefers_high_intent_households(world):
    visited = [h for h in world.households if h.sessions and h.consent]
    retargeted = [h for h in visited if h.retargeted]

    def mean_intent(households):
        return sum(h.intent for h in households) / len(households)

    assert mean_intent(retargeted) > mean_intent(visited)


def test_meta_rows_respect_dates_and_click_counts(world):
    by_campaign = Counter(d.campaign for d in world.meta_days)
    assert set(by_campaign) == {
        c.key for c in world.context.config.campaigns if c.platform == "meta"
    }

    summer = [d.day for d in world.meta_days if d.campaign == "meta_prospecting_summer_test"]
    assert min(summer) == date(2026, 2, 15)
    for meta_day in world.meta_days:
        assert 0 <= meta_day.clicks <= meta_day.impressions
        assert meta_day.spend > 0


def test_cold_snap_raises_emergency_demand(world):
    def emergencies_per_day(first: date, last: date) -> float:
        days = (last - first).days + 1
        count = sum(
            1
            for h in world.households
            if h.need == "emergency_repair" and first <= h.origin_day <= last
        )
        return count / days

    event = emergencies_per_day(date(2026, 2, 9), date(2026, 2, 14))
    before = emergencies_per_day(date(2026, 1, 26), date(2026, 2, 8))

    assert event > 2 * before


def test_same_seed_gives_the_same_world():
    first = simulate(load_config("tiny"), seed=11)
    second = simulate(load_config("tiny"), seed=11)

    def fingerprint(world: World) -> list[tuple]:
        return [(s.pseudo_id, s.start, s.channel, s.landing_page) for s in world.all_sessions()]

    assert fingerprint(first) == fingerprint(second)
    assert [d.spend for d in first.meta_days] == [d.spend for d in second.meta_days]


def test_visits_after_the_window_are_simulated_but_bounded(world):
    calendar = world.context.calendar
    latest = max(s.start for s in world.all_sessions())

    # Journeys can run past data_as_of; export filters them, the simulation never runs wild.
    assert latest < calendar.as_of_end_utc + timedelta(days=60)
