"""Polish electricity tariffs (G groups) with total price per hour and price-window search."""

from __future__ import annotations

from datetime import datetime, timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SERVICE_FIND_WINDOW
from .coordinator import TariffCoordinator
from .pricing import TZ
from .windows import MODE_CHEAPEST, MODE_EXPENSIVE, PricePoint, find_window

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type TariffConfigEntry = ConfigEntry[TariffCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TariffConfigEntry) -> bool:
    coordinator = TariffCoordinator(hass, entry)
    await coordinator.async_load_history()
    await coordinator.async_refresh()
    entry.runtime_data = coordinator

    async def _refresh(*_args) -> None:
        await coordinator.async_refresh()

    @callback
    def _on_source(event: Event) -> None:
        hass.async_create_task(_refresh())

    if coordinator.price_entity:
        entry.async_on_unload(
            async_track_state_change_event(hass, [coordinator.price_entity], _on_source)
        )
    entry.async_on_unload(
        async_track_time_change(hass, _refresh, minute=[0, 15, 30, 45], second=0)
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TariffConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


PRICE_FIELDS = ("total", "energy", "distribution")

FIND_WINDOW_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Required("duration"): vol.All(vol.Coerce(float), vol.Range(min=0.25, max=48)),
        vol.Optional("mode", default=MODE_CHEAPEST): vol.In([MODE_CHEAPEST, MODE_EXPENSIVE]),
        vol.Optional("period", default="upcoming"): vol.In(["upcoming", "today", "tomorrow"]),
        vol.Optional("contiguous", default=True): cv.boolean,
        vol.Optional("price", default="total"): vol.In(PRICE_FIELDS),
        vol.Optional("start_after"): cv.datetime,
        vol.Optional("end_before"): cv.datetime,
    }
)


def _aware(d: datetime) -> datetime:
    return d.replace(tzinfo=TZ) if d.tzinfo is None else d.astimezone(TZ)


def _register_services(hass: HomeAssistant) -> None:
    async def find_window_service(call: ServiceCall) -> ServiceResponse:
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        wanted = call.data.get("config_entry_id")
        if wanted:
            entries = [e for e in entries if e.entry_id == wanted]
        if not entries:
            raise ServiceValidationError("No loaded tariff matches config_entry_id")
        if len(entries) > 1:
            raise ServiceValidationError(
                "Several tariffs are configured; pass config_entry_id to choose one"
            )
        coord: TariffCoordinator = entries[0].runtime_data
        series = coord.data.series
        now = dt_util.utcnow().astimezone(TZ)
        today = now.date()
        day0 = datetime.combine(today, datetime.min.time(), TZ)
        period = call.data["period"]
        if period == "today":
            lo, hi = day0, datetime.combine(today + timedelta(days=1), datetime.min.time(), TZ)
        elif period == "tomorrow":
            lo = datetime.combine(today + timedelta(days=1), datetime.min.time(), TZ)
            hi = datetime.combine(today + timedelta(days=2), datetime.min.time(), TZ)
        else:
            cur = next((s for s in series if s.start <= now < s.end), None)
            lo = cur.start if cur else now
            hi = series[-1].end if series else now
        if (sa := call.data.get("start_after")) is not None:
            lo = max(lo, _aware(sa))
        if (eb := call.data.get("end_before")) is not None:
            hi = min(hi, _aware(eb))

        field = call.data["price"]
        points = [
            PricePoint(s.start, s.end, getattr(s, field))
            for s in series
            if s.start >= lo and s.end <= hi
        ]
        w = find_window(points, timedelta(hours=call.data["duration"]),
                        call.data["mode"], call.data["contiguous"])
        if w is None:
            return {
                "found": False,
                "reason": "not enough price data in the requested range"
                if points else "no prices in the requested range",
                "available_from": points[0].start.isoformat() if points else None,
                "available_to": points[-1].end.isoformat() if points else None,
            }
        prices = [p.price for p in w.points]
        return {
            "found": True,
            "start": w.start.isoformat(),
            "end": w.end.isoformat(),
            "hours": round(sum((p.end - p.start).total_seconds() for p in w.points) / 3600, 2),
            "average": round(w.average, 5),
            "min": round(min(prices), 5),
            "max": round(max(prices), 5),
            "unit": "PLN/kWh",
            "price": field,
            "contiguous": w.contiguous,
            "ranges": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in w.ranges],
            "slots": [{"start": p.start.isoformat(), "price": p.price} for p in w.points],
        }

    if not hass.services.has_service(DOMAIN, SERVICE_FIND_WINDOW):
        hass.services.async_register(
            DOMAIN, SERVICE_FIND_WINDOW, find_window_service,
            schema=FIND_WINDOW_SCHEMA, supports_response=SupportsResponse.ONLY,
        )
