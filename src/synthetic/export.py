"""Write a generated world to disk: source-shaped files, ground truth and a manifest."""

import csv
import hashlib
import json
import shutil
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

from synthetic import __version__
from synthetic.config import WEB_ENTRY_POINTS, WorldConfig, config_digest, load_config
from synthetic.generator import World, simulate
from synthetic.recording import (
    Table,
    annotation_table,
    assign_identifiers,
    clarity_table,
    ga4_table,
    mapping_table,
    meta_table,
    salesforce_tables,
    truth_tables,
)

DEFAULT_SEED = 20261014

# Planted scenarios whose effect comes from the overall design rather than one config entry:
# (id, label, where in the config or code it comes from).
DESIGN_SCENARIOS = (
    (
        "S01",
        "Lead-form promos: cheap leads, low qualification",
        "campaigns with tactic lead_form; qualification.by_entry_point.meta_lead_form",
    ),
    (
        "S02",
        "Paid search visible in GA4 without a spend feed",
        "campaign search_paid_generic (platform google_ads, no budget)",
    ),
    (
        "S07",
        "Meta reports more leads than the CRM",
        "meta_account.view_through_rate; click-window double counting",
    ),
    (
        "S08",
        "Retargeting earns credit with zero causal effect",
        "retargeting clicks are placed after conversions are decided",
    ),
    (
        "S11",
        "Ottawa regional campaign is expensive per qualified lead",
        "campaign meta_prospecting_furnace_ottawa",
    ),
    ("S12", "Recent cohorts are immature", "lognormal sales cycle censored at data_as_of"),
    ("S13", "Small northern towns create small cells", "region northern_other"),
    (
        "S14",
        "Sarah and Claire leads qualify slightly less often",
        "qualification.by_entry_point web_chat_agent / meta_messaging_agent",
    ),
)


def generate(config_name_or_path: str | Path, seed: int, out_root: Path) -> Path:
    """Simulate one world and write it to <out_root>/<config name>-seed-<seed>/."""
    config = load_config(config_name_or_path)
    folder = out_root / f"{config.name}-seed-{seed}"
    if folder.exists():
        if not (folder / "manifest.json").exists():
            raise FileExistsError(f"{folder} exists and wasn't created by the generator")
        shutil.rmtree(folder)
    world = simulate(config, seed)
    write_world(world, folder)
    return folder


def write_world(world: World, folder: Path) -> dict[str, Any]:
    ctx = world.context
    assign_identifiers(world)
    tables = [
        meta_table(ctx, world),
        ga4_table(ctx, world),
        *salesforce_tables(ctx, world),
        clarity_table(ctx, world),
        annotation_table(ctx),
        mapping_table(ctx),
        *truth_tables(ctx, world),
    ]
    files: dict[str, dict[str, Any]] = {}
    for table in tables:
        files[table.path] = _write_csv(folder, table)
    scenarios = folder / "truth" / "scenarios.json"
    scenarios.write_text(_json(_scenarios(world.context.config)), encoding="utf-8", newline="\n")
    files["truth/scenarios.json"] = {"rows": None, "sha256": _sha256(scenarios)}

    manifest = {
        "generator": "synthetic",
        "generator_version": __version__,
        "synthetic": True,
        "notice": "Fictional data. Not facts about LG Home Comfort or any real business.",
        "organization": {
            "slug": ctx.config.organization.slug,
            "name": ctx.config.organization.name,
        },
        "config": world.context.config.name,
        "config_sha256": config_digest(world.context.config),
        "seed": world.context.seed,
        "window": {
            "start": ctx.calendar.start.isoformat(),
            "end": ctx.calendar.end.isoformat(),
            "data_as_of": ctx.calendar.data_as_of.isoformat(),
        },
        "reporting_tz": ctx.config.organization.reporting_tz,
        "meta_account_timezone": ctx.config.meta_account.timezone,
        "currency": ctx.config.organization.currency,
        "files": dict(sorted(files.items())),
        "realized": realized_stats(world),
    }
    (folder / "manifest.json").write_text(_json(manifest), encoding="utf-8", newline="\n")
    return manifest


def realized_stats(world: World) -> dict[str, Any]:
    """What the generator actually produced, for checking against the config and the docs."""
    ctx = world.context
    calendar = ctx.calendar
    as_of_end = calendar.as_of_end_utc
    leads = world.leads
    real = [lead for lead in leads if lead.duplicate_of is None and not lead.is_test]
    acquisition = [lead for lead in real if lead.true_class == "acquisition"]
    sessions = [s for s in world.all_sessions() if calendar.in_export_window(s.start)]
    web_leads = [lead for lead in real if lead.entry_point in WEB_ENTRY_POINTS]

    def share(part: int, whole: int) -> float:
        return round(part / whole, 4) if whole else 0.0

    def distribution(values: list[str]) -> dict[str, float]:
        counts = Counter(values)
        return {key: share(count, len(values)) for key, count in counts.most_common()}

    def won(group: list) -> int:
        return sum(
            1
            for lead in group
            if lead.opportunity is not None
            and lead.opportunity.won
            and lead.opportunity.close_at < as_of_end
        )

    click_window = timedelta(days=ctx.config.meta_account.click_window_days)

    def has_meta_evidence(lead) -> bool:
        if lead.entry_point in ("meta_lead_form", "meta_messaging_agent"):
            return True
        return any(
            s.channel == "meta" and lead.created_at - click_window <= s.start <= lead.created_at
            for s in lead.household.sessions
        )

    meta_rows = [row for row in world.meta_days if calendar.start <= row.day <= calendar.data_as_of]
    crm_with_meta = sum(1 for lead in real if has_meta_evidence(lead))
    reported = sum(row.reported_leads for row in meta_rows)
    months = ((calendar.data_as_of - calendar.start).days + 1) / (365.25 / 12)

    return {
        "sessions_in_window": len(sessions),
        "ga4_sessions_recorded": sum(1 for s in sessions if s.recorded),
        "leads_total": len(leads),
        "leads_by_true_class": distribution([lead.true_class for lead in leads]),
        "duplicate_leads": sum(1 for lead in leads if lead.duplicate_of is not None),
        "resubmissions": sum(1 for lead in leads if lead.resubmission),
        "test_leads": sum(1 for lead in leads if lead.is_test),
        "acquisition_leads": len(acquisition),
        "acquisition_entry_points": distribution([lead.entry_point for lead in acquisition]),
        "acquisition_won_sales": won(acquisition),
        "service_demand_won_sales": won(
            [lead for lead in real if lead.true_class == "service_demand"]
        ),
        "web_leads_with_consent": share(
            sum(lead.household.consent for lead in web_leads), len(web_leads)
        ),
        "meta_spend_per_month": round(sum(row.spend for row in meta_rows) / months, 2),
        "meta_reported_leads": reported,
        "crm_leads_with_meta_evidence": crm_with_meta,
        "meta_reported_to_crm_ratio": share(reported, crm_with_meta),
        "retargeted_households": sum(1 for h in world.households if h.retargeted),
    }


def _scenarios(config: WorldConfig) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    sections = (
        ("demand_events", config.demand_events),
        ("campaign_modifiers", config.campaign_modifiers),
        ("page_changes", config.page_changes),
        ("capture_outages", config.capture_outages),
    )
    for section, items in sections:
        scenarios += [{"config_section": section, **item.model_dump(mode="json")} for item in items]
    scenarios += [
        {"id": "S09", "label": "Campaign missing from the mapping sheet", "campaign": c.key}
        for c in config.campaigns
        if not c.mapped
    ]
    scenarios += [
        {"id": key, "label": label, "where": where} for key, label, where in DESIGN_SCENARIOS
    ]
    return sorted(scenarios, key=lambda scenario: scenario["id"])


def _write_csv(folder: Path, table: Table) -> dict[str, Any]:
    path = folder / table.path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(table.columns)
        writer.writerows(table.rows)
    return {"rows": len(table.rows), "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"
