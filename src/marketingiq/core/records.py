"""Staging rows -> core records. Pure: no database, so the whole step is testable in memory.

Records refer to each other by natural keys (campaign key, page path, Salesforce Id); the
build step turns those into database ids when it writes them.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from marketingiq.core import vocabulary as vocab
from marketingiq.core.rules import EvidenceInput, LeadKey, Rules, find_duplicates

Row = dict[str, Any]


@dataclass
class CoreRecords:
    campaigns: dict[str, Row] = field(default_factory=dict)  # by campaign key
    identifiers: list[tuple[str, str, str]] = field(default_factory=list)  # key, kind, value
    spend: list[Row] = field(default_factory=list)
    pages: dict[str, Row] = field(default_factory=dict)  # by path
    sessions: list[Row] = field(default_factory=list)
    leads: list[Row] = field(default_factory=list)
    appointments: list[Row] = field(default_factory=list)
    opportunities: list[Row] = field(default_factory=list)
    annotations: list[Row] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def build_records(staging: dict[str, list[Row]], rules: Rules, *, reporting_tz: str) -> CoreRecords:
    records = CoreRecords()
    by_identifier = _campaigns(staging, rules, records)
    journeys = _sessions(staging["ga4_sessions"], rules, by_identifier, records)
    _leads(staging["sf_leads"], rules, by_identifier, journeys, records)
    _appointments_and_opportunities(staging, rules, records)
    records.annotations = [
        {k: row[k] for k in ("annotation_type", "start_date", "end_date", "label")}
        for row in staging["annotations"]
    ]
    records.summary = _summary(staging, records, reporting_tz)
    return records


def _campaigns(
    staging: dict[str, list[Row]], rules: Rules, records: CoreRecords
) -> dict[tuple[str, str], str]:
    """Campaigns from the team's mapping sheet, plus any Meta campaign with spend that the
    sheet doesn't mention (it stays unmapped: its UTM can't be linked to it)."""
    by_identifier: dict[tuple[str, str], str] = {}

    def identify(key: str, kind: str, value: str) -> None:
        if (kind, value) not in by_identifier:
            by_identifier[(kind, value)] = key
            records.identifiers.append((key, kind, value))

    for row in staging["campaign_mapping_sheet"]:
        utm = rules.campaign_value(row["utm_campaign"])
        if utm is None or utm in records.campaigns:
            continue
        records.campaigns[utm] = {
            "key": utm,
            "name": row["campaign_name"],
            "platform": row["platform"],
            "platform_campaign_id": row["platform_campaign_id"],
            "utm_campaign": utm,
            "tactic": row["tactic"],
            "service_lines": [s for s in (row["service_lines"] or "").split("|") if s],
            "region": row["region"],
            "in_mapping_sheet": True,
            "has_spend_feed": False,
        }
        identify(utm, "utm_campaign", utm)
        if row["platform"] == "meta" and row["platform_campaign_id"]:
            identify(utm, "meta_campaign_id", row["platform_campaign_id"])

    for row in staging["meta_insights_daily"]:
        campaign_id = row["campaign_id"]
        key = by_identifier.get(("meta_campaign_id", campaign_id))
        if key is None:
            key = f"meta:{campaign_id}"
            records.campaigns[key] = {
                "key": key,
                "name": row["campaign_name"],
                "platform": "meta",
                "platform_campaign_id": campaign_id,
                "utm_campaign": None,
                "tactic": None,
                "service_lines": [],
                "region": None,
                "in_mapping_sheet": False,
                "has_spend_feed": False,
            }
            identify(key, "meta_campaign_id", campaign_id)
        records.campaigns[key]["has_spend_feed"] = True
        records.spend.append(
            {
                "campaign_key": key,
                "report_date": row["report_date"],
                "source_tz": row["account_timezone"],
                "spend": row["spend"],
                "impressions": row["impressions"],
                "link_clicks": row["inline_link_clicks"],
                "platform_reported_leads": row["leads_reported"],
                "attribution_setting": row["attribution_setting"],
            }
        )
    return by_identifier


def _page(path: str, rules: Rules, records: CoreRecords) -> None:
    if path not in records.pages:
        page = rules.page(path)
        records.pages[path] = {
            "path": path,
            "page_type": page.page_type,
            "service_line": page.service_line,
            "city": page.city,
        }


def _sessions(
    rows: list[Row],
    rules: Rules,
    by_identifier: dict[tuple[str, str], str],
    records: CoreRecords,
) -> dict[str, list[datetime]]:
    """Canonical sessions; returns each GA client id's sorted session start times."""
    journeys: dict[str, list[datetime]] = defaultdict(list)
    for row in rows:
        value = rules.campaign_value(row["campaign"])
        _page(row["landing_page"], rules, records)
        records.sessions.append(
            {
                "user_pseudo_id": row["user_pseudo_id"],
                "ga_session_id": row["ga_session_id"],
                "started_at": row["session_start_utc"],
                "source": row["source"],
                "medium": row["medium"],
                "channel": rules.channel(row["source"], row["medium"]),
                "campaign_value": value,
                "campaign_key": by_identifier.get(("utm_campaign", value)) if value else None,
                "landing_page": row["landing_page"],
                "device": row["device_category"],
                "has_gclid": row["has_gclid"],
                "has_fbclid": row["has_fbclid"],
                **{name: row[name] for name in _EVENTS},
            }
        )
        journeys[row["user_pseudo_id"]].append(row["session_start_utc"])
    for starts in journeys.values():
        starts.sort()
    return journeys


_EVENTS = (
    "ev_quote_submit",
    "ev_callback_submit",
    "ev_phone_click",
    "ev_chat_start",
    "ev_booking_click",
)


def _leads(
    rows: list[Row],
    rules: Rules,
    by_identifier: dict[tuple[str, str], str],
    journeys: dict[str, list[datetime]],
    records: CoreRecords,
) -> None:
    keys = [LeadKey(r["id"], r["person_key"], r["created_date"], r["is_test"]) for r in rows]
    duplicates = find_duplicates(keys, rules.duplicate_window)
    version = rules.book.classification.version

    for row in rows:
        entry_point = rules.entry_point(row["entry_point"])
        stage = rules.lead_stage(row["status"])
        utm = rules.campaign_value(row["utm_campaign"])

        # The campaign the lead itself names (native Meta id first, then captured UTM).
        linked_key = None
        if row["meta_campaign_id"]:
            linked_key = by_identifier.get(("meta_campaign_id", row["meta_campaign_id"]))
        if linked_key is None and utm:
            linked_key = by_identifier.get(("utm_campaign", utm))
        linked = records.campaigns.get(linked_key) if linked_key else None
        linked_services = [s for s in (linked or {}).get("service_lines", []) if s]
        campaign_service = linked_services[0] if len(linked_services) == 1 else None
        if campaign_service not in vocab.SERVICE_LINES:
            campaign_service = None

        page = rules.page(row["form_page_path"]) if row["form_page_path"] else None
        request_type, request_source = rules.request_type(
            row["request_type"], entry_point, linked["tactic"] if linked else None
        )
        customer_type, customer_source = rules.customer_type(row["existing_customer"])
        service_line, service_source = rules.service_line(
            row["service_line"], page.service_line if page else None, campaign_service
        )
        city = rules.city(row["city"])
        duplicate_of = duplicates.get(row["id"])
        lead_class, junk_reason = rules.classify(
            request_type=request_type,
            customer_type=customer_type,
            stage=stage,
            is_test=row["is_test"],
            is_duplicate=duplicate_of is not None,
        )

        evidence = None
        if duplicate_of is None:
            evidence = rules.evidence(
                EvidenceInput(
                    created_at=row["created_date"],
                    entry_point=entry_point,
                    ga_client_id=row["ga_client_id"],
                    meta_campaign_id=row["meta_campaign_id"],
                    utm_source=row["utm_source"],
                    utm_medium=row["utm_medium"],
                    utm_campaign=row["utm_campaign"],
                    click_id_type=row["click_id_type"],
                    lead_source=row["lead_source"],
                ),
                journeys.get(row["ga_client_id"] or "", []),
            )

        records.leads.append(
            {
                "source_id": row["id"],
                "created_at": row["created_date"],
                "lead_source_raw": row["lead_source"],
                "status_raw": row["status"],
                "stage": stage,
                "is_qualified": rules.is_qualified(stage),
                "qualified_at": row["qualified_date"],
                "stage_time_source": "field" if row["qualified_date"] else "unavailable",
                "is_converted": row["is_converted"],
                "converted_opportunity_source_id": row["converted_opportunity_id"],
                "entry_point": entry_point,
                "entry_point_raw": row["entry_point"],
                "request_type": request_type,
                "request_type_source": request_source,
                "customer_type": customer_type,
                "customer_type_source": customer_source,
                "service_line": service_line,
                "service_line_source": service_source,
                "lead_class": lead_class,
                "junk_reason": junk_reason,
                "classification_version": version,
                "city_raw": row["city"],
                "city": city.city,
                "region": city.region,
                "city_match": city.match,
                "person_key": row["person_key"],
                "is_test": row["is_test"],
                "duplicate_of_source_id": duplicate_of,
                "ga_client_id": row["ga_client_id"],
                "form_page_path": row["form_page_path"],
                "utm_source": row["utm_source"],
                "utm_medium": row["utm_medium"],
                "utm_campaign": utm,
                "click_id_type": row["click_id_type"],
                "meta_campaign_source_id": row["meta_campaign_id"],
                "evidence_tier": evidence.tier if evidence else None,
                "evidence_detail": evidence.detail if evidence else None,
                "evidence_campaign_key": (
                    by_identifier.get(evidence.identifier)
                    if evidence and evidence.identifier
                    else None
                ),
                "evidence_channel": evidence.channel if evidence else None,
            }
        )


def _appointments_and_opportunities(
    staging: dict[str, list[Row]], rules: Rules, records: CoreRecords
) -> None:
    lead_for_opportunity = {
        lead["converted_opportunity_source_id"]: lead["source_id"]
        for lead in records.leads
        if lead["converted_opportunity_source_id"]
    }
    for row in staging["sf_events"]:
        records.appointments.append(
            {
                "source_id": row["id"],
                "lead_source_id": row["who_id"],
                "kind": rules.appointment_kind(row["event_type"]),
                "kind_raw": row["event_type"],
                "status": rules.appointment_status(row["appointment_status"]),
                "status_raw": row["appointment_status"],
                "booked_at": row["created_date"],
                "scheduled_for": row["activity_date_time"],
            }
        )
    for row in staging["sf_opportunities"]:
        outcome = ("won" if row["is_won"] else "lost") if row["is_closed"] else "open"
        records.opportunities.append(
            {
                "source_id": row["id"],
                "lead_source_id": lead_for_opportunity.get(row["id"]),
                "created_at": row["created_date"],
                "stage_raw": row["stage_name"],
                "outcome": outcome,
                "close_date": row["close_date"],
                "amount": row["amount"],
                "amount_basis": rules.amount_basis(row["amount_basis"]),
                "amount_basis_raw": row["amount_basis"],
                "service_line": rules.crm_service_line(row["service_line"]),
                "service_line_raw": row["service_line"],
            }
        )


def _counts(values: list[Any]) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def _summary(staging: dict[str, list[Row]], records: CoreRecords, reporting_tz: str) -> dict:
    """A data-quality overview of the build, stored with it in core.build_runs."""
    leads = records.leads
    tiered = [lead for lead in leads if lead["evidence_tier"]]
    acquisition = [lead for lead in leads if lead["lead_class"] == "acquisition"]
    lead_ids = {lead["source_id"] for lead in leads}
    unmapped = Counter(
        s["campaign_value"]
        for s in records.sessions
        if s["campaign_value"] and not s["campaign_key"]
    )
    meta_timezones = sorted({row["account_timezone"] for row in staging["meta_insights_daily"]})
    return {
        "leads": {
            "total": len(leads),
            "by_class": _counts([lead["lead_class"] for lead in leads]),
            "junk_reasons": _counts([lead["junk_reason"] for lead in leads if lead["junk_reason"]]),
            "request_type_sources": _counts([lead["request_type_source"] for lead in leads]),
            "acquisition_with_unknown_customer_type": sum(
                1 for lead in acquisition if lead["customer_type"] == "unknown"
            ),
            "evidence_tiers": _counts([lead["evidence_tier"] for lead in tiered]),
            "evidence_details": _counts(
                [lead["evidence_detail"] for lead in tiered if lead["evidence_detail"]]
            ),
            "city_matches": _counts([lead["city_match"] for lead in leads]),
        },
        "sessions": {
            "total": len(records.sessions),
            "by_channel": _counts([s["channel"] for s in records.sessions]),
            "unmapped_campaign_values": dict(sorted(unmapped.items())),
        },
        "campaigns": {
            "total": len(records.campaigns),
            "spend_but_not_in_mapping_sheet": sorted(
                c["name"] for c in records.campaigns.values() if not c["in_mapping_sheet"]
            ),
        },
        "appointments": {
            "total": len(records.appointments),
            "without_lead": sum(
                1 for a in records.appointments if a["lead_source_id"] not in lead_ids
            ),
        },
        "opportunities": {
            "total": len(records.opportunities),
            "without_lead": sum(1 for o in records.opportunities if not o["lead_source_id"]),
        },
        "timezones": {
            "reporting": reporting_tz,
            "meta_accounts": meta_timezones,
            "mismatch": any(tz != reporting_tz for tz in meta_timezones),
        },
    }
