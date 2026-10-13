"""Reference price seeded from the recorder (runs with a real recorder)."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done as wait,
)

from custom_components.pl_energy_tariff.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    yield


async def _done(hass):
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_reference_uses_recorded_history(hass: HomeAssistant, freezer):
    """History of the total-price sensor (incl. history migrated from old helpers) seeds the reference."""
    await hass.config.async_set_time_zone("Europe/Warsaw")
    entry = MockConfigEntry(domain=DOMAIN, title="Taryfa G11 stała",
                            data={"group": "G11", "energy_mode": "fixed"}, options={})
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create("sensor", DOMAIN, f"{entry.entry_id}_total_price",
                                           suggested_object_id="taryfa_g11_stala_total_price", config_entry=entry)
    freezer.move_to("2026-10-01 00:00:00+02:00")
    hass.states.async_set("sensor.taryfa_g11_stala_total_price", "2.0")
    await wait(hass)
    hass.states.async_remove("sensor.taryfa_g11_stala_total_price")   # the integration owns it now
    freezer.move_to("2026-10-13 12:30:00+02:00")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await _done(hass)
    ref = hass.states.get("sensor.taryfa_g11_stala_total_price")
    r = hass.states.get("sensor.taryfa_g11_stala_reference_price")
    assert r.attributes["history_samples"] > 12
    # history at 2.0 zł pulls the reference above the flat G11 price (~0.97 zł)
    assert float(ref.state) == pytest.approx(0.9739, abs=1e-3)
    assert r.attributes["history_inertia"] > 1.9      # 12 days at 2.0 zł, τ ≈ 6 days
    assert float(r.state) > float(ref.state) + 0.5
