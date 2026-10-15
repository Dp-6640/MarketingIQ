"""Runs the simulation."""

from dataclasses import dataclass

from synthetic.config import WorldConfig
from synthetic.context import Context
from synthetic.entities import Household, MetaDay, Session
from synthetic.meta import meta_delivery, retargeting_overlay
from synthetic.traffic import demand_households, no_need_sessions


@dataclass
class World:
    context: Context
    households: list[Household]
    visitor_sessions: list[Session]  # visits from people with no need
    meta_days: list[MetaDay]

    def all_sessions(self) -> list[Session]:
        household_sessions = [s for h in self.households for s in h.sessions]
        return household_sessions + self.visitor_sessions


def simulate(config: WorldConfig, seed: int) -> World:
    ctx = Context(config, seed)
    households = demand_households(ctx)
    meta_days, meta_households, ad_visits = meta_delivery(ctx)
    households += meta_households
    visitors = no_need_sessions(ctx) + ad_visits
    visitors += retargeting_overlay(ctx, households, meta_days, visitors)
    return World(ctx, households, visitors, meta_days)
