"""Builds the priced series from the tariff config and (for dynamic tariffs) a price entity."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import tariffs as T
from .const import (
    CONF_BILLING,
    CONF_CAPACITY,
    CONF_COGEN,
    CONF_ENERGY_MODE,
    CONF_EXCISE,
    CONF_FIXED_NETWORK,
    CONF_GROUP,
    CONF_MARGIN,
    CONF_OZE,
    CONF_PHASES,
    CONF_PRICE_ENTITY,
    CONF_QUALITY,
    CONF_SOURCE_VAT,
    CONF_TRADE_FEE,
    CONF_VAT,
    DIST_PREFIX,
    DOMAIN,
    ENERGY_PREFIX,
)
from .pricing import (
    MODE_DYNAMIC,
    TZ,
    PricedSlot,
    TariffConfig,
    build_series,
    monthly_fixed,
)
from .source import parse_points

_LOGGER = logging.getLogger(__name__)


def config_from_entry(entry: ConfigEntry) -> TariffConfig:
    group = entry.data[CONF_GROUP]
    mode = entry.data[CONF_ENERGY_MODE]
    o = entry.options
    base = TariffConfig.defaults(group, mode)
    g = T.GROUPS[group]
    fn = o.get(CONF_FIXED_NETWORK)
    return TariffConfig(
        group=group,
        energy_mode=mode,
        dist_rates={k: float(o.get(DIST_PREFIX + k, v)) for k, v in g.dist_rates.items()},
        energy_rates={k: float(o.get(ENERGY_PREFIX + k, v)) for k, v in g.energy_rates.items()},
        margin=float(o.get(CONF_MARGIN, base.margin)),
        excise=float(o.get(CONF_EXCISE, base.excise)),
        quality_fee=float(o.get(CONF_QUALITY, base.quality_fee)),
        oze_fee=float(o.get(CONF_OZE, base.oze_fee)),
        cogeneration_fee=float(o.get(CONF_COGEN, base.cogeneration_fee)),
        vat=float(o.get(CONF_VAT, base.vat)),
        phases=int(o.get(CONF_PHASES, base.phases)),
        billing_months=int(o.get(CONF_BILLING, base.billing_months)),
        capacity_bracket=o.get(CONF_CAPACITY, base.capacity_bracket),
        fixed_network=float(fn) if fn not in (None, "") else None,
        trade_fee=float(o.get(CONF_TRADE_FEE, base.trade_fee)),
    )


@dataclass
class TariffData:
    series: list[PricedSlot]
    fixed: dict[str, float]
    source_error: str | None = None
    built_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class TariffCoordinator(DataUpdateCoordinator[TariffData]):
    """No polling: refreshed on price-entity changes and on every quarter-hour tick."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=None)
        self.cfg = config_from_entry(entry)
        self.price_entity: str | None = entry.options.get(CONF_PRICE_ENTITY)
        self._source_vat = bool(entry.options.get(CONF_SOURCE_VAT, False))
        self._last_error: str | None = None

    def _read_source(self):
        if self.cfg.energy_mode != MODE_DYNAMIC:
            return None, None
        if not self.price_entity:
            return [], "no price entity configured"
        st = self.hass.states.get(self.price_entity)
        if st is None:
            return [], f"{self.price_entity} not found"
        if st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) and not st.attributes:
            return [], f"{self.price_entity} is {st.state}"
        try:
            pts = parse_points(
                dict(st.attributes), st.attributes.get(ATTR_UNIT_OF_MEASUREMENT),
                includes_vat=self._source_vat, vat=self.cfg.vat,
            )
        except ValueError as err:
            return [], f"{self.price_entity}: {err}"
        if not pts:
            return [], f"{self.price_entity} has no price list in its attributes"
        return pts, None

    async def _async_update_data(self) -> TariffData:
        source, err = self._read_source()
        today = dt_util.utcnow().astimezone(TZ).date()
        series = build_series(self.cfg, source, today)
        if err != self._last_error:
            if err:
                _LOGGER.warning("Tariff %s: %s", self.config_entry.title, err)
            elif self._last_error:
                _LOGGER.info("Tariff %s: price source OK again", self.config_entry.title)
            self._last_error = err
        return TariffData(
            series=series,
            fixed=monthly_fixed(self.cfg),
            source_error=err,
            built_at=dt_util.utcnow(),
        )
