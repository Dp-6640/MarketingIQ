"""The canonical values of the core model (docs/lifecycle_and_classification.md)."""

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
    "unknown",
)
REQUEST_TYPES = (
    "install_replace",
    "repair_service",
    "maintenance",
    "sales_general",
    "billing",
    "customer_service",
    "non_sales_form",
    "other",
    "unknown",
)
REQUEST_TYPE_SOURCES = ("crm_field", "entry_point_default", "campaign", "unknown")
CUSTOMER_TYPES = ("new", "existing", "unknown")
CUSTOMER_TYPE_SOURCES = ("self_reported", "crm_match", "unknown")
SERVICE_LINE_SOURCES = ("crm_field", "form_page", "campaign", "unknown")
LEAD_CLASSES = (
    "acquisition",
    "existing_customer_sales",
    "service_demand",
    "non_marketing",
    "junk",
    "unknown",
)
JUNK_REASONS = ("test", "invalid", "duplicate")
LEAD_STAGES = (
    "new",
    "working",
    "qualified",
    "disqualified",
    "converted",
    "invalid",
    "service_scheduled",
    "closed_no_action",
    "unknown",
)
CHANNELS = (
    "organic_search",
    "paid_search",
    "paid_social",
    "organic_social",
    "direct",
    "referral",
    "email",
    "other",
)
# Channels only a self-reported lead source can name (evidence tier T4).
REPORTED_CHANNELS = (
    *CHANNELS,
    "search_unspecified",
    "social_unspecified",
    "offline_media",
    "word_of_mouth",
)
EVIDENCE_TIERS = (
    "T1_journey",
    "T2_captured_source",
    "T3_platform_native",
    "T4_self_reported_channel",
    "T5_none",
)
PAGE_TYPES = ("home", "service", "location", "offer", "quote", "careers", "blog", "other")
CITY_MATCHES = ("exact", "normalized", "alias", "region_only", "blank", "unrecognized")
APPOINTMENT_KINDS = ("in_home_consultation", "service_visit", "other")
APPOINTMENT_STATUSES = ("booked", "completed", "no_show", "cancelled", "unknown")
OPPORTUNITY_OUTCOMES = ("open", "won", "lost")
AMOUNT_BASES = ("purchase_price", "financed_total", "lease_contract", "monthly", "unknown")
