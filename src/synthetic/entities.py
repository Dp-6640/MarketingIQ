"""In-memory records of the simulated world: what really happened, before any recording."""

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(slots=True, eq=False)
class Session:
    pseudo_id: str  # GA cookie id of the visitor
    start: datetime  # UTC
    channel: str  # organic_search, paid_search, direct, referral, organic_social, email, meta
    campaign: str | None  # campaign key, if the visit came from one
    source: str
    medium: str
    # GA4 campaign value for tagged visits: the UTM (which may differ in letter case) or the
    # ad-platform link. "" for untagged visits.
    campaign_name: str
    content: str
    landing_page: str
    device: str
    has_gclid: bool
    has_fbclid: bool
    recorded: bool  # visitor accepted analytics cookies, so GA4 can see the visit
    household: "Household | None"  # None for visitors with no need
    ev_quote_submit: int = 0
    ev_callback_submit: int = 0
    ev_phone_click: int = 0
    ev_chat_start: int = 0
    ev_booking_click: int = 0
    ga_session_id: int = 0  # assigned at export


@dataclass(slots=True, eq=False)
class Household:
    key: tuple[int, ...]  # random-stream key; stable when unrelated records change
    person_key: str  # pseudonymous household key
    region: str
    city: str
    need: str
    service_line: str | None
    request: str
    customer_type: str  # new | existing
    intent: float  # hidden 0-1 score; drives conversion and qualification
    consent: bool  # accepts analytics and advertising cookies
    device: str
    system_age: int  # years; old systems can turn a repair into a replacement sale
    origin_channel: str  # channel of the first contact: a web channel, "meta" or "offline"
    origin_campaign: str | None
    origin_day: date
    pseudo_id: str | None = None
    sessions: list[Session] = field(default_factory=list)
    converts: bool = False
    entry_point: str | None = None
    lead_at: datetime | None = None
    retargeted: bool = False  # a retargeting click happened before the lead (truth for S08)
    hid: int = 0  # display id, assigned at export


@dataclass(slots=True, eq=False)
class MetaDay:
    """One campaign on one day of the ad account's time zone."""

    campaign: str
    day: date
    spend: float
    impressions: int
    clicks: int
    landed: int = 0  # retargeting: clicks that reached the website (placed by the overlay)
    reported_leads: int = 0
