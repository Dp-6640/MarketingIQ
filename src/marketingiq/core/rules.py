"""The rule book: load rules.toml, then apply it to source values.

Every function here is pure (no database), so each rule is tested on its own. The rule
order inside each function is the documented order in docs/lifecycle_and_classification.md
and docs/attribution.md.
"""

import re
import tomllib
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from marketingiq.core import vocabulary as vocab

RULES_PATH = Path(__file__).with_name("rules.toml")
META_NATIVE_ENTRY_POINTS = ("meta_lead_form", "meta_messaging_agent")


# --- the rule book (validated rules.toml) -----------------------------------------------


def _check_values(value: dict[str, str], allowed: tuple[str, ...]) -> dict[str, str]:
    unknown = sorted({v for v in value.values() if v not in allowed})
    if unknown:
        raise ValueError(f"values {unknown} aren't canonical; allowed: {list(allowed)}")
    return value


def _check_keys(value: dict[str, Any], allowed: tuple[str, ...]) -> dict[str, Any]:
    unknown = sorted(k for k in value if k not in allowed)
    if unknown:
        raise ValueError(f"keys {unknown} aren't canonical; allowed: {list(allowed)}")
    return value


def _mapping_to(allowed: tuple[str, ...]) -> Any:
    return Annotated[dict[str, str], AfterValidator(partial(_check_values, allowed=allowed))]


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    verified: bool


class Channels(Section):
    search_engines: list[str]
    social_sources: list[str]
    paid_search_mediums: list[str]
    paid_social_mediums: list[str]
    email_mediums: list[str]
    untagged_campaigns: list[str]


class CampaignMapping(Section):
    pass


class Site(Section):
    home: list[str]
    quote: list[str]
    careers: list[str]
    blog_prefix: str
    location_prefix: str
    offer_prefix: str
    service_pages: _mapping_to(vocab.SERVICE_LINES)


class Region(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    cities: list[str] = Field(min_length=1)


class Geography(Section):
    regions: list[Region]
    city_aliases: dict[str, str]
    region_aliases: dict[str, str]
    location_slugs: dict[str, str]

    @model_validator(mode="after")
    def _known_places(self) -> "Geography":
        cities = {city for region in self.regions for city in region.cities}
        regions = {region.key for region in self.regions}
        if len(cities) != sum(len(region.cities) for region in self.regions):
            raise ValueError("a city appears in more than one region")
        for name, places, known in (
            ("city_aliases", self.city_aliases.values(), cities),
            ("location_slugs", self.location_slugs.values(), cities),
            ("region_aliases", self.region_aliases.values(), regions),
        ):
            unknown = sorted(set(places) - known)
            if unknown:
                raise ValueError(f"{name} point at unknown places {unknown}")
        return self


class Salesforce(Section):
    qualified_stages: list[str]
    entry_points: _mapping_to(vocab.ENTRY_POINTS)
    request_types: _mapping_to(vocab.REQUEST_TYPES)
    service_lines: _mapping_to(vocab.SERVICE_LINES)
    lead_stages: _mapping_to(vocab.LEAD_STAGES)
    appointment_kinds: _mapping_to(vocab.APPOINTMENT_KINDS)
    appointment_statuses: _mapping_to(vocab.APPOINTMENT_STATUSES)
    amount_bases: _mapping_to(vocab.AMOUNT_BASES)
    lead_source_channels: _mapping_to(vocab.REPORTED_CHANNELS)

    @model_validator(mode="after")
    def _known_stages(self) -> "Salesforce":
        _check_values(dict(enumerate(self.qualified_stages)), vocab.LEAD_STAGES)
        return self


class Classification(Section):
    duplicate_window_hours: int = Field(gt=0)
    entry_point_defaults: _mapping_to(vocab.REQUEST_TYPES)
    tactic_defaults: _mapping_to(vocab.REQUEST_TYPES)

    @model_validator(mode="after")
    def _known_entry_points(self) -> "Classification":
        _check_keys(self.entry_point_defaults, vocab.ENTRY_POINTS)
        return self


class Attribution(Section):
    lookback_days: int = Field(ge=1, le=365)
    supported_lookback_days: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _default_is_supported(self) -> "Attribution":
        if self.lookback_days not in self.supported_lookback_days:
            raise ValueError("lookback_days must be one of supported_lookback_days")
        return self


class RuleBook(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    channels: Channels
    campaign_mapping: CampaignMapping
    site: Site
    geography: Geography
    salesforce: Salesforce
    classification: Classification
    attribution: Attribution

    def versions(self) -> dict[str, dict[str, Any]]:
        """{section: {version, verified}}, recorded with every core build."""
        return {
            name: {"version": section.version, "verified": section.verified}
            for name in type(self).model_fields
            if isinstance(section := getattr(self, name), Section)
        }


def load_rulebook(path: Path = RULES_PATH) -> RuleBook:
    return RuleBook.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))


# --- applying the rules -----------------------------------------------------------------


@dataclass(frozen=True)
class Page:
    page_type: str
    service_line: str | None = None
    city: str | None = None


@dataclass(frozen=True)
class CityMatch:
    city: str | None
    region: str | None
    match: str  # one of vocab.CITY_MATCHES


@dataclass(frozen=True)
class EvidenceInput:
    created_at: datetime
    entry_point: str
    ga_client_id: str | None
    meta_campaign_id: str | None
    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None
    click_id_type: str | None
    lead_source: str | None


@dataclass(frozen=True)
class Evidence:
    tier: str  # one of vocab.EVIDENCE_TIERS
    detail: str | None = None  # why a GA id didn't give a journey, when it didn't
    identifier: tuple[str, str] | None = None  # (kind, value) naming the credited campaign
    channel: str | None = None


@dataclass(frozen=True)
class LeadKey:
    source_id: str
    person_key: str | None
    created_at: datetime
    is_test: bool


# "Toronto, Ontario", "Mississauga ON": a trailing province after a comma or a space.
_PROVINCE_SUFFIX = re.compile(r"(?:,\s*|\s+)(?:ontario|on)$")
_SPACES = re.compile(r"\s+")


class Rules:
    def __init__(self, book: RuleBook) -> None:
        self.book = book
        channels = book.channels
        self._search_engines = set(channels.search_engines)
        self._social = set(channels.social_sources)
        self._paid_search = set(channels.paid_search_mediums)
        self._paid_social = set(channels.paid_social_mediums)
        self._email = set(channels.email_mediums)
        self._untagged = {value.casefold() for value in channels.untagged_campaigns}
        geography = book.geography
        self._region_of_city = {c: r.key for r in geography.regions for c in r.cities}
        self._city_by_key = {city.casefold(): city for city in self._region_of_city}
        self._city_aliases = {k.casefold(): v for k, v in geography.city_aliases.items()}
        self._region_aliases = {k.casefold(): v for k, v in geography.region_aliases.items()}
        self._qualified = set(book.salesforce.qualified_stages)
        self.lookback = timedelta(days=book.attribution.lookback_days)
        self.duplicate_window = timedelta(hours=book.classification.duplicate_window_hours)

    # web sessions -------------------------------------------------------------------

    def channel(self, source: str, medium: str) -> str:
        """GA4-style default channel grouping, first match wins."""
        source, medium = source.strip().casefold(), medium.strip().casefold()
        if medium in self._paid_social:
            return "paid_social"
        if medium in self._paid_search:
            return "paid_social" if source in self._social else "paid_search"
        if source == "(direct)" and medium in ("(none)", "(not set)", ""):
            return "direct"
        if medium == "organic":
            return "organic_search"
        if medium in self._email:
            return "email"
        if source in self._social:
            return "organic_social"
        if medium == "referral":
            return "referral"
        return "other"

    def campaign_value(self, value: str | None) -> str | None:
        """Normalized campaign value (case-insensitive), or None for 'no campaign'."""
        if value is None:
            return None
        normalized = value.strip().casefold()
        return None if not normalized or normalized in self._untagged else normalized

    def page(self, path: str) -> Page:
        site = self.book.site
        if path in site.home:
            return Page("home")
        if path in site.quote:
            return Page("quote")
        if path in site.careers:
            return Page("careers")
        if path.startswith(site.blog_prefix):
            return Page("blog")
        if path in site.service_pages:
            return Page("service", service_line=site.service_pages[path])
        if path.startswith(site.location_prefix):
            slug = path.removeprefix(site.location_prefix).strip("/")
            return Page("location", city=self.book.geography.location_slugs.get(slug))
        if path.startswith(site.offer_prefix):
            service = path.removeprefix(site.offer_prefix).strip("/").replace("-", "_")
            return Page("offer", service_line=service if service in vocab.SERVICE_LINES else None)
        return Page("other")

    # leads --------------------------------------------------------------------------

    def city(self, raw: str | None) -> CityMatch:
        if raw is None or not raw.strip():
            return CityMatch(None, None, "blank")
        text = _SPACES.sub(" ", raw.strip())
        if text in self._region_of_city:
            match = "exact" if text == raw else "normalized"
            return CityMatch(text, self._region_of_city[text], match)
        key = _PROVINCE_SUFFIX.sub("", text.casefold()).strip(" ,")
        if key in self._city_by_key:
            city = self._city_by_key[key]
            return CityMatch(city, self._region_of_city[city], "normalized")
        if key in self._city_aliases:
            city = self._city_aliases[key]
            return CityMatch(city, self._region_of_city[city], "alias")
        if key in self._region_aliases:
            return CityMatch(None, self._region_aliases[key], "region_only")
        return CityMatch(None, None, "unrecognized")

    def entry_point(self, raw: str | None) -> str:
        return self.book.salesforce.entry_points.get(raw or "", "unknown")

    def lead_stage(self, raw: str) -> str:
        return self.book.salesforce.lead_stages.get(raw, "unknown")

    def is_qualified(self, stage: str) -> bool:
        return stage in self._qualified

    def request_type(
        self, raw: str | None, entry_point: str, tactic: str | None
    ) -> tuple[str, str]:
        """(request type, where it came from): CRM field, then entry-point default (U-20),
        then the linked campaign's tactic."""
        if raw:
            return self.book.salesforce.request_types.get(raw, "unknown"), "crm_field"
        defaults = self.book.classification
        if entry_point in defaults.entry_point_defaults:
            return defaults.entry_point_defaults[entry_point], "entry_point_default"
        if tactic in defaults.tactic_defaults:
            return defaults.tactic_defaults[tactic], "campaign"
        return "unknown", "unknown"

    def customer_type(self, raw: str | None) -> tuple[str, str]:
        answer = (raw or "").strip().casefold()
        if answer in ("yes", "true"):
            return "existing", "self_reported"
        if answer in ("no", "false"):
            return "new", "self_reported"
        return "unknown", "unknown"

    def service_line(
        self, raw: str | None, page_service: str | None, campaign_service: str | None
    ) -> tuple[str, str]:
        """(service line, source): CRM field, then the form's page, then the campaign."""
        mapped = self.book.salesforce.service_lines.get(raw or "")
        if mapped:
            return mapped, "crm_field"
        if page_service:
            return page_service, "form_page"
        if campaign_service:
            return campaign_service, "campaign"
        return "unknown", "unknown"

    def classify(
        self,
        *,
        request_type: str,
        customer_type: str,
        stage: str,
        is_test: bool,
        is_duplicate: bool,
    ) -> tuple[str, str | None]:
        """(lead class, junk reason), by the ordered rules of
        docs/lifecycle_and_classification.md."""
        if is_test:
            return "junk", "test"
        if stage == "invalid":
            return "junk", "invalid"
        if is_duplicate:
            return "junk", "duplicate"
        if request_type in ("billing", "customer_service", "non_sales_form"):
            return "non_marketing", None
        if request_type in ("repair_service", "maintenance"):
            return "service_demand", None
        if request_type in ("install_replace", "sales_general"):
            if customer_type == "existing":
                return "existing_customer_sales", None
            return "acquisition", None
        return "unknown", None

    def evidence(
        self,
        lead: EvidenceInput,
        journey: Sequence[datetime],
        lookback: timedelta | None = None,
    ) -> Evidence:
        """Evidence tier, first match wins (docs/attribution.md). `journey` = the sorted
        start times of every GA4 session of the lead's GA client id; `lookback` defaults to
        the rule book's."""
        detail = None
        if lead.ga_client_id:
            if not journey:
                detail = "ga_id_unmatched"
            else:
                first = bisect_left(journey, lead.created_at - (lookback or self.lookback))
                if first < len(journey) and journey[first] <= lead.created_at:
                    return Evidence("T1_journey")
                detail = "journey_outside_lookback"
        if lead.entry_point in META_NATIVE_ENTRY_POINTS and lead.meta_campaign_id:
            identifier = ("meta_campaign_id", lead.meta_campaign_id)
            return Evidence("T3_platform_native", detail, identifier, "paid_social")
        if lead.utm_campaign or lead.click_id_type:
            if lead.utm_source and lead.utm_medium:
                channel = self.channel(lead.utm_source, lead.utm_medium)
            else:
                channel = {"gclid": "paid_search", "fbclid": "paid_social"}.get(
                    lead.click_id_type or ""
                )
            value = self.campaign_value(lead.utm_campaign)
            identifier = ("utm_campaign", value) if value else None
            return Evidence("T2_captured_source", detail, identifier, channel)
        reported = self.book.salesforce.lead_source_channels.get(lead.lead_source or "")
        if reported:
            return Evidence("T4_self_reported_channel", detail, None, reported)
        return Evidence("T5_none", detail)

    # appointments and opportunities -------------------------------------------------

    def appointment_kind(self, raw: str) -> str:
        return self.book.salesforce.appointment_kinds.get(raw, "other")

    def appointment_status(self, raw: str | None) -> str:
        return self.book.salesforce.appointment_statuses.get(raw or "", "unknown")

    def amount_basis(self, raw: str | None) -> str:
        return self.book.salesforce.amount_bases.get(raw or "", "unknown")

    def crm_service_line(self, raw: str | None) -> str:
        return self.book.salesforce.service_lines.get(raw or "", "unknown")


def find_duplicates(leads: Iterable[LeadKey], window: timedelta) -> dict[str, str]:
    """{duplicate source id: original source id}.

    Leads of the same person within `window` of the group's first lead are duplicates of
    it; a later lead starts a new group. Test leads and leads without a person key are
    never deduplicated.
    """
    by_person: dict[str, list[LeadKey]] = defaultdict(list)
    for lead in leads:
        if lead.person_key and not lead.is_test:
            by_person[lead.person_key].append(lead)
    duplicates: dict[str, str] = {}
    for group in by_person.values():
        group.sort(key=lambda lead: (lead.created_at, lead.source_id))
        anchor = group[0]
        for lead in group[1:]:
            if lead.created_at - anchor.created_at <= window:
                duplicates[lead.source_id] = anchor.source_id
            else:
                anchor = lead
    return duplicates
