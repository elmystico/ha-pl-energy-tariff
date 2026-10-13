"""Sensors: total price and its components, tariff zone, fixed monthly cost."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from . import tariffs as T
from .const import DOMAIN
from .coordinator import TariffCoordinator
from .pricing import MODE_DYNAMIC, TZ, PricedSlot, slot_at

UNIT = "zł/kWh"
LIST_ATTRS = frozenset({"prices", "prices_today", "prices_tomorrow"})


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coord: TariffCoordinator = entry.runtime_data
    async_add_entities([
        PriceSensor(coord, entry, "total_price", "total"),
        PriceSensor(coord, entry, "energy_price", "energy"),
        PriceSensor(coord, entry, "distribution_price", "distribution"),
        NextPriceSensor(coord, entry),
        ZoneSensor(coord, entry),
        FixedCostSensor(coord, entry),
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
            manufacturer="TAURON Dystrybucja / TAURON Sprzedaż",
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
        self._attr_options = list(T.GROUPS[coord.cfg.group].energy_zones)

    @property
    def native_value(self) -> str | None:
        local = self.now()
        return self.coordinator.cfg.tariff.classify(local)[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        local = self.now()
        zone, rate_key = self.coordinator.cfg.tariff.classify(local)
        return {"zone_name": T.ZONE_NAMES_PL.get(zone, zone), "rate_key": rate_key,
                "group": self.coordinator.cfg.group}


class FixedCostSensor(TariffEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "zł"
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:calendar-month"

    def __init__(self, coord, entry) -> None:
        super().__init__(coord, entry, "fixed_monthly_cost")

    @property
    def native_value(self) -> float:
        return self.coordinator.data.fixed["total"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        f = dict(self.coordinator.data.fixed)
        f.pop("total", None)
        return f
