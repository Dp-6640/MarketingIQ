"""What the tracking systems record: source-shaped rows, with their gaps and noise.

Everything here runs after the truth is complete. Column names follow each platform's
public schema; Salesforce fields ending in __c are hypothetical custom fields (U-02).
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import numpy as np

from synthetic.config import Recording
from synthetic.context import Context
from synthetic.entities import Household, Lead, Session
from synthetic.generator import World
from synthetic.rng import stable_int

LEAD_COLUMNS = (
    "Id",
    "CreatedDate",
    "LeadSource",
    "Status",
    "IsConverted",
    "ConvertedDate",
    "ConvertedOpportunityId",
    "City",
    "Entry_Point__c",
    "Request_Type__c",
    "Existing_Customer__c",
    "Service_Line__c",
    "Form_Page_Path__c",
    "UTM_Source__c",
    "UTM_Medium__c",
    "UTM_Campaign__c",
    "Click_Id_Type__c",
    "GA_Client_Id__c",
    "Meta_Campaign_Id__c",
    "Person_Key__c",
    "Qualified_Date__c",
    "Is_Test__c",
)
EVENT_COLUMNS = (
    "Id",
    "WhoId",
    "Type",
    "Appointment_Status__c",
    "CreatedDate",
    "ActivityDateTime",
)
OPPORTUNITY_COLUMNS = (
    "Id",
    "CreatedDate",
    "StageName",
    "CloseDate",
    "IsClosed",
    "IsWon",
    "Amount",
    "Amount_Basis__c",
    "Service_Line__c",
)
GA4_COLUMNS = (
    "user_pseudo_id",
    "ga_session_id",
    "session_start_utc",
    "source",
    "medium",
    "campaign",
    "content",
    "landing_page",
    "device_category",
    "has_gclid",
    "has_fbclid",
    "ev_quote_submit",
    "ev_callback_submit",
    "ev_phone_click",
    "ev_chat_start",
    "ev_booking_click",
)
META_COLUMNS = (
    "date",
    "account_id",
    "account_timezone",
    "campaign_id",
    "campaign_name",
    "spend",
    "impressions",
    "inline_link_clicks",
    "leads_reported",
    "attribution_setting",
)
CLARITY_COLUMNS = (
    "date_utc",
    "url",
    "sessions",
    "bot_sessions",
    "dead_clicks",
    "rage_clicks",
    "quickbacks",
    "excessive_scroll",
    "avg_scroll_depth",
    "script_errors",
)
ANNOTATION_COLUMNS = ("type", "start_date", "end_date", "label")
MAPPING_COLUMNS = (
    "platform",
    "platform_campaign_id",
    "campaign_name",
    "utm_campaign",
    "tactic",
    "service_lines",
    "region",
)

# Synthetic picklist labels (unverified; the application maps them through versioned config).
LEAD_SOURCE_BY_ENTRY = {
    "web_quote_form": "Web",
    "web_callback_form": "Web",
    "booking": "Web",
    "web_chat_agent": "Web Chat",
    "meta_messaging_agent": "Facebook",
    "meta_lead_form": "Facebook Lead Ad",
    "email_sms": "Email",
    "other": "Other",
}
SELF_REPORTED_SOURCE = {
    "organic_search": "Google",
    "paid_search": "Google",
    "meta": "Facebook",
    "organic_social": "Facebook",
    "referral": "Referral",
    "email": "Email",
    "direct": "Other",
}
SELF_REPORTED_VALUES = ("Google", "Facebook", "Referral", "TV/Radio", "Word of Mouth", "Other")
ENTRY_LABEL = {
    "web_quote_form": "Quote Form",
    "web_callback_form": "Callback Form",
    "booking": "Booking",
    "phone": "Phone",
    "web_chat_agent": "Web Chat",
    "meta_messaging_agent": "Messenger",
    "meta_lead_form": "Facebook Lead Ad",
    "email_sms": "Email/SMS",
    "other": "Other",
}
# The public callback form's dropdown merges repairs and maintenance into one option.
REQUEST_LABEL = {
    "install_replace": "Installation",
    "sales_general": "Sales",
    "repair_service": "Service & Repair",
    "maintenance": "Service & Repair",
    "billing": "Billing",
    "customer_service": "Customer Service",
    "non_sales_form": "Other",
    "spam": "Other",
}
SERVICE_LABEL = {
    "furnace": "Furnace",
    "air_conditioner": "Air Conditioner",
    "heat_pump": "Heat Pump",
    "water_heater": "Water Heater",
    "water_treatment": "Water Treatment",
    "air_quality": "Air Quality",
    "security": "Home Security",
    "generator": "Generator",
    "maintenance_plan": "Maintenance Plan",
}
AMOUNT_BASIS_LABEL = {
    "purchase_price": "Purchase",
    "financed_total": "Financed",
    "lease_contract": "Lease",
    "monthly": "Monthly",
}
APPOINTMENT_TYPE_LABEL = {
    "in_home_consultation": "In-Home Consultation",
    "service_visit": "Service Visit",
}
APPOINTMENT_STATUS_LABEL = {
    "completed": "Completed",
    "no_show": "No Show",
    "cancelled": "Cancelled",
}
UNTAGGED_CAMPAIGN = {
    "organic_search": "(organic)",
    "direct": "(direct)",
    "referral": "(referral)",
    "organic_social": "(referral)",
}

Row = tuple[str, ...]


@dataclass
class Table:
    path: str  # relative to the dataset folder
    columns: tuple[str, ...]
    rows: list[Row]


# --- identifiers ------------------------------------------------------------------------

_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_CHECKSUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"


def salesforce_id(prefix: str, number: int) -> str:
    """18-character Salesforce-style id: 3-char object prefix, 12 base62 chars, 3-char
    case-safety checksum (one character per 5-character chunk)."""
    digits = ""
    while number:
        number, remainder = divmod(number, 62)
        digits = _BASE62[remainder] + digits
    short = prefix + digits.rjust(12, "0")
    suffix = ""
    for start in range(0, 15, 5):
        chunk = short[start : start + 5]
        suffix += _CHECKSUM[sum(1 << i for i, char in enumerate(chunk) if char.isupper())]
    return short + suffix


def assign_identifiers(world: World) -> None:
    """Deterministic display ids: households, GA4 session ids and Salesforce-style ids."""
    for number, household in enumerate(
        sorted(world.households, key=lambda h: (h.origin_day, h.key)), start=1
    ):
        household.hid = number

    previous: tuple[str, int] | None = None
    for session in sorted(world.all_sessions(), key=lambda s: (s.pseudo_id, s.start)):
        session_id = int(session.start.timestamp())
        if previous and previous[0] == session.pseudo_id and session_id <= previous[1]:
            session_id = previous[1] + 1
        session.ga_session_id = session_id
        previous = (session.pseudo_id, session_id)

    leads = sorted(world.leads, key=lambda lead: (lead.created_at, lead.key))
    for number, lead in enumerate(leads, start=1):
        lead.sf_id = salesforce_id("00Q", number)
    appointments = sorted(
        (lead for lead in leads if lead.appointment is not None),
        key=lambda lead: (lead.appointment.booked_at, lead.sf_id),
    )
    for number, lead in enumerate(appointments, start=1):
        lead.appointment.sf_id = salesforce_id("00U", number)
    opportunities = sorted(
        (lead for lead in leads if lead.opportunity is not None),
        key=lambda lead: (lead.opportunity.created_at, lead.sf_id),
    )
    for number, lead in enumerate(opportunities, start=1):
        lead.opportunity.sf_id = salesforce_id("006", number)


# --- formatting -------------------------------------------------------------------------


def sf_datetime(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def flag(value: bool) -> str:
    return "true" if value else "false"


# --- Salesforce-style records -----------------------------------------------------------


def salesforce_tables(ctx: Context, world: World) -> list[Table]:
    as_of_end = ctx.calendar.as_of_end_utc
    leads = sorted(world.leads, key=lambda lead: lead.sf_id)
    lead_rows = [_lead_row(ctx, lead) for lead in leads]

    event_rows = []
    for lead in sorted(
        (lead for lead in leads if lead.appointment is not None),
        key=lambda lead: lead.appointment.sf_id,
    ):
        appointment = lead.appointment
        if appointment.booked_at >= as_of_end:
            continue
        if appointment.scheduled_for >= as_of_end:
            status = "Scheduled"
        else:
            status = APPOINTMENT_STATUS_LABEL[appointment.outcome]
        event_rows.append(
            (
                appointment.sf_id,
                lead.sf_id,
                APPOINTMENT_TYPE_LABEL[appointment.kind],
                status,
                sf_datetime(appointment.booked_at),
                sf_datetime(appointment.scheduled_for),
            )
        )

    opportunity_rows = []
    common = ctx.config.lifecycle_common
    for lead in sorted(
        (lead for lead in leads if lead.opportunity is not None),
        key=lambda lead: lead.opportunity.sf_id,
    ):
        opportunity = lead.opportunity
        if opportunity.created_at >= as_of_end:
            continue
        closed = opportunity.close_at < as_of_end
        if closed:
            stage = "Closed Won" if opportunity.won else "Closed Lost"
            close_date = ctx.calendar.local_date(opportunity.close_at)
        else:
            stage = "Quote Sent"
            expected = opportunity.created_at + timedelta(days=common.open_quote_expected_days)
            close_date = ctx.calendar.local_date(expected)
        opportunity_rows.append(
            (
                opportunity.sf_id,
                sf_datetime(opportunity.created_at),
                stage,
                close_date.isoformat(),
                flag(closed),
                flag(closed and opportunity.won),
                f"{opportunity.amount:.2f}",
                AMOUNT_BASIS_LABEL[opportunity.amount_basis],
                SERVICE_LABEL[opportunity.service_line],
            )
        )

    return [
        Table("salesforce/leads.csv", LEAD_COLUMNS, lead_rows),
        Table("salesforce/events.csv", EVENT_COLUMNS, event_rows),
        Table("salesforce/opportunities.csv", OPPORTUNITY_COLUMNS, opportunity_rows),
    ]


def _lead_row(ctx: Context, lead: Lead) -> Row:
    recording = ctx.config.recording
    calendar = ctx.calendar
    rng = ctx.streams.rng("record", *lead.key)
    household = lead.household
    entry = lead.entry_point
    as_of_end = calendar.as_of_end_utc

    visits = [s for s in household.sessions if s.start <= lead.created_at] if household else []
    capture, ga_capture, page_capture = _capture_rates(recording, entry)
    created_day = calendar.local_date(lead.created_at)
    if any(o.start <= created_day <= o.end for o in ctx.config.capture_outages):
        capture = ga_capture = page_capture = 0.0

    utm_source = utm_medium = utm_campaign = click_id = ga_id = form_page = ""
    if visits and rng.random() < capture:
        cutoff = lead.created_at - timedelta(days=recording.capture_lookback_days)
        tagged = [
            s
            for s in visits
            if s.start >= cutoff and (s.channel in ("meta", "email") or s.has_gclid or s.has_fbclid)
        ]
        if tagged:
            latest = tagged[-1]
            if latest.channel in ("meta", "email"):  # auto-tagged paid search has no UTMs
                utm_source, utm_medium, utm_campaign = (
                    latest.source,
                    latest.medium,
                    latest.campaign_name,
                )
            click_id = "gclid" if latest.has_gclid else "fbclid" if latest.has_fbclid else ""
    if visits and household.consent and rng.random() < ga_capture:
        ga_id = household.pseudo_id or ""
    if visits and rng.random() < page_capture:
        form_page = visits[-1].landing_page

    meta_id = ""
    if household is not None and household.origin_campaign:
        native_rate = {
            "meta_lead_form": recording.meta_id_on_lead_form,
            "meta_messaging_agent": recording.meta_id_on_messaging,
        }.get(entry, 0.0)
        if rng.random() < native_rate:
            meta_id = ctx.campaigns[household.origin_campaign].platform_campaign_id

    lead_source = LEAD_SOURCE_BY_ENTRY.get(entry, "Other")
    if entry == "phone":
        lead_source = "Phone"
        if household is not None and rng.random() < recording.phone_lead_source_self_reported:
            lead_source = _self_reported_source(household, rng)
            if rng.random() < recording.lead_source_wrong:
                lead_source = SELF_REPORTED_VALUES[int(rng.integers(0, len(SELF_REPORTED_VALUES)))]

    request_type = ""
    if rng.random() < recording.request_type_recorded.get(entry, 0.0):
        request_type = REQUEST_LABEL[lead.request]
    existing = service = ""
    if household is not None:
        if rng.random() < recording.existing_customer_recorded.get(entry, 0.0):
            existing = "Yes" if household.customer_type == "existing" else "No"
        if household.service_line and rng.random() < recording.service_line_recorded.get(
            entry, 0.0
        ):
            service = SERVICE_LABEL[household.service_line]

    city = _recorded_city(ctx, rng, household.city if household else "Toronto", entry)
    person_key = household.person_key if household else rng.bytes(8).hex()
    qualified = ""
    qualified_by_as_of = lead.qualified_at is not None and lead.qualified_at < as_of_end
    if qualified_by_as_of and rng.random() < recording.qualified_date_recorded:
        qualified = sf_datetime(lead.qualified_at)

    opportunity = lead.opportunity
    converted = opportunity is not None and opportunity.created_at < as_of_end
    return (
        lead.sf_id,
        sf_datetime(lead.created_at),
        lead_source,
        lead.status,
        flag(converted),
        calendar.local_date(opportunity.created_at).isoformat() if converted else "",
        opportunity.sf_id if converted else "",
        city,
        ENTRY_LABEL[entry],
        request_type,
        existing,
        service,
        form_page,
        utm_source,
        utm_medium,
        utm_campaign,
        click_id,
        ga_id,
        meta_id,
        person_key,
        qualified,
        flag(lead.is_test),
    )


def _capture_rates(recording: Recording, entry: str) -> tuple[float, float, float]:
    """(UTM/click-id capture, GA client id capture given consent, form page capture)."""
    if entry in ("web_quote_form", "web_callback_form"):
        return (
            recording.utm_capture,
            recording.ga_id_capture_given_consent,
            recording.form_page_capture,
        )
    if entry == "booking":
        rate = recording.booking_capture
        return rate, rate, rate
    if entry == "web_chat_agent":
        rate = recording.chat_capture
        return rate, rate, rate
    return 0.0, 0.0, 0.0


def _self_reported_source(household: Household, rng: np.random.Generator) -> str:
    if household.origin_channel == "offline":
        return "TV/Radio" if rng.random() < 0.5 else "Word of Mouth"
    return SELF_REPORTED_SOURCE[household.origin_channel]


def _recorded_city(ctx: Context, rng: np.random.Generator, city: str, entry: str) -> str:
    recording = ctx.config.recording
    if rng.random() < recording.city_blank.get(entry, 0.0):
        return ""
    if rng.random() < recording.city_unrecognizable:
        return recording.unrecognizable_cities[
            int(rng.integers(0, len(recording.unrecognizable_cities)))
        ]
    if rng.random() < recording.city_variant:
        variants = [
            *ctx.city_aliases.get(city, []),
            city.lower(),
            city.upper(),
            f"{city} ON",
            f"{city}, Ontario",
            f" {city} ",
        ]
        return variants[int(rng.integers(0, len(variants)))]
    return city


# --- GA4, Meta, Clarity, annotations, mapping sheet -------------------------------------


def ga4_table(ctx: Context, world: World) -> Table:
    calendar = ctx.calendar
    sessions = sorted(
        (s for s in world.all_sessions() if s.recorded and calendar.in_export_window(s.start)),
        key=lambda s: (s.start, s.pseudo_id, s.ga_session_id),
    )
    rng = ctx.streams.rng("ga4_duplicate_rows")
    rows: list[Row] = []
    for session in sessions:
        row = (
            session.pseudo_id,
            str(session.ga_session_id),
            iso_utc(session.start),
            session.source,
            session.medium,
            session.campaign_name or UNTAGGED_CAMPAIGN[session.channel],
            session.content,
            session.landing_page,
            session.device,
            flag(session.has_gclid),
            flag(session.has_fbclid),
            str(session.ev_quote_submit),
            str(session.ev_callback_submit),
            str(session.ev_phone_click),
            str(session.ev_chat_start),
            str(session.ev_booking_click),
        )
        rows.append(row)
        if rng.random() < ctx.config.recording.duplicate_session_rows:
            rows.append(row)
    return Table("ga4/sessions.csv", GA4_COLUMNS, rows)


def meta_table(ctx: Context, world: World) -> Table:
    calendar = ctx.calendar
    account = ctx.config.meta_account
    rows = [
        (
            row.day.isoformat(),
            account.account_id,
            account.timezone,
            ctx.campaigns[row.campaign].platform_campaign_id,
            ctx.campaigns[row.campaign].display_name,
            f"{row.spend:.2f}",
            str(row.impressions),
            str(row.clicks),
            str(row.reported_leads),
            account.attribution_setting,
        )
        for row in sorted(
            world.meta_days,
            key=lambda row: (row.day, ctx.campaigns[row.campaign].platform_campaign_id),
        )
        if calendar.start <= row.day <= calendar.data_as_of
    ]
    return Table("meta/insights_daily.csv", META_COLUMNS, rows)


def clarity_table(ctx: Context, world: World) -> Table:
    """Daily page-level friction summaries (UTC days, as Clarity's export uses)."""
    config = ctx.config
    clarity = config.clarity
    counts: Counter[tuple[date, str]] = Counter(
        (s.start.astimezone(UTC).date(), s.landing_page)
        for s in world.all_sessions()
        if s.recorded and ctx.calendar.in_export_window(s.start)
    )
    rows: list[Row] = []
    for (day, page), sessions in sorted(counts.items()):
        rng = ctx.streams.rng("clarity", day.toordinal(), stable_int(page))
        is_location = page.startswith(config.pages.location_prefix)
        rage_rate = clarity.location_rage_click_rate if is_location else clarity.rage_click_rate
        for change in config.page_changes:
            if day >= change.date and page.startswith(change.path_prefix):
                rage_rate *= change.clarity_friction_multiplier
        noise = float(rng.uniform(-clarity.session_count_noise, clarity.session_count_noise))
        low, high = clarity.scroll_depth_range
        rows.append(
            (
                day.isoformat(),
                f"{config.organization.site}{page}",
                str(max(1, round(sessions * (1 + noise)))),
                str(int(rng.poisson(sessions * clarity.bot_session_rate))),
                str(int(rng.poisson(sessions * clarity.dead_click_rate))),
                str(int(rng.poisson(sessions * rage_rate))),
                str(int(rng.poisson(sessions * clarity.quickback_rate))),
                str(int(rng.poisson(sessions * clarity.excessive_scroll_rate))),
                f"{float(rng.uniform(low, high)):.1f}",
                str(int(rng.poisson(sessions * clarity.script_error_rate))),
            )
        )
    return Table("clarity/page_daily.csv", CLARITY_COLUMNS, rows)


def annotation_table(ctx: Context) -> Table:
    """Dated events a marketer would know about. Capture outages are deliberately absent."""
    config = ctx.config
    calendar = ctx.calendar
    rows: list[Row] = [
        (event.kind, event.start.isoformat(), event.end.isoformat(), event.label)
        for event in config.demand_events
        if event.annotate
    ]
    rows += [
        ("site_change", change.date.isoformat(), change.date.isoformat(), change.label)
        for change in config.page_changes
        if change.annotate
    ]
    rows += [
        ("campaign_launch", c.start.isoformat(), c.start.isoformat(), f"Launched {c.display_name}")
        for c in config.campaigns
        if c.start is not None and calendar.start <= c.start <= calendar.data_as_of
    ]
    rows.sort(key=lambda row: (row[1], row[0], row[3]))
    return Table("annotations.csv", ANNOTATION_COLUMNS, rows)


def mapping_table(ctx: Context) -> Table:
    """The marketing team's campaign naming sheet; unmapped campaigns are missing (S09)."""
    rows = [
        (
            c.platform,
            c.platform_campaign_id,
            c.display_name,
            c.utm_campaign,
            c.tactic,
            "|".join(c.service_lines),
            c.region,
        )
        for c in ctx.config.campaigns
        if c.mapped
    ]
    return Table("reference/campaign_mappings.csv", MAPPING_COLUMNS, rows)


# --- ground truth -----------------------------------------------------------------------


def truth_tables(ctx: Context, world: World) -> list[Table]:
    calendar = ctx.calendar
    leads_by_household: dict[int, list[Lead]] = defaultdict(list)
    for lead in world.leads:
        if lead.household is not None:
            leads_by_household[id(lead.household)].append(lead)

    households = sorted(world.households, key=lambda h: h.hid)
    household_rows = [
        (
            str(h.hid),
            h.person_key,
            h.region,
            h.city,
            h.need,
            h.service_line or "",
            h.request,
            h.customer_type,
            f"{h.intent:.4f}",
            flag(h.consent),
            h.origin_channel,
            h.origin_campaign or "",
            h.origin_day.isoformat(),
            str(h.system_age),
            flag(h.retargeted),
            flag(bool(leads_by_household.get(id(h)))),
        )
        for h in households
    ]

    session_rows = [
        (
            s.pseudo_id,
            str(s.ga_session_id),
            str(s.household.hid) if s.household else "",
            iso_utc(s.start),
            s.channel,
            s.campaign or "",
            flag(s.recorded and calendar.in_export_window(s.start)),
        )
        for s in sorted(world.all_sessions(), key=lambda s: (s.start, s.pseudo_id, s.ga_session_id))
        if s.start < calendar.as_of_end_utc
    ]

    journey_rows = []
    for lead in sorted(world.leads, key=lambda lead: lead.sf_id):
        household = lead.household
        before: list[Session] = []
        if household is not None:
            before = [s for s in household.sessions if s.start <= lead.created_at]
        first = before[0] if before else None
        last = before[-1] if before else None
        journey_rows.append(
            (
                lead.sf_id,
                str(household.hid) if household else "",
                lead.true_class,
                lead.entry_point,
                flag(lead.is_test),
                lead.duplicate_of.sf_id if lead.duplicate_of else "",
                flag(lead.resubmission),
                str(len(before)),
                first.channel if first else "",
                (first.campaign or "") if first else "",
                last.channel if last else "",
                (last.campaign or "") if last else "",
                flag(
                    any(
                        s.campaign and ctx.campaigns[s.campaign].tactic == "retargeting"
                        for s in before
                    )
                ),
                household.origin_channel if household else "",
                (household.origin_campaign or "") if household else "",
            )
        )

    return [
        Table(
            "truth/households.csv",
            (
                "household_id",
                "person_key",
                "region",
                "city",
                "need",
                "service_line",
                "request",
                "customer_type",
                "intent",
                "analytics_consent",
                "origin_channel",
                "origin_campaign",
                "origin_day",
                "system_age_years",
                "retargeted",
                "has_lead",
            ),
            household_rows,
        ),
        Table(
            "truth/sessions.csv",
            (
                "user_pseudo_id",
                "ga_session_id",
                "household_id",
                "session_start_utc",
                "channel",
                "campaign",
                "in_ga4_export",
            ),
            session_rows,
        ),
        Table(
            "truth/journeys.csv",
            (
                "lead_id",
                "household_id",
                "true_class",
                "entry_point",
                "is_test",
                "duplicate_of",
                "resubmission",
                "visits_before_lead",
                "first_touch_channel",
                "first_touch_campaign",
                "last_touch_channel",
                "last_touch_campaign",
                "retargeted_before_lead",
                "origin_channel",
                "origin_campaign",
            ),
            journey_rows,
        ),
    ]
