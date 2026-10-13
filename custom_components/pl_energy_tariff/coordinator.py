"""Builds the priced series from the tariff config and (for dynamic tariffs) a price entity."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import tariffs as T
from .const import (
    CONF_BILLING,
    CONF_CAPACITY,
    CONF_CHARGE_AVERAGE,
    CONF_CHARGE_CHEAP,
    CONF_CHARGE_EXPENSIVE,
    CONF_CHARGE_VERY_CHEAP,
    CONF_CHEAP_FRACTION,
    CONF_COGEN,
    CONF_ENERGY_MODE,
    CONF_EXCISE,
    CONF_EXTREME_FRACTION,
    CONF_FIXED_NETWORK,
    CONF_GROUP,
    CONF_MARGIN,
    CONF_OZE,
    CONF_PHASES,
    CONF_PRICE_ENTITY,
    CONF_QUALITY,
    CONF_REFERENCE_DAYS,
    CONF_SOURCE_VAT,
    CONF_TRADE_FEE,
    CONF_VAT,
    CONF_WINDOW_HOURS,
    DIST_PREFIX,
    DOMAIN,
    ENERGY_PREFIX,
    HISTORY_LOOKBACK_DAYS,
    INDICATOR_DEFAULTS,
)
from .indicators import (
    ChargeLevels,
    Reference,
    Slot,
    WindowStats,
    charge_target,
    price_level,
    price_score,
    reference_price,
    window_stats,
)
from .pricing import (
    MODE_DYNAMIC,
    TZ,
    PricedSlot,
    TariffConfig,
    build_series,
    monthly_fixed,
    slot_at,
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


@dataclass(frozen=True)
class IndicatorConfig:
    window_hours: float
    cheap_fraction: float
    extreme_fraction: float
    reference_days: float
    charge: ChargeLevels


def indicator_config(options: dict[str, Any]) -> IndicatorConfig:
    o = {**INDICATOR_DEFAULTS, **{k: v for k, v in options.items() if k in INDICATOR_DEFAULTS}}
    return IndicatorConfig(
        window_hours=float(o[CONF_WINDOW_HOURS]),
        cheap_fraction=float(o[CONF_CHEAP_FRACTION]),
        extreme_fraction=float(o[CONF_EXTREME_FRACTION]),
        reference_days=float(o[CONF_REFERENCE_DAYS]),
        charge=ChargeLevels(
            very_cheap=float(o[CONF_CHARGE_VERY_CHEAP]),
            cheap=float(o[CONF_CHARGE_CHEAP]),
            average=float(o[CONF_CHARGE_AVERAGE]),
            expensive=float(o[CONF_CHARGE_EXPENSIVE]),
        ),
    )


@dataclass
class Indicators:
    reference: Reference | None = None
    window: WindowStats | None = None
    score: float | None = None
    level: str | None = None
    charge_target: float | None = None
    history_samples: int = 0
    history_from: datetime | None = None


@dataclass
class TariffData:
    series: list[PricedSlot]
    fixed: dict[str, float]
    source_error: str | None = None
    built_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    indicators: Indicators = field(default_factory=Indicators)


class TariffCoordinator(DataUpdateCoordinator[TariffData]):
    """No polling: refreshed on price-entity changes and on every quarter-hour tick."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=None)
        self.cfg = config_from_entry(entry)
        self.price_entity: str | None = entry.options.get(CONF_PRICE_ENTITY)
        self._source_vat = bool(entry.options.get(CONF_SOURCE_VAT, False))
        self._last_error: str | None = None
        self.ind_cfg = indicator_config(dict(entry.options))
        # past total prices: recorder history (loaded once) + slots seen while running
        self._history: dict[datetime, float] = {}
        self._past: dict[datetime, float] = {}

    async def async_load_history(self) -> None:
        """Seed the reference price with the recorded history of our total-price sensor."""
        if "recorder" not in self.hass.config.components:
            return
        entity_id = er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, f"{self.config_entry.entry_id}_total_price"
        )
        if not entity_id:
            return
        from homeassistant.components.recorder import get_instance, history

        end = dt_util.utcnow()
        start = end - timedelta(days=HISTORY_LOOKBACK_DAYS)
        try:
            states = await get_instance(self.hass).async_add_executor_job(
                lambda: history.state_changes_during_period(
                    self.hass, start, end, entity_id, no_attributes=True, include_start_time_state=True
                )
            )
        except Exception as err:  # noqa: BLE001 – history is optional
            _LOGGER.warning("Tariff %s: cannot read history: %s", self.config_entry.title, err)
            return
        hist: dict[datetime, float] = {}
        for st in states.get(entity_id, []):
            try:
                hist[st.last_changed.astimezone(TZ)] = float(st.state)
            except (TypeError, ValueError):
                continue
        self._history = hist
        _LOGGER.debug("Tariff %s: loaded %d history samples", self.config_entry.title, len(hist))

    def _samples(self, series: list[PricedSlot], now: datetime) -> list[tuple[datetime, float]]:
        for s in series:
            if s.start <= now:
                self._past[s.start] = s.total
        cutoff = now - timedelta(days=HISTORY_LOOKBACK_DAYS)
        self._past = {t: p for t, p in self._past.items() if t >= cutoff}
        first_live = min(self._past) if self._past else now
        merged = {t: p for t, p in self._history.items() if cutoff <= t < first_live}
        merged.update(self._past)
        return sorted(merged.items())

    def _indicators(self, series: list[PricedSlot], now: datetime) -> Indicators:
        c = self.ind_cfg
        samples = self._samples(series, now)
        slots = [Slot(s.start, s.end, s.total) for s in series]
        ref = reference_price(samples, slots, now, week_h=c.reference_days * 24)
        win = window_stats(slots, now, c.window_hours, c.cheap_fraction, c.extreme_fraction)
        cur = slot_at(series, now)
        ind = Indicators(reference=ref, window=win, history_samples=len(samples),
                         history_from=samples[0][0] if samples else None)
        if cur is not None:
            if ref is not None:
                ind.score = price_score(cur.total, ref)
            if win is not None:
                ind.level = price_level(cur.total, win)
                if ref is not None:
                    ind.charge_target = charge_target(cur.total, win, ref.price, c.charge)
        return ind

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
        now = dt_util.utcnow().astimezone(TZ)
        return TariffData(
            series=series,
            fixed=monthly_fixed(self.cfg),
            source_error=err,
            built_at=dt_util.utcnow(),
            indicators=self._indicators(series, now),
        )
