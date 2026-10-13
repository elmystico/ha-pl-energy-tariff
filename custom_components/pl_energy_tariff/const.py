"""Constants for PL energy tariff."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "pl_energy_tariff"
NAME: Final = "Taryfy energii PL"

CONF_GROUP: Final = "group"
CONF_ENERGY_MODE: Final = "energy_mode"
CONF_PRICE_ENTITY: Final = "price_entity"
CONF_SOURCE_VAT: Final = "source_includes_vat"
CONF_MARGIN: Final = "margin"
CONF_EXCISE: Final = "excise"
CONF_QUALITY: Final = "quality_fee"
CONF_OZE: Final = "oze_fee"
CONF_COGEN: Final = "cogeneration_fee"
CONF_VAT: Final = "vat"
CONF_PHASES: Final = "phases"
CONF_BILLING: Final = "billing_months"
CONF_CAPACITY: Final = "capacity_bracket"
CONF_FIXED_NETWORK: Final = "fixed_network"
CONF_TRADE_FEE: Final = "trade_fee"
CONF_WINDOW_HOURS: Final = "window_hours"
CONF_CHEAP_FRACTION: Final = "cheap_fraction"
CONF_EXTREME_FRACTION: Final = "extreme_fraction"
CONF_REFERENCE_DAYS: Final = "reference_days"
CONF_CHARGE_VERY_CHEAP: Final = "charge_very_cheap"
CONF_CHARGE_CHEAP: Final = "charge_cheap"
CONF_CHARGE_AVERAGE: Final = "charge_average"
CONF_CHARGE_EXPENSIVE: Final = "charge_expensive"

INDICATOR_DEFAULTS: Final = {
    CONF_WINDOW_HOURS: 16.0,
    CONF_CHEAP_FRACTION: 0.25,
    CONF_EXTREME_FRACTION: 0.1667,
    CONF_REFERENCE_DAYS: 7.0,
    CONF_CHARGE_VERY_CHEAP: 100.0,
    CONF_CHARGE_CHEAP: 81.0,
    CONF_CHARGE_AVERAGE: 66.0,
    CONF_CHARGE_EXPENSIVE: 20.0,
}
HISTORY_LOOKBACK_DAYS: Final = 28

DIST_PREFIX: Final = "dist_"
ENERGY_PREFIX: Final = "energy_"

DEFAULT_PRICE_ENTITY: Final = "sensor.tge_rdn_fixing_1"

SERVICE_FIND_WINDOW: Final = "find_window"
SIGNAL_UPDATE: Final = f"{DOMAIN}_update"
