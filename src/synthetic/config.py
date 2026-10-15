"""Generator configuration: every synthetic assumption in one validated object.

Values live in TOML files in src/synthetic/config/. docs/synthetic-data.md is the
human-readable version of default.toml.

A file can `extends` another one. Top-level sections merge key by key. Inside a section, a
table whose values are all numbers (a distribution or multiplier map) replaces the base table
as a whole, other tables merge recursively, and arrays always replace.
"""

import hashlib
import tomllib
from datetime import date
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

CONFIG_DIR = Path(__file__).parent / "config"

SERVICE_LINES = (
    "furnace",
    "air_conditioner",
    "heat_pump",
    "water_heater",
    "water_treatment",
    "air_quality",
    "security",
    "generator",
    "maintenance_plan",
)
NEEDS = (
    "planned_replacement",
    "emergency_repair",
    "research",
    "existing_service",
    "billing",
    "junk",
)
ENTRY_POINTS = (
    "web_quote_form",
    "web_callback_form",
    "booking",
    "phone",
    "web_chat_agent",
    "meta_messaging_agent",
    "meta_lead_form",
    "email_sms",
    "other",
)
# Entry points that happen on the website, during a session.
WEB_ENTRY_POINTS = ("web_quote_form", "web_callback_form", "booking", "web_chat_agent")
REQUESTS = (
    "install_replace",
    "sales_general",
    "repair_service",
    "maintenance",
    "billing",
    "customer_service",
    "non_sales_form",
    "spam",
)
WEB_CHANNELS = ("organic_search", "paid_search", "direct", "referral", "organic_social", "email")
DEVICES = ("mobile", "desktop", "tablet")
PAGE_KINDS = ("home", "service", "location", "offer", "quote", "careers", "blog")
AMOUNT_BASES = ("purchase_price", "financed_total", "lease_contract", "monthly")
AMBIENT_EVENTS = ("phone_click", "chat_start", "booking_click")
META_TACTICS = ("prospecting", "retargeting", "lead_form", "messaging", "promo")
Tactic = Literal["prospecting", "retargeting", "lead_form", "messaging", "promo", "search", "email"]


# --- reusable validated types ---------------------------------------------------------


def _check_keys(value: dict[str, Any], allowed: tuple[str, ...]) -> dict[str, Any]:
    unknown = [key for key in value if key not in allowed]
    if unknown:
        raise ValueError(f"unknown keys {unknown}; allowed: {list(allowed)}")
    return value


def _check_distribution(
    value: dict[str, float], allowed: tuple[str, ...] | None
) -> dict[str, float]:
    if not value:
        raise ValueError("distribution is empty")
    if allowed is not None:
        _check_keys(value, allowed)
    if any(share < 0 for share in value.values()):
        raise ValueError("shares must be non-negative")
    total = sum(value.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"shares sum to {total:.6f}, expected 1")
    return value


def _check_probabilities(value: dict[str, float], allowed: tuple[str, ...]) -> dict[str, float]:
    _check_keys(value, allowed)
    if any(not 0.0 <= p <= 1.0 for p in value.values()):
        raise ValueError("probabilities must be between 0 and 1")
    return value


def _check_multipliers(value: dict[str, float], allowed: tuple[str, ...]) -> dict[str, float]:
    _check_keys(value, allowed)
    if any(m < 0 for m in value.values()):
        raise ValueError("multipliers must be non-negative")
    return value


def _distribution(allowed: tuple[str, ...] | None = None) -> Any:
    check = partial(_check_distribution, allowed=allowed)
    return Annotated[dict[str, float], AfterValidator(check)]


def _probabilities(allowed: tuple[str, ...]) -> Any:
    check = partial(_check_probabilities, allowed=allowed)
    return Annotated[dict[str, float], AfterValidator(check)]


def _multipliers(allowed: tuple[str, ...]) -> Any:
    check = partial(_check_multipliers, allowed=allowed)
    return Annotated[dict[str, float], AfterValidator(check)]


def _check_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown time zone {name!r}") from exc
    return name


def _check_range(value: tuple[float, float]) -> tuple[float, float]:
    if value[0] > value[1]:
        raise ValueError("range must be [low, high] with low <= high")
    return value


def _check_hours(value: list[float]) -> list[float]:
    if len(value) != 24 or any(w < 0 for w in value) or sum(value) <= 0:
        raise ValueError("hour weights must be 24 non-negative numbers with a positive sum")
    return value


def parse_month_day(text: str) -> tuple[int, int]:
    """'MM-DD' -> (month, day); validated against a non-leap year."""
    try:
        parsed = date.fromisoformat(f"2001-{text}")
    except ValueError as exc:
        raise ValueError(f"expected MM-DD, got {text!r}") from exc
    return parsed.month, parsed.day


Prob = Annotated[float, Field(ge=0.0, le=1.0)]
Range = Annotated[tuple[float, float], AfterValidator(_check_range)]
TimeZoneName = Annotated[str, AfterValidator(_check_timezone)]
HourWeights = Annotated[list[float], AfterValidator(_check_hours)]
AnyDistribution = _distribution()
ChannelDistribution = _distribution(WEB_CHANNELS)
DeviceDistribution = _distribution(DEVICES)
EntryPointDistribution = _distribution(ENTRY_POINTS)
NeedDistribution = _distribution(NEEDS)
PageKindDistribution = _distribution(PAGE_KINDS)
RequestDistribution = _distribution(REQUESTS)
ServiceDistribution = _distribution(SERVICE_LINES)
AmountBasisDistribution = _distribution(AMOUNT_BASES)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- sections -------------------------------------------------------------------------


class Window(StrictModel):
    start: date
    end: date
    data_as_of: date
    burn_in_days: int = Field(30, ge=0, le=120)

    @model_validator(mode="after")
    def _ordered(self) -> "Window":
        if not self.start <= self.data_as_of <= self.end:
            raise ValueError("expected start <= data_as_of <= end")
        return self


class Organization(StrictModel):
    slug: str
    name: str
    reporting_tz: TimeZoneName
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    site: str


class MetaAccount(StrictModel):
    account_id: str
    timezone: TimeZoneName
    attribution_setting: str
    click_window_days: int = Field(ge=1, le=28)
    view_through_rate: float = Field(ge=0)
    landing_rate: Prob


class Traffic(StrictModel):
    demand_households_per_day: float = Field(gt=0)
    no_need_sessions_per_day: float = Field(ge=0)
    growth_per_year: float = Field(gt=-1)
    growth_by_service: _multipliers(SERVICE_LINES) = Field(default_factory=dict)
    weekday: Annotated[list[float], Field(min_length=7, max_length=7)]
    analytics_consent_rate: Prob
    click_id_rate: Prob
    utm_case_variant_rate: Prob
    journey_cap_days: int = Field(ge=1)
    phone_click_on_last_session: Prob
    device_mix: DeviceDistribution
    no_need_channels: ChannelDistribution
    later_touch_channels: ChannelDistribution
    ambient_events: _probabilities(AMBIENT_EVENTS)
    channel_campaigns: dict[str, str]
    meta_prospect_needs: NeedDistribution
    meta_native_needs: NeedDistribution


class Sources(StrictModel):
    organic_search: AnyDistribution
    referral: AnyDistribution
    organic_social: AnyDistribution
    meta: AnyDistribution


class Need(StrictModel):
    share: Prob
    existing_customer_share: Prob
    intent: tuple[float, float]  # Beta(a, b)
    web_share: Prob
    sessions_extra_mean: float = Field(ge=0)
    journey_median_days: float = Field(ge=0)
    convert_base: Prob
    convert_intent_slope: float = Field(ge=0)
    service_mix: str | None = None
    hours: str
    first_touch: ChannelDistribution
    entry_points: EntryPointDistribution
    offline_entry_points: EntryPointDistribution
    requests: RequestDistribution

    @model_validator(mode="after")
    def _positive_beta(self) -> "Need":
        if min(self.intent) <= 0:
            raise ValueError("intent Beta parameters must be positive")
        return self


class City(StrictModel):
    name: str
    weight: float = Field(gt=0)
    slug: str = ""  # location page slug, if the city has one
    aliases: list[str] = Field(default_factory=list)


class Region(StrictModel):
    key: str
    name: str
    share: Prob
    cities: list[City] = Field(min_length=1)


class Pages(StrictModel):
    home: str
    quote: str
    careers: str
    blog: str
    location_prefix: str
    offer_prefix: str
    service: dict[str, str]

    @model_validator(mode="after")
    def _all_services(self) -> "Pages":
        if set(self.service) != set(SERVICE_LINES):
            raise ValueError("pages.service needs exactly one page per service line")
        return self


class CampaignConfig(StrictModel):
    key: str
    display_name: str
    platform: Literal["meta", "google_ads", "email"]
    platform_campaign_id: str = ""
    tactic: Tactic
    utm_campaign: str
    # Empty means "not tied to a service line" (the acquisition mix is used where needed).
    service_lines: dict[str, float] = Field(default_factory=dict)
    region: str = ""  # empty = all regions
    seasons: list[tuple[str, str]] = Field(default_factory=list)  # recurring MM-DD ranges
    start: date | None = None
    end: date | None = None
    daily_budget: float = Field(0.0, ge=0)
    cpm: float = Field(0.0, ge=0)
    link_ctr: Prob = 0.0
    audience_quality: Prob = 0.0  # prospecting/promo: share of landed clicks that are prospects
    form_completion: Prob = 0.0  # lead_form: share of clicks that submit the form
    conversation_to_lead: Prob = 0.0  # messaging: share of clicks that become a lead
    need_click_share: Prob = 0.0  # retargeting: share of landed clicks from in-journey prospects
    landing: str = ""  # landing-page profile in [landing]
    mapped: bool = True  # False = missing from the team's mapping sheet (scenario S09)

    @model_validator(mode="after")
    def _consistent(self) -> "CampaignConfig":
        if self.service_lines:
            _check_distribution(self.service_lines, SERVICE_LINES)
        for first, last in self.seasons:
            parse_month_day(first)
            parse_month_day(last)
        if self.start and self.end and self.start > self.end:
            raise ValueError(f"{self.key}: start is after end")
        if self.platform != "meta":
            if self.daily_budget:
                raise ValueError(f"{self.key}: only Meta campaigns have a spend feed")
            return self
        if self.tactic not in META_TACTICS:
            raise ValueError(f"{self.key}: tactic {self.tactic!r} is not a Meta tactic")
        if self.daily_budget <= 0 or self.cpm <= 0 or self.link_ctr <= 0:
            raise ValueError(f"{self.key}: Meta campaigns need daily_budget, cpm and link_ctr")
        required = {
            "prospecting": ("audience_quality", "landing"),
            "promo": ("audience_quality", "landing"),
            "retargeting": ("need_click_share", "landing"),
            "lead_form": ("form_completion",),
            "messaging": ("conversation_to_lead",),
        }[self.tactic]
        missing = [name for name in required if not getattr(self, name)]
        if missing:
            raise ValueError(f"{self.key}: {self.tactic} campaigns need {missing}")
        return self


class DemandEvent(StrictModel):
    id: str
    kind: str
    label: str
    start: date
    end: date
    need_multipliers: _multipliers(NEEDS)
    repair_service_mix: ServiceDistribution | None = None
    annotate: bool = True


class CampaignModifier(StrictModel):
    id: str
    label: str
    campaign: str
    start: date
    end: date
    budget: float = Field(1.0, ge=0)
    ctr: float = Field(1.0, ge=0)
    audience_quality: float = Field(1.0, ge=0)


class PageChange(StrictModel):
    id: str
    label: str
    date: date
    path_prefix: str
    conversion_multiplier: float = Field(ge=0)
    clarity_friction_multiplier: float = Field(ge=0)
    annotate: bool = True


class CaptureOutage(StrictModel):
    id: str
    label: str
    start: date
    end: date


class Qualification(StrictModel):
    intent_reference: float = Field(gt=0, le=1)
    intent_factor_range: Range
    by_entry_point: _multipliers(ENTRY_POINTS)
    by_origin_channel: _multipliers(WEB_CHANNELS)
    decision_days: Range


class Lifecycle(StrictModel):
    qualify: Prob
    consultation: bool
    book: Prob = 0.0
    complete: Prob = 0.0
    opportunity: Prob
    win: Prob
    close_median_days: float = Field(gt=0)
    amount_median: float = Field(gt=0)

    @model_validator(mode="after")
    def _consultation_rates(self) -> "Lifecycle":
        if self.consultation and (self.book <= 0 or self.complete <= 0):
            raise ValueError("service lines with a consultation need book and complete rates")
        return self


class RepairToReplacement(StrictModel):
    min_system_age: int = Field(ge=0)
    rate: Prob
    win: Prob
    close_median_days: float = Field(gt=0)


class LifecycleCommon(StrictModel):
    close_sigma: float = Field(gt=0)
    amount_sigma: float = Field(ge=0)
    amount_basis: AmountBasisDistribution
    financed_markup: float = Field(ge=1)
    lease_months: int = Field(gt=0)
    monthly_divisor: float = Field(gt=0)
    booking_lead_days: Range
    open_quote_expected_days: int = Field(gt=0)
    no_show_share_of_incomplete: Prob
    service_visit_book: Prob
    service_visit_complete: Prob
    repair_to_replacement: RepairToReplacement


class Recording(StrictModel):
    utm_capture: Prob
    ga_id_capture_given_consent: Prob
    form_page_capture: Prob
    booking_capture: Prob
    chat_capture: Prob
    capture_lookback_days: int = Field(ge=1)
    meta_id_on_lead_form: Prob
    meta_id_on_messaging: Prob
    phone_lead_source_self_reported: Prob
    lead_source_wrong: Prob
    request_type_recorded: _probabilities(ENTRY_POINTS)
    existing_customer_recorded: _probabilities(ENTRY_POINTS)
    service_line_recorded: _probabilities(ENTRY_POINTS)
    city_blank: _probabilities(ENTRY_POINTS)
    city_variant: Prob
    city_unrecognizable: Prob
    unrecognizable_cities: list[str] = Field(min_length=1)
    qualified_date_recorded: Prob
    duplicate_within_72h: Prob
    resubmission_after_72h: Prob
    test_leads: Prob
    duplicate_session_rows: Prob


class Clarity(StrictModel):
    bot_session_rate: float = Field(ge=0)
    session_count_noise: Prob
    dead_click_rate: float = Field(ge=0)
    rage_click_rate: float = Field(ge=0)
    location_rage_click_rate: float = Field(ge=0)
    quickback_rate: float = Field(ge=0)
    excessive_scroll_rate: float = Field(ge=0)
    script_error_rate: float = Field(ge=0)
    scroll_depth_range: Range


# --- root -----------------------------------------------------------------------------


class WorldConfig(StrictModel):
    name: str
    window: Window
    organization: Organization
    meta_account: MetaAccount
    traffic: Traffic
    sources: Sources
    hours: dict[str, HourWeights]
    needs: dict[str, Need]
    service_mixes: dict[str, ServiceDistribution]
    seasonality: dict[str, list[float]]
    regions: list[Region] = Field(min_length=1)
    pages: Pages
    landing: dict[str, PageKindDistribution]
    campaigns: list[CampaignConfig]
    demand_events: list[DemandEvent] = Field(default_factory=list)
    campaign_modifiers: list[CampaignModifier] = Field(default_factory=list)
    page_changes: list[PageChange] = Field(default_factory=list)
    capture_outages: list[CaptureOutage] = Field(default_factory=list)
    qualification: Qualification
    lifecycle: dict[str, Lifecycle]
    lifecycle_common: LifecycleCommon
    recording: Recording
    clarity: Clarity

    @model_validator(mode="after")
    def _cross_references(self) -> "WorldConfig":
        if set(self.needs) != set(NEEDS):
            raise ValueError(f"needs must define exactly {list(NEEDS)}")
        _check_distribution({key: need.share for key, need in self.needs.items()}, NEEDS)
        for key, need in self.needs.items():
            if need.service_mix is not None and need.service_mix not in self.service_mixes:
                raise ValueError(f"needs.{key}: unknown service_mix {need.service_mix!r}")
            if need.hours not in self.hours:
                raise ValueError(f"needs.{key}: unknown hours profile {need.hours!r}")

        _check_keys(self.seasonality, SERVICE_LINES)
        for service, values in self.seasonality.items():
            if len(values) != 12 or min(values) <= 0:
                raise ValueError(f"seasonality.{service}: expected 12 positive monthly values")

        region_keys = [region.key for region in self.regions]
        if len(set(region_keys)) != len(region_keys):
            raise ValueError("region keys must be unique")
        _check_distribution({r.key: r.share for r in self.regions}, None)

        for profile in (*WEB_CHANNELS, "no_need"):
            if profile not in self.landing:
                raise ValueError(f"landing profile {profile!r} is missing")
        if set(self.lifecycle) != set(SERVICE_LINES):
            raise ValueError("lifecycle needs exactly one entry per service line")

        self._check_campaigns(region_keys)
        return self

    def _check_campaigns(self, region_keys: list[str]) -> None:
        keys = [c.key for c in self.campaigns]
        if len(set(keys)) != len(keys):
            raise ValueError("campaign keys must be unique")
        utms = [c.utm_campaign.lower() for c in self.campaigns]
        if len(set(utms)) != len(utms):
            raise ValueError("utm_campaign values must be unique (case-insensitive)")
        meta_ids = [c.platform_campaign_id for c in self.campaigns if c.platform == "meta"]
        if len(set(meta_ids)) != len(meta_ids) or not all(meta_ids):
            raise ValueError("Meta campaigns need unique platform_campaign_id values")
        by_key = {c.key: c for c in self.campaigns}
        for campaign in self.campaigns:
            if campaign.region and campaign.region not in region_keys:
                raise ValueError(f"{campaign.key}: unknown region {campaign.region!r}")
            if campaign.landing and campaign.landing not in self.landing:
                raise ValueError(f"{campaign.key}: unknown landing profile {campaign.landing!r}")
        for channel, key in self.traffic.channel_campaigns.items():
            if channel not in WEB_CHANNELS or key not in by_key or by_key[key].platform == "meta":
                raise ValueError(f"channel_campaigns.{channel}: needs a non-Meta campaign key")
        for modifier in self.campaign_modifiers:
            if modifier.campaign not in by_key or by_key[modifier.campaign].platform != "meta":
                raise ValueError(f"{modifier.id}: unknown Meta campaign {modifier.campaign!r}")


# --- loading --------------------------------------------------------------------------


def load_config(name_or_path: str | Path = "default") -> WorldConfig:
    """Load a config by name (a file in CONFIG_DIR) or by path to a .toml file."""
    return WorldConfig.model_validate(_read(_resolve(name_or_path, CONFIG_DIR), frozenset()))


def config_digest(config: WorldConfig) -> str:
    """SHA-256 of the fully merged, validated config."""
    return hashlib.sha256(config.model_dump_json().encode()).hexdigest()


def _resolve(name_or_path: str | Path, base_dir: Path) -> Path:
    path = Path(name_or_path)
    return path if path.suffix == ".toml" else base_dir / f"{name_or_path}.toml"


def _read(path: Path, seen: frozenset[Path]) -> dict[str, Any]:
    if path in seen:
        raise ValueError(f"circular 'extends' involving {path.name}")
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    base = raw.pop("extends", None)
    if base is None:
        return raw
    return _merge(_read(_resolve(base, path.parent), seen | {path}), raw)


def _is_number_map(value: dict[str, Any]) -> bool:
    return all(isinstance(v, int | float) and not isinstance(v, bool) for v in value.values())


def _merge(base: dict[str, Any], override: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        mergeable = isinstance(value, dict) and isinstance(current, dict)
        if mergeable and (depth == 0 or not _is_number_map(value)):
            merged[key] = _merge(current, value, depth + 1)
        else:
            merged[key] = value
    return merged
