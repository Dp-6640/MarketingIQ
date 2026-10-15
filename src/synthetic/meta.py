"""Meta ad delivery, the households Meta ads bring in, and retargeting."""

from bisect import bisect_left, insort
from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np

from synthetic.config import WEB_ENTRY_POINTS, CampaignConfig, parse_month_day
from synthetic.context import Context
from synthetic.entities import Household, MetaDay, Session
from synthetic.rng import stable_int
from synthetic.traffic import (
    META_NATIVE,
    META_PROSPECT,
    build_household,
    decide_conversion,
    make_session,
    plan_journey,
    visitor_session,
)

RETARGETING_POOL_DAYS = 30


def is_active(campaign: CampaignConfig, day: date) -> bool:
    if campaign.start and day < campaign.start:
        return False
    if campaign.end and day > campaign.end:
        return False
    if not campaign.seasons:
        return True
    month_day = (day.month, day.day)
    for first, last in campaign.seasons:
        start, end = parse_month_day(first), parse_month_day(last)
        within = (
            start <= month_day <= end if start <= end else (month_day >= start or month_day <= end)
        )
        if within:
            return True
    return False


def meta_delivery(ctx: Context) -> tuple[list[MetaDay], list[Household], list[Session]]:
    """Spend -> impressions -> link clicks for every active Meta campaign-day, plus the
    prospects, native leads and no-need visits those clicks produce."""
    calendar = ctx.calendar
    landing_rate = ctx.config.meta_account.landing_rate
    days: list[MetaDay] = []
    households: list[Household] = []
    sessions: list[Session] = []
    for campaign in ctx.config.campaigns:
        if campaign.platform != "meta":
            continue
        campaign_int = stable_int(campaign.key)
        for day in calendar.sim_days():
            if not is_active(campaign, day):
                continue
            rng = ctx.streams.rng("meta_day", campaign_int, day.toordinal())
            budget, ctr, quality = _modifiers(ctx, campaign, day)
            spend = (
                campaign.daily_budget * budget * calendar.growth(day) * float(rng.uniform(0.9, 1.1))
            )
            cpm = campaign.cpm * float(rng.uniform(0.92, 1.08))
            impressions = int(spend / cpm * 1000)
            clicks = int(rng.binomial(impressions, min(1.0, campaign.link_ctr * ctr)))
            meta_day = MetaDay(campaign.key, day, round(spend, 2), impressions, clicks)
            days.append(meta_day)
            seasonal = _campaign_season(ctx, campaign, day)

            if campaign.tactic in ("prospecting", "promo"):
                landed = int(rng.binomial(clicks, landing_rate))
                share = min(1.0, campaign.audience_quality * quality * seasonal)
                prospects = int(rng.binomial(landed, share))
                for k in range(prospects):
                    households.append(_prospect(ctx, campaign, campaign_int, day, k))
                for _ in range(landed - prospects):
                    sessions.append(_ad_click_visit(ctx, rng, campaign, day))
            elif campaign.tactic in ("lead_form", "messaging"):
                rate = (
                    campaign.form_completion
                    if campaign.tactic == "lead_form"
                    else (campaign.conversation_to_lead)
                )
                leads = int(rng.binomial(clicks, min(1.0, rate * quality * seasonal)))
                entry = (
                    "meta_lead_form" if campaign.tactic == "lead_form" else "meta_messaging_agent"
                )
                for k in range(leads):
                    households.append(_native(ctx, campaign, campaign_int, day, k, entry))
            else:  # retargeting: retargeting_overlay places these visits
                meta_day.landed = int(rng.binomial(clicks, landing_rate))
    return days, households, sessions


def retargeting_overlay(
    ctx: Context,
    households: list[Household],
    meta_days: list[MetaDay],
    visitor_sessions: list[Session],
) -> list[Session]:
    """Place retargeting clicks on people who already visited.

    Runs after every household's conversion has been decided and never changes it, so
    retargeting has no causal effect in this world (scenario S08). It reaches high-intent
    households more often, so it still collects attribution credit.
    """
    calendar = ctx.calendar
    tz = ctx.meta_tz
    retargeting = [d for d in meta_days if ctx.campaigns[d.campaign].tactic == "retargeting"]
    if not retargeting:
        return []

    reachable: dict[date, list[Household]] = defaultdict(list)
    for household in households:
        if not household.sessions or not household.consent:
            continue
        day = calendar.local_date(household.sessions[0].start, tz)
        last_day = calendar.local_date(_reach_until(household), tz)
        while day <= last_day:
            reachable[day].append(household)
            day += timedelta(days=1)

    pool = sorted(
        (s for s in visitor_sessions if s.recorded),
        key=lambda s: (calendar.local_date(s.start, tz), s.start, s.pseudo_id),
    )
    pool_days = [calendar.local_date(s.start, tz) for s in pool]

    extra: list[Session] = []
    for meta_day in retargeting:
        campaign = ctx.campaigns[meta_day.campaign]
        rng = ctx.streams.rng("retargeting", stable_int(campaign.key), meta_day.day.toordinal())
        wanted = int(rng.binomial(meta_day.landed, campaign.need_click_share))
        candidates = reachable.get(meta_day.day, [])
        placed = 0
        if wanted and candidates:
            weights = np.array([household.intent**2 for household in candidates])
            chosen = rng.choice(
                len(candidates),
                size=min(wanted, len(candidates)),
                replace=False,
                p=weights / weights.sum(),
            )
            for index in sorted(chosen.tolist()):
                placed += _place_click(ctx, rng, candidates[index], campaign, meta_day.day)
        low = bisect_left(pool_days, meta_day.day - timedelta(days=RETARGETING_POOL_DAYS))
        high = bisect_left(pool_days, meta_day.day)
        for _ in range(meta_day.landed - placed):
            if high <= low:
                break
            past = pool[int(rng.integers(low, high))]
            extra.append(
                make_session(
                    ctx,
                    rng,
                    pseudo_id=past.pseudo_id,
                    start=calendar.random_time(rng, meta_day.day, "web", tz),
                    channel="meta",
                    campaign=campaign.key,
                    device=past.device,
                    service_line=None,
                    city=None,
                    household=None,
                    recorded=True,
                )
            )
    return extra


def _reach_until(household: Household) -> datetime:
    """Last moment a retargeting click can land before the lead (or a week after the last
    visit, for households that never become a lead)."""
    if household.converts and household.lead_at is not None:
        if household.entry_point in WEB_ENTRY_POINTS:
            return household.sessions[-1].start  # the visit where they submitted
        return household.lead_at
    return household.sessions[-1].start + timedelta(days=7)


def _place_click(
    ctx: Context,
    rng: np.random.Generator,
    household: Household,
    campaign: CampaignConfig,
    day: date,
) -> bool:
    calendar = ctx.calendar
    tz = ctx.meta_tz
    low = max(calendar.at(day, 0, tz), household.sessions[0].start + timedelta(minutes=1))
    high = min(
        calendar.at(day + timedelta(days=1), 0, tz), _reach_until(household) - timedelta(minutes=1)
    )
    if high <= low:
        return False
    start = (low + (high - low) * float(rng.random())).replace(microsecond=0)
    session = make_session(
        ctx,
        rng,
        pseudo_id=household.pseudo_id or "",
        start=start,
        channel="meta",
        campaign=campaign.key,
        device=household.device,
        service_line=household.service_line,
        city=household.city,
        household=household,
        recorded=household.consent,
    )
    insort(household.sessions, session, key=lambda s: s.start)
    household.retargeted = True
    return True


def _modifiers(ctx: Context, campaign: CampaignConfig, day: date) -> tuple[float, float, float]:
    budget = ctr = quality = 1.0
    for modifier in ctx.config.campaign_modifiers:
        if modifier.campaign == campaign.key and modifier.start <= day <= modifier.end:
            budget *= modifier.budget
            ctr *= modifier.ctr
            quality *= modifier.audience_quality
    return budget, ctr, quality


def _campaign_season(ctx: Context, campaign: CampaignConfig, day: date) -> float:
    if not campaign.service_lines:
        return 1.0
    return sum(w * ctx.calendar.season(s, day) for s, w in campaign.service_lines.items())


def _service_for(
    ctx: Context, rng: np.random.Generator, campaign: CampaignConfig, need: str
) -> str | None:
    if campaign.key in ctx.pick_campaign_service:
        return ctx.pick_campaign_service[campaign.key].sample(rng)
    mix = ctx.config.needs[need].service_mix
    return ctx.pick_service[mix].sample(rng) if mix else None


def _prospect(
    ctx: Context, campaign: CampaignConfig, campaign_int: int, day: date, k: int
) -> Household:
    """Someone with a need who clicked a prospecting ad: their first visit is the click."""
    key = (META_PROSPECT, campaign_int, day.toordinal(), k)
    rng = ctx.streams.rng("household", *key)
    need = ctx.pick_meta_prospect_need.sample(rng)
    household = build_household(
        ctx,
        rng,
        key,
        day=day,
        region=campaign.region or ctx.pick_region.sample(rng),
        need=need,
        service_line=_service_for(ctx, rng, campaign, need),
        origin_channel="meta",
        origin_campaign=campaign.key,
    )
    click = ctx.calendar.random_time(rng, day, "web", ctx.meta_tz)
    household.origin_day = ctx.calendar.local_date(click)
    plan_journey(
        ctx, rng, household, first_channel="meta", first_campaign=campaign.key, first_start=click
    )
    decide_conversion(ctx, rng, household)
    return household


def _native(
    ctx: Context, campaign: CampaignConfig, campaign_int: int, day: date, k: int, entry: str
) -> Household:
    """A lead created inside Meta (lead form or Messenger); never visits the website."""
    key = (META_NATIVE, campaign_int, day.toordinal(), k)
    rng = ctx.streams.rng("household", *key)
    need = ctx.pick_meta_native_need.sample(rng)
    household = build_household(
        ctx,
        rng,
        key,
        day=day,
        region=campaign.region or ctx.pick_region.sample(rng),
        need=need,
        service_line=_service_for(ctx, rng, campaign, need),
        origin_channel="meta",
        origin_campaign=campaign.key,
    )
    click = ctx.calendar.random_time(rng, day, "web", ctx.meta_tz)
    household.origin_day = ctx.calendar.local_date(click)
    household.converts = True
    household.entry_point = entry
    household.lead_at = click + timedelta(seconds=int(rng.integers(30, 600)))
    return household


def _ad_click_visit(
    ctx: Context, rng: np.random.Generator, campaign: CampaignConfig, day: date
) -> Session:
    service = None
    if campaign.key in ctx.pick_campaign_service:
        service = ctx.pick_campaign_service[campaign.key].sample(rng)
    return visitor_session(
        ctx,
        rng,
        start=ctx.calendar.random_time(rng, day, "web", ctx.meta_tz),
        channel="meta",
        campaign=campaign.key,
        service_line=service,
    )
