"""Binary sensors: current price in the cheap / expensive part of the coming window."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import TariffCoordinator
from .pricing import iso_local
from .sensor import TariffEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coord: TariffCoordinator = entry.runtime_data
    async_add_entities([
        LevelBinarySensor(coord, entry, "cheap_now", ("very_cheap", "cheap"), "mdi:cash-check"),
        LevelBinarySensor(coord, entry, "expensive_now", ("expensive", "very_expensive"), "mdi:cash-remove"),
    ])


class LevelBinarySensor(TariffEntity, BinarySensorEntity):
    def __init__(self, coord, entry, key: str, levels: tuple[str, ...], icon: str) -> None:
        super().__init__(coord, entry, key)
        self.entity_id = self.entity_id.replace("sensor.", "binary_sensor.", 1)
        self._levels = levels
        self._attr_icon = icon

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.indicators.level is not None

    @property
    def is_on(self) -> bool | None:
        lvl = self.coordinator.data.indicators.level
        return None if lvl is None else lvl in self._levels

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        w = self.coordinator.data.indicators.window
        if not w:
            return {}
        return {"cheap_max": w.cheap_max, "expensive_min": w.expensive_min,
                "window_end": iso_local(w.end)}
