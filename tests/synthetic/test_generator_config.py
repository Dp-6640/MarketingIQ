import tomllib

import pytest
from pydantic import ValidationError

from synthetic.config import CONFIG_DIR, WorldConfig, config_digest, load_config


def _default_raw() -> dict:
    return tomllib.loads((CONFIG_DIR / "default.toml").read_text(encoding="utf-8"))


def test_default_and_tiny_configs_are_valid():
    default = load_config("default")
    tiny = load_config("tiny")

    assert default.name == "default"
    assert tiny.name == "tiny"
    assert len(default.campaigns) == 13
    assert [region.key for region in tiny.regions] == ["gta"]


def test_tiny_inherits_unset_values_from_default():
    default = load_config("default")
    tiny = load_config("tiny")

    assert tiny.window.start.isoformat() == "2026-01-01"
    assert tiny.meta_account.timezone == "America/Los_Angeles"
    # Not set in tiny.toml, so inherited:
    assert tiny.needs == default.needs
    assert tiny.recording == default.recording
    assert tiny.traffic.weekday == default.traffic.weekday
    assert tiny.campaign_modifiers == []


def test_override_replaces_nested_distributions_but_merges_sections(tmp_path):
    override = tmp_path / "override.toml"
    override.write_text(
        f'extends = "{(CONFIG_DIR / "default.toml").as_posix()}"\n'
        'name = "override"\n'
        "[traffic]\n"
        "no_need_sessions_per_day = 1.0\n"
        "[needs.research]\n"
        "entry_points = { web_quote_form = 1.0 }\n",
        encoding="utf-8",
    )

    config = load_config(override)

    # Merged with the base distribution, the shares would sum to 2 and fail validation.
    assert config.needs["research"].entry_points == {"web_quote_form": 1.0}
    assert config.needs["research"].share == load_config("default").needs["research"].share
    assert config.traffic.no_need_sessions_per_day == 1.0
    assert config.traffic.device_mix == load_config("default").traffic.device_mix


def test_digest_is_stable_and_content_sensitive():
    assert config_digest(load_config("default")) == config_digest(load_config("default"))
    assert config_digest(load_config("default")) != config_digest(load_config("tiny"))


def test_shares_must_sum_to_one():
    raw = _default_raw()
    raw["traffic"]["device_mix"]["mobile"] = 0.70

    with pytest.raises(ValidationError, match="shares sum to"):
        WorldConfig.model_validate(raw)


def test_unknown_keys_are_rejected():
    raw = _default_raw()
    raw["traffic"]["demand_househods_per_day"] = 10.0  # typo

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        WorldConfig.model_validate(raw)


def test_unknown_category_in_distribution_is_rejected():
    raw = _default_raw()
    raw["needs"]["research"]["entry_points"] = {"web_quote_form": 0.6, "carrier_pigeon": 0.4}

    with pytest.raises(ValidationError, match="unknown keys"):
        WorldConfig.model_validate(raw)


def test_campaign_modifier_must_reference_a_meta_campaign():
    raw = _default_raw()
    raw["campaign_modifiers"][0]["campaign"] = "search_paid_generic"

    with pytest.raises(ValidationError, match="unknown Meta campaign"):
        WorldConfig.model_validate(raw)


def test_meta_campaign_needs_delivery_parameters():
    raw = _default_raw()
    raw["campaigns"][0]["audience_quality"] = 0.0

    with pytest.raises(ValidationError, match="prospecting campaigns need"):
        WorldConfig.model_validate(raw)


def test_only_meta_campaigns_have_spend():
    raw = _default_raw()
    search = next(c for c in raw["campaigns"] if c["key"] == "search_paid_generic")
    search["daily_budget"] = 10.0

    with pytest.raises(ValidationError, match="only Meta campaigns have a spend feed"):
        WorldConfig.model_validate(raw)


def test_unmapped_campaign_is_the_summer_test():
    unmapped = [c.key for c in load_config("default").campaigns if not c.mapped]

    assert unmapped == ["meta_prospecting_summer_test"]
