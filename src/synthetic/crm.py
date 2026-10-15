"""CRM leads and what happens to them: qualification, consultations, opportunities.

Statuses are Salesforce-style picklist values invented for this synthetic world; the
application maps them through versioned stage mappings marked unverified (U-02).
"""

import math
from datetime import datetime, timedelta

import numpy as np

from synthetic.config import Lifecycle
from synthetic.context import Context
from synthetic.entities import Appointment, Household, Lead, Opportunity

# Stream-key kinds for leads that don't come straight from a household.
TEST_LEAD = 4
ORIGINAL, DUPLICATE, RESUBMISSION = 0, 1, 2
DUPLICATE_ENTRY_SWAPS = ("web_quote_form", "web_callback_form", "phone")


def true_class(household: Household, request: str) -> str:
    """The lead's real class, from what the household actually wanted."""
    if request == "spam":
        return "junk"
    if request in ("billing", "customer_service", "non_sales_form"):
        return "non_marketing"
    if request in ("repair_service", "maintenance"):
        return "service_demand"
    return "existing_customer_sales" if household.customer_type == "existing" else "acquisition"


def make_leads(ctx: Context, households: list[Household]) -> list[Lead]:
    """CRM leads created inside the export window, plus duplicates, resubmissions and tests."""
    calendar = ctx.calendar
    recording = ctx.config.recording
    leads = [
        Lead(
            key=(*household.key, ORIGINAL),
            household=household,
            created_at=household.lead_at,
            entry_point=household.entry_point,
            request=household.request,
            true_class=true_class(household, household.request),
        )
        for household in households
        if household.converts
        and household.lead_at is not None
        and household.entry_point is not None
        and calendar.in_export_window(household.lead_at)
    ]

    extra: list[Lead] = []
    for lead in leads:
        household = lead.household
        rng = ctx.streams.rng("lead_extra", *lead.key)
        if rng.random() < recording.duplicate_within_72h:
            created = lead.created_at + timedelta(seconds=int(rng.uniform(0.5, 60) * 3600))
            entry = lead.entry_point
            if entry in DUPLICATE_ENTRY_SWAPS and rng.random() < 0.5:
                others = [e for e in DUPLICATE_ENTRY_SWAPS if e != entry]
                entry = others[int(rng.integers(0, len(others)))]
            if calendar.in_export_window(created):
                extra.append(
                    Lead(
                        key=(*household.key, DUPLICATE),
                        household=household,
                        created_at=created,
                        entry_point=entry,
                        request=lead.request,
                        true_class="junk",
                        duplicate_of=lead,
                    )
                )
        if rng.random() < recording.resubmission_after_72h:
            created = lead.created_at + timedelta(days=float(rng.uniform(10, 90)))
            samplers = ctx.needs[household.need]
            entry = (samplers.entry if household.sessions else samplers.offline_entry).sample(rng)
            if calendar.in_export_window(created):
                extra.append(
                    Lead(
                        key=(*household.key, RESUBMISSION),
                        household=household,
                        created_at=created,
                        entry_point=entry,
                        request=lead.request,
                        true_class=lead.true_class,
                        resubmission=True,
                    )
                )
    leads += extra

    rng = ctx.streams.rng("test_leads")
    window_seconds = (calendar.as_of_end_utc - calendar.window_start_utc).total_seconds()
    for index in range(int(rng.binomial(len(leads), recording.test_leads))):
        leads.append(
            Lead(
                key=(TEST_LEAD, index),
                household=None,
                created_at=calendar.window_start_utc
                + timedelta(seconds=int(rng.uniform(0, window_seconds))),
                entry_point="web_quote_form" if rng.random() < 0.5 else "web_callback_form",
                request="spam",
                true_class="junk",
                is_test=True,
            )
        )
    return leads


def run_lifecycles(ctx: Context, leads: list[Lead]) -> None:
    for lead in leads:
        rng = ctx.streams.rng("lifecycle", *lead.key)
        if lead.is_test:
            lead.status = "Closed - No Action"
        elif lead.duplicate_of is not None:
            _close_duplicate(ctx, rng, lead)
        elif lead.true_class == "junk":
            lead.status = "Spam"
        elif lead.true_class == "non_marketing":
            lead.status = _status_after(
                ctx, lead.created_at + timedelta(days=1), "Closed - No Action"
            )
        elif lead.true_class == "service_demand":
            _service_lifecycle(ctx, rng, lead)
        else:
            _sales_lifecycle(ctx, rng, lead)


def _status_after(ctx: Context, moment: datetime, status: str) -> str:
    """`status` if it was reached by data_as_of, otherwise the lead is still being worked."""
    return status if moment < ctx.calendar.as_of_end_utc else "Working"


def _close_duplicate(ctx: Context, rng: np.random.Generator, lead: Lead) -> None:
    # Sales teams usually close duplicates; some stay open untouched.
    if rng.random() < 0.7:
        lead.status = _status_after(ctx, lead.created_at + timedelta(days=2), "Closed - No Action")
    else:
        lead.status = "New"


def _sales_lifecycle(ctx: Context, rng: np.random.Generator, lead: Lead) -> None:
    """New-customer (and existing-customer) sales leads: qualify, consult, quote, close."""
    config = ctx.config
    household = lead.household
    service = household.service_line or "furnace"
    lifecycle = config.lifecycle[service]
    common = config.lifecycle_common
    qualification = config.qualification
    calendar = ctx.calendar

    low, high = qualification.intent_factor_range
    intent_factor = min(max(household.intent / qualification.intent_reference, low), high)
    probability = (
        lifecycle.qualify
        * intent_factor
        * qualification.by_entry_point.get(lead.entry_point, 1.0)
        * qualification.by_origin_channel.get(household.origin_channel, 1.0)
    )
    qualified = rng.random() < min(probability, 0.97)
    lead.decided_at = lead.created_at + timedelta(
        days=float(rng.uniform(*qualification.decision_days))
    )
    if lead.decided_at >= calendar.as_of_end_utc:
        lead.status = (
            "New" if lead.created_at >= calendar.as_of_end_utc - timedelta(days=1) else "Working"
        )
        return
    if not qualified:
        lead.status = "Unqualified"
        return
    lead.qualified_at = lead.decided_at

    opportunity_at = None
    if lifecycle.consultation:
        if lead.entry_point == "booking":
            booked, booked_at = True, lead.created_at
        else:
            booked = rng.random() < lifecycle.book
            booked_at = lead.qualified_at + timedelta(days=float(rng.uniform(0, 3)))
        if booked:
            scheduled = booked_at + timedelta(days=float(rng.uniform(*common.booking_lead_days)))
            completed = rng.random() < lifecycle.complete
            if completed:
                outcome = "completed"
            elif rng.random() < common.no_show_share_of_incomplete:
                outcome = "no_show"
            else:
                outcome = "cancelled"
            lead.appointment = Appointment("in_home_consultation", booked_at, scheduled, outcome)
            if completed and rng.random() < lifecycle.opportunity:
                opportunity_at = scheduled + timedelta(days=float(rng.uniform(0, 2)))
    elif rng.random() < lifecycle.opportunity:
        opportunity_at = lead.qualified_at + timedelta(days=float(rng.uniform(0, 1)))

    if opportunity_at is not None:
        lead.opportunity = _opportunity(
            ctx,
            rng,
            lead,
            opportunity_at,
            service,
            lifecycle.win,
            lifecycle.close_median_days,
            lifecycle,
        )
    converted = (
        lead.opportunity is not None and lead.opportunity.created_at < calendar.as_of_end_utc
    )
    lead.status = "Converted" if converted else "Qualified"


def _service_lifecycle(ctx: Context, rng: np.random.Generator, lead: Lead) -> None:
    """Repairs and maintenance: a service visit; an old system may need a replacement quote."""
    common = ctx.config.lifecycle_common
    household = lead.household
    calendar = ctx.calendar
    if rng.random() < common.service_visit_book:
        booked_at = lead.created_at + timedelta(seconds=int(rng.uniform(300, 4 * 3600)))
        scheduled = lead.created_at + timedelta(days=float(rng.uniform(0.2, 3)))
        completed = rng.random() < common.service_visit_complete
        outcome = "completed" if completed else "cancelled"
        lead.appointment = Appointment("service_visit", booked_at, scheduled, outcome)
        replacement = common.repair_to_replacement
        if (
            completed
            and lead.request == "repair_service"
            and household.service_line is not None
            and household.system_age >= replacement.min_system_age
            and rng.random() < replacement.rate
        ):
            lifecycle = ctx.config.lifecycle[household.service_line]
            opportunity_at = scheduled + timedelta(days=float(rng.uniform(0, 1)))
            lead.opportunity = _opportunity(
                ctx,
                rng,
                lead,
                opportunity_at,
                household.service_line,
                replacement.win,
                replacement.close_median_days,
                lifecycle,
            )
    if lead.opportunity is not None and lead.opportunity.created_at < calendar.as_of_end_utc:
        lead.status = "Converted"
    elif lead.appointment is not None and lead.appointment.booked_at < calendar.as_of_end_utc:
        lead.status = "Service Scheduled"
    else:
        lead.status = "Working"


def _opportunity(
    ctx: Context,
    rng: np.random.Generator,
    lead: Lead,
    created_at: datetime,
    service: str,
    win: float,
    close_median_days: float,
    lifecycle: Lifecycle,
) -> Opportunity:
    common = ctx.config.lifecycle_common
    close_days = float(rng.lognormal(math.log(close_median_days), common.close_sigma))
    close_at = max(lead.created_at + timedelta(days=close_days), created_at + timedelta(days=1))
    won = bool(rng.random() < win)
    price = lifecycle.amount_median * float(rng.lognormal(0.0, common.amount_sigma))
    basis = ctx.pick_amount_basis.sample(rng)
    if basis == "financed_total":
        amount = price * common.financed_markup
    elif basis == "lease_contract":
        amount = price / common.monthly_divisor * common.lease_months
    elif basis == "monthly":
        amount = price / common.monthly_divisor
    else:
        amount = price
    return Opportunity(created_at, close_at, won, round(amount, 2), basis, service)
