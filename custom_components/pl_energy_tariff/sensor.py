"""Sensors: total price and its components, tariff zone, fixed charges per day."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from . import tariffs as T
from .const import DOMAIN
from .coordinator import TariffCoordinator
from .indicators import LEVELS
from .pricing import MODE_DYNAMIC, TZ, PricedSlot, daily_fixed, slot_at

UNIT = "PLN/kWh"  # kod waluty ISO 4217 (wymóg HA dla monetary i panelu Energia)
LIST_ATTRS = frozenset({"prices", "prices_today", "prices_tomorrow"})


def _migrate_fixed_cost_entity(hass: HomeAssistant, entry) -> None:
    """0.4.0: fixed_monthly_cost (PLN/month) became fixed_daily_cost (PLN/d)."""
    reg = er.async_get(hass)
    old_id = reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_fixed_monthly_cost")
    if old_id is None:
        return
    changes: dict[str, Any] = {"new_unique_id": f"{entry.entry_id}_fixed_daily_cost"}
    new_entity_id = old_id.replace("_fixed_monthly_cost", "_fixed_daily_cost")
    if new_entity_id != old_id and reg.async_get(new_entity_id) is None:
        changes["new_entity_id"] = new_entity_id
    reg.async_update_entity(old_id, **changes)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coord: TariffCoordinator = entry.runtime_data
    _migrate_fixed_cost_entity(hass, entry)
    async_add_entities([
        PriceSensor(coord, entry, "total_price", "total"),
        PriceSensor(coord, entry, "energy_price", "energy"),
        PriceSensor(coord, entry, "distribution_price", "distribution"),
        NextPriceSensor(coord, entry),
        ZoneSensor(coord, entry),
        FixedCostSensor(coord, entry),
        FixedCostTodaySensor(coord, entry),
        ReferencePriceSensor(coord, entry),
        PriceScoreSensor(coord, entry),
        WindowMedianSensor(coord, entry),
        PriceLevelSensor(coord, entry),
        ChargeTargetSensor(coord, entry),
    ])


class TariffEntity(CoordinatorEntity[TariffCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coord: TariffCoordinator, entry, key: str) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self.entity_id = f"sensor.{slugify(entry.title)}_{key}"
        cfg = coord.cfg
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=cfg.manufacturer,
            model=f"{cfg.group} · {'cena dynamiczna' if cfg.energy_mode == MODE_DYNAMIC else 'cena stała'}",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def series(self) -> list[PricedSlot]:
        return self.coordinator.data.series

    @staticmethod
    def now():
        return dt_util.utcnow().astimezone(TZ)

    def current(self) -> PricedSlot | None:
        return slot_at(self.series, self.now())


class PriceSensor(TariffEntity, SensorEntity):
    """Current price; attributes list today's and tomorrow's prices for charts and templates."""

    _attr_native_unit_of_measurement = UNIT
    _attr_suggested_display_precision = 4
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cash-clock"
    _unrecorded_attributes = LIST_ATTRS

    def __init__(self, coord, entry, key: str, field: str) -> None:
        super().__init__(coord, entry, key)
        self._field = field

    @property
    def native_value(self) -> float | None:
        s = self.current()
        return getattr(s, self._field) if s else None

    @property
    def available(self) -> bool:
        return super().available and self.current() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        today = self.now().date()
        tomorrow = today + timedelta(days=1)

        def series(day):
            return [
                {"time": s.start.isoformat(), "price": getattr(s, self._field)}
                for s in self.series if s.start.astimezone(TZ).date() == day
            ]

        pt, pn = series(today), series(tomorrow)
        attrs: dict[str, Any] = {
            "prices_today": pt, "prices_tomorrow": pn, "prices": pt + pn,
            "tomorrow_available": bool(pn),
        }
        s = self.current()
        if s and self._field == "total":
            attrs.update({
                "zone": s.zone,
                "energy": s.energy,
                "distribution": s.distribution,
                "exchange_netto": s.exchange,
            })
        if self.coordinator.data.source_error:
            attrs["source_error"] = self.coordinator.data.source_error
        return attrs


class NextPriceSensor(TariffEntity, SensorEntity):
    _attr_native_unit_of_measurement = UNIT
    _attr_suggested_display_precision = 4
    _attr_icon = "mdi:cash-fast"

    def __init__(self, coord, entry) -> None:
        super().__init__(coord, entry, "next_total_price")

    @property
    def native_value(self) -> float | None:
        s = self.current()
        n = slot_at(self.series, s.end) if s else None
        return n.total if n else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.current()
        n = slot_at(self.series, s.end) if s else None
        return {"start": n.start.isoformat(), "zone": n.zone} if n else {}


class ZoneSensor(TariffEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_icon = "mdi:clock-time-four-outline"

    def __init__(self, coord, entry) -> None:
        super().__init__(coord, entry, "zone")
        self._attr_options = list(coord.cfg.tariff.energy_zones)

    @property
    def native_value(self) -> str | None:
        local = self.now()
        return self.coordinator.cfg.classify(local)[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        local = self.now()
        zone, rate_key = self.coordinator.cfg.classify(local)
        return {"zone_name": T.ZONE_NAMES_PL.get(zone, zone), "rate_key": rate_key,
                "group": self.coordinator.cfg.group, "operator": self.coordinator.cfg.operator}


class FixedCostSensor(TariffEntity, SensorEntity):
    """Fixed charges expressed per day (monthly components / days in the current month)."""

    _attr_native_unit_of_measurement = "PLN/d"
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:calendar-today"

    def __init__(self, coord, entry) -> None:
        super().__init__(coord, entry, "fixed_daily_cost")

    def _fixed(self) -> dict[str, float]:
        # Computed for the current local day so the value follows month length
        # (28–31 days) without waiting for a coordinator refresh.
        return daily_fixed(self.coordinator.cfg, self.now().date())

    @property
    def native_value(self) -> float:
        return self._fixed()["total"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        f = self._fixed()
        f.pop("total", None)
        return f


class FixedCostTodaySensor(TariffEntity, SensorEntity):
    """Fixed charges accrued since local midnight, as a continuous cost meter.

    value = daily fixed charge · (seconds since midnight / seconds in the day), recomputed
    every minute and reset at midnight (state_class total + last_reset), so long-term
    statistics sum it like any other cost meter (hour, day, month).
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "PLN"
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:cash-clock"

    def __init__(self, coord, entry) -> None:
        super().__init__(coord, entry, "fixed_cost_today")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(self.hass, self._tick, second=0)
        )

    @callback
    def _tick(self, _now) -> None:
        self.async_write_ha_state()

    def _day(self):
        now = self.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=1, hours=3)).replace(hour=0)  # next local midnight (DST-safe)
        return now, start, end

    @property
    def last_reset(self):
        return self._day()[1]

    @property
    def native_value(self) -> float:
        now, start, end = self._day()
        # timestamps, not wall-clock subtraction: DST days have 23 h or 25 h
        frac = (now.timestamp() - start.timestamp()) / (end.timestamp() - start.timestamp())
        return round(daily_fixed(self.coordinator.cfg, now.date())["total"] * frac, 4)


def _iso(d):
    return d.isoformat() if d else None


class IndicatorEntity(TariffEntity, SensorEntity):
    @property
    def ind(self):
        return self.coordinator.data.indicators


class ReferencePriceSensor(IndicatorEntity):
    """Weekly inertia of past prices blended with the inertia of the forecast."""

    _attr_native_unit_of_measurement = UNIT
    _attr_suggested_display_precision = 4
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:scale-balance"

    def __init__(self, coord, entry) -> None:
        super().__init__(coord, entry, "reference_price")

    @property
    def native_value(self) -> float | None:
        r = self.ind.reference
        return round(r.price, 5) if r else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self.ind.reference
        if not r:
            return {}
        return {
            "forecast_inertia": round(r.forecast, 5) if r.forecast is not None else None,
            "history_inertia": round(r.history, 5) if r.history is not None else None,
            "forecast_hours": round(r.horizon_h, 2),
            "tau_forecast_h": round(r.tau_forecast_h, 2),
            "tau_history_h": round(r.tau_history_h, 2),
            "sigma": round(r.sigma, 5),
            "history_samples": self.ind.history_samples,
            "history_from": _iso(self.ind.history_from),
        }


class PriceScoreSensor(IndicatorEntity):
    """100 · (price − reference) / (σ · reference)."""

    _attr_native_unit_of_measurement = "%"
    _attr_suggested_display_precision = 0
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:sigma"

    def __init__(self, coord, entry) -> None:
        super().__init__(coord, entry, "price_score")

    @property
    def native_value(self) -> float | None:
        v = self.ind.score
        return round(v, 1) if v is not None else None


class WindowMedianSensor(IndicatorEntity):
    """Median of the next N hours with cheap / expensive thresholds."""

    _attr_native_unit_of_measurement = UNIT
    _attr_suggested_display_precision = 4
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-bell-curve"

    def __init__(self, coord, entry) -> None:
        super().__init__(coord, entry, "window_median")

    @property
    def native_value(self) -> float | None:
        w = self.ind.window
        return w.median if w else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        w = self.ind.window
        if not w:
            return {}
        return {
            "window_start": _iso(w.start), "window_end": _iso(w.end), "window_hours": w.hours,
            "very_cheap_max": w.very_cheap_max, "cheap_max": w.cheap_max,
            "expensive_min": w.expensive_min, "very_expensive_min": w.very_expensive_min,
        }


class PriceLevelSensor(IndicatorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(LEVELS)
    _attr_icon = "mdi:stairs"

    def __init__(self, coord, entry) -> None:
        super().__init__(coord, entry, "price_level")

    @property
    def native_value(self) -> str | None:
        return self.ind.level


class ChargeTargetSensor(IndicatorEntity):
    """Suggested battery charge limit for the current price."""

    _attr_native_unit_of_measurement = "%"
    _attr_suggested_display_precision = 0
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-charging-high"

    def __init__(self, coord, entry) -> None:
        super().__init__(coord, entry, "charge_target")

    @property
    def native_value(self) -> float | None:
        return self.ind.charge_target
