"""Build the core model for one organization from its latest successful staging batches.

The whole build is one transaction: the organization's core rows are deleted and rebuilt
from scratch, so readers see either the previous build or the new one, never a mix, and
running a build twice gives the same result. Each build is recorded in core.build_runs
with the batches and rule versions it used and a data-quality summary.
"""

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, delete, func, insert, select, text

from marketingiq.core import tables as t
from marketingiq.core.records import CoreRecords, build_records
from marketingiq.core.rules import Rules, load_rulebook
from marketingiq.db import copy_records
from marketingiq.ingest.staging import STAGING_TABLES
from marketingiq.models import LoadBatch, Organization

REQUIRED = ("meta_insights_daily", "ga4_sessions", "sf_leads", "campaign_mapping_sheet")
OPTIONAL = ("sf_events", "sf_opportunities", "annotations")


@dataclass(frozen=True)
class BuildResult:
    run_id: int
    batches: dict[str, int]
    summary: dict[str, Any]


def build_core(engine: Engine, org_slug: str, rules: Rules | None = None) -> BuildResult:
    rules = rules or Rules(load_rulebook())
    with engine.begin() as conn:
        org = conn.execute(
            select(Organization.id, Organization.reporting_tz).where(Organization.slug == org_slug)
        ).one_or_none()
        if org is None:
            raise LookupError(f"no organization with slug {org_slug!r}")
        batches = _latest_batches(conn, org.id)
        missing = [entity for entity in REQUIRED if entity not in batches]
        if missing:
            raise LookupError(f"no successful load yet for {missing}; run the loader first")

        staging = {
            entity: _read_batch(conn, entity, batches.get(entity)) for entity in REQUIRED + OPTIONAL
        }
        records = build_records(staging, rules, reporting_tz=org.reporting_tz)

        for table in t.REBUILT_TABLES:
            conn.execute(delete(table).where(table.c.org_id == org.id))
        _write(conn, org.id, records)
        run_id = conn.execute(
            insert(t.build_runs)
            .values(
                org_id=org.id,
                batches=batches,
                rules=rules.book.versions(),
                summary=json.loads(json.dumps(records.summary, default=str)),
            )
            .returning(t.build_runs.c.id)
        ).scalar_one()
    return BuildResult(run_id, batches, records.summary)


def _latest_batches(conn: Connection, org_id: int) -> dict[str, int]:
    rows = conn.execute(
        select(LoadBatch.entity, func.max(LoadBatch.id))
        .where(LoadBatch.org_id == org_id, LoadBatch.status == "succeeded")
        .group_by(LoadBatch.entity)
    )
    return dict(rows.all())


def _read_batch(conn: Connection, entity: str, batch_id: int | None) -> list[dict[str, Any]]:
    if batch_id is None:
        return []
    table = STAGING_TABLES[entity]
    rows = conn.execute(
        select(table).where(table.c.load_batch_id == batch_id).order_by(table.c.source_row)
    )
    return [dict(row) for row in rows.mappings()]


def _ids(conn: Connection, table: Any, key_column: str, org_id: int) -> dict[Any, int]:
    rows = conn.execute(select(table.c[key_column], table.c.id).where(table.c.org_id == org_id))
    return dict(rows.all())


def _write(conn: Connection, org_id: int, records: CoreRecords) -> None:
    if records.campaigns:
        conn.execute(
            insert(t.campaigns), [{"org_id": org_id, **c} for c in records.campaigns.values()]
        )
    campaign_ids = _ids(conn, t.campaigns, "key", org_id)
    if records.identifiers:
        conn.execute(
            insert(t.campaign_identifiers),
            [
                {"org_id": org_id, "campaign_id": campaign_ids[key], "kind": kind, "value": value}
                for key, kind, value in records.identifiers
            ],
        )
    copy_records(
        conn,
        t.ad_spend_daily,
        (
            {"org_id": org_id, "campaign_id": campaign_ids[r["campaign_key"]], **r}
            for r in records.spend
        ),
    )

    if records.pages:
        conn.execute(
            insert(t.landing_pages), [{"org_id": org_id, **p} for p in records.pages.values()]
        )
    page_ids = _ids(conn, t.landing_pages, "path", org_id)
    copy_records(
        conn,
        t.web_sessions,
        (
            {
                "org_id": org_id,
                "campaign_id": campaign_ids.get(s["campaign_key"]),
                "landing_page_id": page_ids[s["landing_page"]],
                **s,
            }
            for s in records.sessions
        ),
    )

    copy_records(
        conn,
        t.leads,
        (
            {
                "org_id": org_id,
                "evidence_campaign_id": campaign_ids.get(lead["evidence_campaign_key"]),
                **lead,
            }
            for lead in records.leads
        ),
    )
    lead_ids = _ids(conn, t.leads, "source_id", org_id)
    duplicates = [
        (lead_ids[lead["source_id"]], lead_ids[lead["duplicate_of_source_id"]])
        for lead in records.leads
        if lead["duplicate_of_source_id"]
    ]
    if duplicates:
        conn.execute(
            text(
                "UPDATE core.leads AS d SET duplicate_of = m.original"
                " FROM unnest(CAST(:duplicates AS bigint[]), CAST(:originals AS bigint[]))"
                " AS m(duplicate, original) WHERE d.id = m.duplicate"
            ),
            {
                "duplicates": [duplicate for duplicate, _ in duplicates],
                "originals": [original for _, original in duplicates],
            },
        )

    copy_records(
        conn,
        t.appointments,
        (
            {"org_id": org_id, "lead_id": lead_ids.get(a["lead_source_id"]), **a}
            for a in records.appointments
        ),
    )
    copy_records(
        conn,
        t.opportunities,
        (
            {"org_id": org_id, "lead_id": lead_ids.get(o["lead_source_id"]), **o}
            for o in records.opportunities
        ),
    )
    if records.annotations:
        conn.execute(insert(t.annotations), [{"org_id": org_id, **a} for a in records.annotations])
