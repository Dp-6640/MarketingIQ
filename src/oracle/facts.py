"""Reads one synthetic dataset's files and derives every lead's facts from the documents' rules.

Sections follow the documents: campaigns and channels (source-to-canonical.md), leads and
their class (lifecycle_and_classification.md, core-model.md "What happens to a lead"),
evidence tiers and credit (attribution.md), then counting (metrics.md).
"""

import csv
import json
import re
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo

RULES = Path(__file__).resolve().parents[1] / "marketingiq" / "core" / "rules.toml"
MODELS = ("first_touch", "last_non_direct", "linear")
LOOKBACKS = (7, 30, 90)
CLICK_ID_CHANNELS = {"gclid": "paid_search", "fbclid": "paid_social"}
PLATFORM_CHANNELS = {"meta": "paid_social", "google_ads": "paid_search", "email": "email"}


@dataclass(frozen=True)
class Campaign:
    key: str
    name: str
    platform: str
    tactic: str | None
    service_lines: tuple[str, ...]
    in_mapping_sheet: bool
    meta_id: str | None
    utm: str | None

    @property
    def channel(self) -> str:
        return PLATFORM_CHANNELS.get(self.platform, "other")


@dataclass(frozen=True)
class Session:
    user: str
    session_id: str
    start: datetime
    day: date
    channel: str
    campaign: str | None
    unmapped: bool  # a campaign value the mapping sheet doesn't know
    landing_page: str
    form_submit: bool


@dataclass(frozen=True)
class Credit:
    """One credited touch. attribution.md keeps three kinds of "no campaign" apart:
    `unmapped` (a captured campaign value or click ID with no mapping), unattributed (no
    evidence: channel None) and channel-only credit (campaign None, channel known)."""

    campaign: str | None
    channel: str | None
    share: Fraction
    unmapped: bool = False


@dataclass
class Lead:
    id: str
    created: datetime
    day: date
    entry_point: str
    stage: str
    request_type: str
    request_type_source: str
    customer_type: str
    service_line: str
    region: str | None
    lead_class: str = "unknown"
    junk_reason: str | None = None
    duplicate_of: str | None = None
    qualified: bool = False
    booked: bool = False
    completed: bool = False
    opportunity: bool = False
    won: bool = False
    closed: bool = False
    # Only first leads (not duplicates) are tiered and credited, per lookback and model.
    tier: dict[int, str] = field(default_factory=dict)
    credits: dict[tuple[str, int], list[Credit]] = field(default_factory=dict)

    @property
    def first(self) -> bool:
        return self.duplicate_of is None


@dataclass
class Facts:
    tz: ZoneInfo
    data_as_of: date
    campaigns: dict[str, Campaign]
    sessions: list[Session]
    leads: list[Lead]
    spend_rows: list[dict]  # one per Meta campaign and day


def _bool(value: str) -> bool:
    return value.strip().lower() == "true"


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _read(folder: Path, name: str) -> list[dict[str, str]]:
    with (folder / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


def _city_key(value: str) -> str:
    """core-model.md step 6: spaces collapsed, case ignored, a trailing province dropped."""
    return re.sub(r"(,\s*|\s+)(ontario|on)$", "", _norm(value)).strip(" ,")


# --- campaigns and channels -------------------------------------------------------------


def _campaigns(folder: Path) -> dict[str, Campaign]:
    """The mapping sheet, plus Meta campaigns with spend that the sheet doesn't list."""
    campaigns: dict[str, Campaign] = {}
    for row in _read(folder, "reference/campaign_mappings.csv"):
        key = row["utm_campaign"].strip()
        campaigns[key] = Campaign(
            key=key,
            name=row["campaign_name"],
            platform=row["platform"],
            tactic=row["tactic"] or None,
            service_lines=tuple(s for s in row["service_lines"].split("|") if s),
            in_mapping_sheet=True,
            meta_id=row["platform_campaign_id"] or None,
            utm=key,
        )
    known = {c.meta_id for c in campaigns.values() if c.meta_id}
    for row in _read(folder, "meta/insights_daily.csv"):
        if row["campaign_id"] not in known:
            known.add(row["campaign_id"])
            key = f"meta:{row['campaign_id']}"
            campaigns[key] = Campaign(
                key, row["campaign_name"], "meta", None, (), False, row["campaign_id"], None
            )
    return campaigns


def channel_of(source: str, medium: str, rules: dict) -> str:
    """GA4 or UTM source/medium → channel, using the rule book's lists."""
    ch = rules["channels"]
    s, m = source.strip().casefold(), medium.strip().casefold()
    if s == "(direct)":
        return "direct"
    if m in ch["paid_social_mediums"]:
        return "paid_social"
    if m in ch["paid_search_mediums"]:
        return "paid_social" if s in ch["social_sources"] else "paid_search"
    if m in ch["email_mediums"]:
        return "email"
    if m == "organic" and s in ch["search_engines"]:
        return "organic_search"
    if s in ch["social_sources"]:
        return "organic_social"
    if m == "referral":
        return "referral"
    return "other"


# --- leads --------------------------------------------------------------------------------


def _region_lookup(rules: dict) -> dict[str, str]:
    geo = rules["geography"]
    lookup = {}
    for region in geo["regions"]:
        for city in region["cities"]:
            lookup[_norm(city)] = region["key"]
    for alias, city in geo["city_aliases"].items():
        lookup[_norm(alias)] = lookup[_norm(city)]
    for alias, region in geo["region_aliases"].items():
        lookup[_norm(alias)] = region
    return lookup


def _classify(lead: Lead, is_test: bool) -> None:
    """lifecycle_and_classification.md, "Deterministic lead classification", rules 1-6."""
    if is_test:
        lead.lead_class, lead.junk_reason = "junk", "test"
    elif lead.stage == "invalid":
        lead.lead_class, lead.junk_reason = "junk", "invalid"
    elif lead.duplicate_of:
        lead.lead_class, lead.junk_reason = "junk", "duplicate"
    elif lead.request_type in ("billing", "customer_service", "non_sales_form"):
        lead.lead_class = "non_marketing"
    elif lead.request_type in ("repair_service", "maintenance"):
        lead.lead_class = "service_demand"
    elif lead.request_type in ("install_replace", "sales_general"):
        existing = lead.customer_type == "existing"
        lead.lead_class = "existing_customer_sales" if existing else "acquisition"
    else:
        lead.lead_class = "unknown"


def _mark_duplicates(leads: list[Lead], person: dict[str, str], hours: int) -> None:
    """Same person within `hours` of the first lead of their group; later ones point to it."""
    by_person: dict[str, list[Lead]] = defaultdict(list)
    for lead in leads:
        if person.get(lead.id):
            by_person[person[lead.id]].append(lead)
    window = timedelta(hours=hours)
    for group in by_person.values():
        group.sort(key=lambda lead: (lead.created, lead.id))
        anchor = group[0]
        for lead in group[1:]:
            if lead.created - anchor.created <= window:
                lead.duplicate_of = anchor.id
            else:
                anchor = lead


# --- evidence and credit --------------------------------------------------------------------


def _journey_credits(touches: list[Session], model: str) -> list[Credit]:
    non_direct = [s for s in touches if s.channel != "direct"]
    if not non_direct:
        return [Credit(None, "direct", Fraction(1))]
    if model == "first_touch":
        chosen = [non_direct[0]]
    elif model == "last_non_direct":
        chosen = [non_direct[-1]]
    else:
        chosen = non_direct
    share = Fraction(1, len(chosen))
    return [Credit(s.campaign, s.channel, share, s.unmapped) for s in chosen]


# --- loading --------------------------------------------------------------------------------


def load(folder: Path | str, rules_path: Path = RULES) -> Facts:
    folder = Path(folder)
    rules = tomllib.loads(rules_path.read_text(encoding="utf-8"))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    tz = ZoneInfo(manifest["reporting_tz"])
    sf = rules["salesforce"]

    campaigns = _campaigns(folder)
    by_meta_id = {c.meta_id: c for c in campaigns.values() if c.meta_id}
    by_utm = {_norm(c.utm): c for c in campaigns.values() if c.utm}
    untagged = {_norm(v) for v in rules["channels"]["untagged_campaigns"]}

    def utm_campaign(value: str) -> Campaign | None:
        value = _norm(value)
        return None if not value or value in untagged else by_utm.get(value)

    sessions, seen = [], set()
    for row in _read(folder, "ga4/sessions.csv"):
        key = (row["user_pseudo_id"], row["ga_session_id"])
        if key in seen:
            continue  # exact duplicate export rows are dropped (synthetic-data.md, section 8)
        seen.add(key)
        start = _utc(row["session_start_utc"])
        campaign = utm_campaign(row["campaign"])
        tagged = _norm(row["campaign"]) not in untagged and bool(row["campaign"].strip())
        sessions.append(
            Session(
                user=row["user_pseudo_id"],
                session_id=row["ga_session_id"],
                start=start,
                day=start.astimezone(tz).date(),
                channel=channel_of(row["source"], row["medium"], rules),
                campaign=campaign.key if campaign else None,
                unmapped=tagged and campaign is None,
                landing_page=row["landing_page"],
                form_submit=int(row["ev_quote_submit"] or 0) + int(row["ev_callback_submit"] or 0)
                > 0,
            )
        )
    journeys: dict[str, list[Session]] = defaultdict(list)
    for session in sessions:
        journeys[session.user].append(session)
    for journey in journeys.values():
        journey.sort(key=lambda s: (s.start, s.session_id))

    events = defaultdict(list)
    for row in _read(folder, "salesforce/events.csv"):
        if sf["appointment_kinds"].get(row["Type"]) == "in_home_consultation":
            events[row["WhoId"]].append(
                sf["appointment_statuses"].get(row["Appointment_Status__c"])
            )
    opportunities = {row["Id"]: row for row in _read(folder, "salesforce/opportunities.csv")}

    regions = _region_lookup(rules)
    site = rules["site"]

    def page_service_line(path: str) -> str | None:
        """A service page from the page map, or an offer page whose slug names a service line."""
        if path in site["service_pages"]:
            return site["service_pages"][path]
        if path.startswith(site["offer_prefix"]):
            slug = path.removeprefix(site["offer_prefix"]).strip("/").replace("-", "_")
            return slug if slug in set(site["service_pages"].values()) else None
        return None

    cls = rules["classification"]
    leads, raw, person, tests = [], {}, {}, set()
    for row in _read(folder, "salesforce/leads.csv"):
        created = _utc(row["CreatedDate"])
        meta = (
            by_meta_id.get(row["Meta_Campaign_Id__c"].strip())
            if row["Meta_Campaign_Id__c"]
            else None
        )
        linked = meta or utm_campaign(row["UTM_Campaign__c"])
        entry_point = sf["entry_points"].get(row["Entry_Point__c"], "unknown")

        if row["Request_Type__c"]:
            request_type, source = (
                sf["request_types"].get(row["Request_Type__c"], "unknown"),
                "crm_field",
            )
        elif entry_point in cls["entry_point_defaults"]:
            request_type, source = cls["entry_point_defaults"][entry_point], "entry_point_default"
        elif linked and linked.tactic in cls["tactic_defaults"]:
            request_type, source = cls["tactic_defaults"][linked.tactic], "campaign"
        else:
            request_type, source = "unknown", "unknown"

        if row["Service_Line__c"]:
            service_line = sf["service_lines"].get(row["Service_Line__c"], "unknown")
        elif page_service_line(row["Form_Page_Path__c"]):
            service_line = page_service_line(row["Form_Page_Path__c"])
        elif linked and len(linked.service_lines) == 1:
            service_line = linked.service_lines[0]
        else:
            service_line = "unknown"

        customer = {"yes": "existing", "no": "new"}.get(
            row["Existing_Customer__c"].strip().casefold()
        )
        lead = Lead(
            id=row["Id"],
            created=created,
            day=created.astimezone(tz).date(),
            entry_point=entry_point,
            stage=sf["lead_stages"].get(row["Status"], "unknown"),
            request_type=request_type,
            request_type_source=source,
            customer_type=customer or "unknown",
            service_line=service_line,
            region=regions.get(_city_key(row["City"])) if row["City"].strip() else None,
        )
        lead.qualified = lead.stage in sf["qualified_stages"]
        statuses = events.get(lead.id, [])
        lead.booked = bool(statuses)
        lead.completed = "completed" in statuses
        opportunity = opportunities.get(row["ConvertedOpportunityId"])
        if opportunity:
            lead.opportunity = True
            lead.won = _bool(opportunity["IsWon"])
            lead.closed = _bool(opportunity["IsClosed"])
        leads.append(lead)
        raw[lead.id] = (row, linked, meta)
        person[lead.id] = row["Person_Key__c"].strip()
        if _bool(row["Is_Test__c"]):
            tests.add(lead.id)

    _mark_duplicates(leads, person, cls["duplicate_window_hours"])
    source_channels = sf["lead_source_channels"]
    for lead in leads:
        _classify(lead, lead.id in tests)
        if not lead.first:
            continue
        row, linked, meta = raw[lead.id]
        ga_id = row["GA_Client_Id__c"].strip()
        for lookback in LOOKBACKS:
            earliest = lead.created - timedelta(days=lookback)
            touches = [s for s in journeys.get(ga_id, []) if earliest <= s.start <= lead.created]
            if ga_id and touches:
                tier = "T1_journey"
                credits = {m: _journey_credits(touches, m) for m in MODELS}
            else:
                if (
                    lead.entry_point in ("meta_lead_form", "meta_messaging_agent")
                    and row["Meta_Campaign_Id__c"].strip()
                ):
                    tier = "T3_platform_native"
                    single = Credit(
                        meta.key if meta else None, "paid_social", Fraction(1), meta is None
                    )
                elif row["UTM_Campaign__c"].strip() or row["Click_Id_Type__c"].strip():
                    tier = "T2_captured_source"
                    campaign = utm_campaign(row["UTM_Campaign__c"])
                    if row["UTM_Medium__c"].strip() or row["UTM_Source__c"].strip():
                        channel = channel_of(row["UTM_Source__c"], row["UTM_Medium__c"], rules)
                    elif campaign:
                        channel = campaign.channel
                    else:
                        channel = CLICK_ID_CHANNELS.get(row["Click_Id_Type__c"].strip(), "other")
                    single = Credit(
                        campaign.key if campaign else None, channel, Fraction(1), campaign is None
                    )
                elif row["LeadSource"] in source_channels:
                    tier = "T4_self_reported_channel"
                    single = Credit(None, source_channels[row["LeadSource"]], Fraction(1))
                else:
                    tier = "T5_none"
                    single = Credit(None, None, Fraction(1))
                credits = {model: [single] for model in MODELS}
            lead.tier[lookback] = tier
            for model in MODELS:
                lead.credits[(model, lookback)] = credits[model]

    spend_rows = []
    for row in _read(folder, "meta/insights_daily.csv"):
        spend_rows.append(
            {
                "day": date.fromisoformat(row["date"]),
                "campaign": by_meta_id[row["campaign_id"]].key,
                "spend": Decimal(row["spend"]),
                "impressions": int(row["impressions"]),
                "link_clicks": int(row["inline_link_clicks"]),
                "platform_reported_leads": int(row["leads_reported"]),
            }
        )
    return Facts(
        tz=tz,
        data_as_of=date.fromisoformat(manifest["window"]["data_as_of"]),
        campaigns=campaigns,
        sessions=sessions,
        leads=leads,
        spend_rows=spend_rows,
    )
