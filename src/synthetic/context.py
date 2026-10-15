"""Shared, precomputed state for one generation run."""

from zoneinfo import ZoneInfo

from synthetic.config import SERVICE_LINES, Need, WorldConfig
from synthetic.rng import Categorical, Streams
from synthetic.timeline import Calendar


class NeedSamplers:
    __slots__ = ("entry", "first_touch", "offline_entry", "requests")

    def __init__(self, need: Need) -> None:
        self.first_touch = Categorical(need.first_touch)
        self.entry = Categorical(need.entry_points)
        self.offline_entry = Categorical(need.offline_entry_points)
        self.requests = Categorical(need.requests)


class Context:
    def __init__(self, config: WorldConfig, seed: int) -> None:
        self.config = config
        self.seed = seed
        self.streams = Streams(seed)
        self.calendar = Calendar(config)
        self.meta_tz = ZoneInfo(config.meta_account.timezone)
        self.campaigns = {campaign.key: campaign for campaign in config.campaigns}

        traffic = config.traffic
        self.pick_region = Categorical({region.key: region.share for region in config.regions})
        self.pick_city = {
            region.key: Categorical({city.name: city.weight for city in region.cities})
            for region in config.regions
        }
        self.city_slug = {city.name: city.slug for r in config.regions for city in r.cities}
        slugs = [city.slug for region in config.regions for city in region.cities if city.slug]
        self.pick_location_slug = Categorical.uniform(slugs) if slugs else None
        self.pick_device = Categorical(traffic.device_mix)
        self.pick_later_touch = Categorical(traffic.later_touch_channels)
        self.pick_no_need_channel = Categorical(traffic.no_need_channels)
        self.pick_meta_prospect_need = Categorical(traffic.meta_prospect_needs)
        self.pick_meta_native_need = Categorical(traffic.meta_native_needs)
        self.pick_landing = {name: Categorical(mix) for name, mix in config.landing.items()}
        self.pick_source = {
            "organic_search": Categorical(config.sources.organic_search),
            "referral": Categorical(config.sources.referral),
            "organic_social": Categorical(config.sources.organic_social),
            "meta": Categorical(config.sources.meta),
        }
        self.pick_service = {name: Categorical(mix) for name, mix in config.service_mixes.items()}
        self.pick_any_service = Categorical.uniform(SERVICE_LINES)
        self.pick_campaign_service = {
            c.key: Categorical(c.service_lines) for c in config.campaigns if c.service_lines
        }
        self.needs = {name: NeedSamplers(need) for name, need in config.needs.items()}
        self.pick_amount_basis = Categorical(config.lifecycle_common.amount_basis)
