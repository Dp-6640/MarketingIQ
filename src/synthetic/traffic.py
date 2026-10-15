"""Households with a need, their website journeys, and visitors with no need."""

import math
from datetime import date, datetime, timedelta

import numpy as np

from synthetic.config import WEB_ENTRY_POINTS
from synthetic.context import Context
from synthetic.entities import Household, Session

# How each channel appears in GA4's source / medium (GA4 conventions, not assumptions).
MEDIUM = {
    "organic_search": "organic",
    "paid_search": "cpc",
    "direct": "(none)",
    "referral": "referral",
    "organic_social": "referral",
    "email": "email",
    "meta": "paid_social",
}
FIXED_SOURCE = {"direct": "(direct)", "paid_search": "google", "email": "newsletter"}
# GA4 event recorded on the visit where each website entry point happens.
EVENT_FOR_ENTRY = {
    "web_quote_form": "ev_quote_submit",
    "web_callback_form": "ev_callback_submit",
    "booking": "ev_booking_click",
    "web_chat_agent": "ev_chat_start",
}

# First element of Household.key: where the household came from.
DEMAND, META_PROSPECT, META_NATIVE = 1, 2, 3


def make_session(
    ctx: Context,
    rng: np.random.Generator,
    *,
    pseudo_id: str,
    start: datetime,
    channel: str,
    campaign: str | None,
    device: str,
    service_line: str | None,
    city: str | None,
    household: Household | None,
    recorded: bool,
    profile: str | None = None,
) -> Session:
    traffic = ctx.config.traffic
    config_campaign = ctx.campaigns[campaign] if campaign else None
    source = FIXED_SOURCE.get(channel) or ctx.pick_source[channel].sample(rng)
    campaign_name = content = ""
    if config_campaign is not None:
        campaign_name = config_campaign.utm_campaign
        if channel == "meta":
            if rng.random() < traffic.utm_case_variant_rate:
                campaign_name = _case_variant(campaign_name, rng)
            content = f"ad_{'abc'[int(rng.integers(0, 3))]}"
        elif channel == "email":
            content = ctx.calendar.local_date(start).strftime("%Y-%m")
    if profile is None:
        profile = config_campaign.landing if channel == "meta" and config_campaign else channel
    session = Session(
        pseudo_id=pseudo_id,
        start=start,
        channel=channel,
        campaign=campaign,
        source=source,
        medium=MEDIUM[channel],
        campaign_name=campaign_name,
        content=content,
        landing_page=landing_page(ctx, rng, profile, service_line, city),
        device=device,
        has_gclid=channel == "paid_search" and rng.random() < traffic.click_id_rate,
        has_fbclid=channel == "meta" and rng.random() < traffic.click_id_rate,
        recorded=recorded,
        household=household,
    )
    for event, probability in traffic.ambient_events.items():
        if rng.random() < probability:
            setattr(session, f"ev_{event}", 1)
    return session


def landing_page(
    ctx: Context,
    rng: np.random.Generator,
    profile: str,
    service_line: str | None,
    city: str | None,
) -> str:
    pages = ctx.config.pages
    kind = ctx.pick_landing[profile].sample(rng)
    if kind in ("service", "offer"):
        service = service_line or ctx.pick_any_service.sample(rng)
        if kind == "service":
            return pages.service[service]
        return f"{pages.offer_prefix}{service.replace('_', '-')}/"
    if kind == "location":
        if city is not None:
            slug = ctx.city_slug.get(city, "")
        else:
            slug = ctx.pick_location_slug.sample(rng) if ctx.pick_location_slug else ""
        return f"{pages.location_prefix}{slug}/" if slug else pages.home
    return {"home": pages.home, "quote": pages.quote, "careers": pages.careers, "blog": pages.blog}[
        kind
    ]


def new_pseudo_id(rng: np.random.Generator, first_visit: datetime) -> str:
    """GA4-shaped client id: random number + first-visit Unix time."""
    return f"{int(rng.integers(1_000_000_000, 10_000_000_000))}.{int(first_visit.timestamp())}"


def build_household(
    ctx: Context,
    rng: np.random.Generator,
    key: tuple[int, ...],
    *,
    day: date,
    region: str,
    need: str,
    service_line: str | None,
    origin_channel: str,
    origin_campaign: str | None,
) -> Household:
    need_config = ctx.config.needs[need]
    return Household(
        key=key,
        person_key=rng.bytes(8).hex(),
        region=region,
        city=ctx.pick_city[region].sample(rng),
        need=need,
        service_line=service_line,
        request=ctx.needs[need].requests.sample(rng),
        customer_type="existing" if rng.random() < need_config.existing_customer_share else "new",
        intent=float(rng.beta(*need_config.intent)),
        consent=bool(rng.random() < ctx.config.traffic.analytics_consent_rate),
        device=ctx.pick_device.sample(rng),
        system_age=int(rng.integers(1, 26)),
        origin_channel=origin_channel,
        origin_campaign=origin_campaign,
        origin_day=day,
    )


def plan_journey(
    ctx: Context,
    rng: np.random.Generator,
    household: Household,
    *,
    first_channel: str,
    first_campaign: str | None = None,
    first_start: datetime | None = None,
) -> None:
    """Create the household's website visits: the first from the origin channel, the rest
    from the later-touch channel mix, spread over a lognormal journey length."""
    config = ctx.config
    calendar = ctx.calendar
    need = config.needs[household.need]
    day = household.origin_day
    start = first_start or calendar.random_time(rng, day, need.hours)
    times = [start]
    extra = min(int(rng.poisson(need.sessions_extra_mean)), 7)
    if extra:
        median = max(need.journey_median_days, 0.5)
        span = min(float(rng.lognormal(math.log(median), 0.7)), config.traffic.journey_cap_days)
        for _ in range(extra):
            later = calendar.random_time(
                rng, day + timedelta(days=int(rng.uniform(0, span))), "web"
            )
            if later <= start:
                later = start + timedelta(seconds=int(rng.integers(600, 7200)))
            times.append(later)
        times.sort()
    household.pseudo_id = new_pseudo_id(rng, start)
    for index, moment in enumerate(times):
        channel = first_channel if index == 0 else ctx.pick_later_touch.sample(rng)
        if index == 0 and first_campaign:
            campaign = first_campaign
        else:
            campaign = config.traffic.channel_campaigns.get(channel)
        household.sessions.append(
            make_session(
                ctx,
                rng,
                pseudo_id=household.pseudo_id,
                start=moment,
                channel=channel,
                campaign=campaign,
                device=household.device,
                service_line=household.service_line,
                city=household.city,
                household=household,
                recorded=household.consent,
            )
        )


def decide_conversion(ctx: Context, rng: np.random.Generator, household: Household) -> None:
    """Whether the household becomes a lead, how, and when."""
    need = ctx.config.needs[household.need]
    samplers = ctx.needs[household.need]
    entry = (samplers.entry if household.sessions else samplers.offline_entry).sample(rng)
    probability = need.convert_base + need.convert_intent_slope * household.intent
    if household.sessions and entry in WEB_ENTRY_POINTS:
        last = household.sessions[-1]
        last_day = ctx.calendar.local_date(last.start)
        for change in ctx.config.page_changes:
            if last_day >= change.date and last.landing_page.startswith(change.path_prefix):
                probability *= change.conversion_multiplier
    if rng.random() >= min(probability, 0.97):
        return
    household.converts = True
    household.entry_point = entry
    household.lead_at = _lead_time(ctx, rng, household, entry)
    if household.sessions:
        last = household.sessions[-1]
        if entry in EVENT_FOR_ENTRY:
            setattr(last, EVENT_FOR_ENTRY[entry], 1)
        elif entry == "phone" and rng.random() < ctx.config.traffic.phone_click_on_last_session:
            last.ev_phone_click = 1


def _lead_time(
    ctx: Context, rng: np.random.Generator, household: Household, entry: str
) -> datetime:
    if not household.sessions:
        hours = ctx.config.needs[household.need].hours
        return ctx.calendar.random_time(
            rng, household.origin_day, "business" if hours == "web" else hours
        )
    last = household.sessions[-1].start
    if entry in WEB_ENTRY_POINTS:
        seconds = float(rng.integers(60, 900))
    elif entry == "phone" and household.need == "emergency_repair":
        seconds = float(rng.integers(60, 1800))
    elif entry == "phone":
        seconds = min(float(rng.exponential(6 * 3600)), 3 * 86400.0)
    elif entry == "email_sms":
        seconds = float(rng.uniform(1, 3)) * 86400
    else:
        seconds = float(rng.uniform(3600, 2 * 86400))
    return last + timedelta(seconds=int(seconds))


def demand_households(ctx: Context) -> list[Household]:
    """Households that make contact on their own, drawn per day and region from the demand
    model: need share x service mix x seasonality x weekday x growth x event multipliers."""
    config = ctx.config
    calendar = ctx.calendar
    combos: list[tuple[str, str | None, float]] = []
    for need_name, need in config.needs.items():
        if need.service_mix is None:
            combos.append((need_name, None, 1.0))
        else:
            mix = config.service_mixes[need.service_mix]
            combos.extend((need_name, service, weight) for service, weight in mix.items())

    households: list[Household] = []
    for day in calendar.sim_days():
        events = [event for event in config.demand_events if event.start <= day <= event.end]
        day_rate = config.traffic.demand_households_per_day * calendar.weekday(day)
        for region_index, region in enumerate(config.regions):
            rates = []
            for need_name, service, weight in combos:
                need = config.needs[need_name]
                multiplier = 1.0
                for event in events:
                    multiplier *= event.need_multipliers.get(need_name, 1.0)
                    if event.repair_service_mix is not None and need.service_mix == "repair":
                        weight = event.repair_service_mix.get(service or "", 0.0)
                rates.append(
                    day_rate
                    * region.share
                    * need.share
                    * weight
                    * calendar.season(service, day)
                    * calendar.growth(day, service)
                    * multiplier
                )
            counts = ctx.streams.rng("demand", day.toordinal(), region_index).poisson(rates)
            for combo_index, count in enumerate(counts.tolist()):
                need_name, service, _ = combos[combo_index]
                for k in range(count):
                    key = (DEMAND, day.toordinal(), region_index, combo_index, k)
                    households.append(
                        _demand_household(ctx, key, day, region.key, need_name, service)
                    )
    return households


def _demand_household(
    ctx: Context,
    key: tuple[int, ...],
    day: date,
    region: str,
    need_name: str,
    service: str | None,
) -> Household:
    rng = ctx.streams.rng("household", *key)
    household = build_household(
        ctx,
        rng,
        key,
        day=day,
        region=region,
        need=need_name,
        service_line=service,
        origin_channel="offline",
        origin_campaign=None,
    )
    if rng.random() < ctx.config.needs[need_name].web_share:
        channel = ctx.needs[need_name].first_touch.sample(rng)
        household.origin_channel = channel
        household.origin_campaign = ctx.config.traffic.channel_campaigns.get(channel)
        plan_journey(ctx, rng, household, first_channel=channel)
    decide_conversion(ctx, rng, household)
    return household


def visitor_session(
    ctx: Context,
    rng: np.random.Generator,
    *,
    start: datetime,
    channel: str,
    campaign: str | None,
    service_line: str | None = None,
    profile: str | None = None,
) -> Session:
    """A one-off visit from someone with no need (a new GA client id each time)."""
    return make_session(
        ctx,
        rng,
        pseudo_id=new_pseudo_id(rng, start),
        start=start,
        channel=channel,
        campaign=campaign,
        device=ctx.pick_device.sample(rng),
        service_line=service_line,
        city=None,
        household=None,
        recorded=bool(rng.random() < ctx.config.traffic.analytics_consent_rate),
        profile=profile,
    )


def no_need_sessions(ctx: Context) -> list[Session]:
    """Baseline traffic from visitors with no need: job seekers, browsers, the curious."""
    config = ctx.config
    calendar = ctx.calendar
    sessions = []
    for day in calendar.sim_days():
        rng = ctx.streams.rng("no_need", day.toordinal())
        rate = (
            config.traffic.no_need_sessions_per_day * calendar.weekday(day) * calendar.growth(day)
        )
        for _ in range(int(rng.poisson(rate))):
            channel = ctx.pick_no_need_channel.sample(rng)
            sessions.append(
                visitor_session(
                    ctx,
                    rng,
                    start=calendar.random_time(rng, day, "web"),
                    channel=channel,
                    campaign=config.traffic.channel_campaigns.get(channel),
                    profile="no_need",
                )
            )
    return sessions


def _case_variant(value: str, rng: np.random.Generator) -> str:
    if rng.random() < 0.5:
        return value.upper()
    return "_".join(part.capitalize() for part in value.split("_"))
