"""End-to-end tests on a real Home Assistant core."""

from datetime import date

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.pl_energy_tariff.const import DOMAIN
from custom_components.pl_energy_tariff.pricing import hourly_slots
from tests.test_engine import F1

SRC = "sensor.tge_rdn_fixing_1"


def tge_attrs(days=(date(2026, 10, 13),)):
    out = {"unit_of_measurement": "zł/MWh", "prices_today": [], "prices_tomorrow": []}
    for i, d in enumerate(days):
        key = "prices_today" if i == 0 else "prices_tomorrow"
        out[key] = [{"time": s.isoformat(), "price": p} for (s, _), p in zip(hourly_slots(d, 1), F1)]
    out["prices"] = out["prices_today"] + out["prices_tomorrow"]
    return out


async def _done(hass):
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.fixture
async def g13_dynamic(hass: HomeAssistant, freezer):
    await hass.config.async_set_time_zone("Europe/Warsaw")
    freezer.move_to("2026-10-13 12:30:00+02:00")
    hass.states.async_set(SRC, "536.09", tge_attrs())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"operator": "tauron", "energy_mode": "dynamic"})
    assert result["step_id"] == "group"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"group": "g13"})
    assert result["step_id"] == "energy_dynamic"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "price_entity": SRC, "source_includes_vat": False, "margin": 0.0892, "excise": 0.0})
    assert result["step_id"] == "distribution"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "dist_morning_peak": 0.2203, "dist_afternoon_peak": 0.3898, "dist_other": 0.0392,
        "quality_fee": 0.0331, "oze_fee": 0.0073, "cogeneration_fee": 0.0030, "vat": 0.23,
        "phases": "3", "billing_months": "1", "capacity_bracket": "1200_2800"})
    assert result["step_id"] == "zones"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "hours_morning_peak": "7-13", "hours_morning_peak_summer": "7-13",
        "hours_afternoon_peak": "16-21", "hours_afternoon_peak_summer": "19-22"})
    assert result["type"] == "create_entry"
    assert result["title"] == "Taryfa G13 dynamiczna"
    await _done(hass)
    return hass.config_entries.async_entries(DOMAIN)[0]


async def test_sensors_dynamic_g13(hass: HomeAssistant, g13_dynamic):
    st = hass.states.get("sensor.taryfa_g13_dynamiczna_total_price")
    assert st is not None
    assert float(st.state) == pytest.approx((0.53609 + 0.0892 + 0.2203 + 0.0331 + 0.0073 + 0.0030) * 1.23, abs=1e-5)
    assert st.attributes["zone"] == "morning_peak"
    assert len(st.attributes["prices_today"]) == 24
    assert st.attributes["tomorrow_available"] is False
    assert hass.states.get("sensor.taryfa_g13_dynamiczna_zone").state == "morning_peak"
    assert float(hass.states.get("sensor.taryfa_g13_dynamiczna_energy_price").state) == pytest.approx(0.76911, abs=1e-5)
    fixed = hass.states.get("sensor.taryfa_g13_dynamiczna_fixed_monthly_cost")
    assert float(fixed.state) == round((10.86 + 4.56 + 17.18) * 1.23, 2)   # 3-phase
    nxt = hass.states.get("sensor.taryfa_g13_dynamiczna_next_total_price")
    assert nxt.attributes["zone"] == "other"   # 13:00 leaves the morning peak


async def test_follows_clock_and_source(hass: HomeAssistant, g13_dynamic, freezer):
    freezer.move_to("2026-10-13 16:00:00+02:00")
    async_fire_time_changed(hass)
    await _done(hass)
    assert hass.states.get("sensor.taryfa_g13_dynamiczna_zone").state == "afternoon_peak"
    # tomorrow published -> 48 slots
    hass.states.async_set(SRC, "727.54", tge_attrs((date(2026, 10, 13), date(2026, 10, 14))))
    await _done(hass)
    st = hass.states.get("sensor.taryfa_g13_dynamiczna_total_price")
    assert st.attributes["tomorrow_available"] is True
    assert len(st.attributes["prices"]) == 48


async def test_find_window(hass: HomeAssistant, g13_dynamic):
    call = lambda **kw: hass.services.async_call(DOMAIN, "find_window", kw, blocking=True, return_response=True)  # noqa: E731
    r = await call(duration=3, period="today")
    assert r["found"] is True
    assert r["hours"] == 3
    assert r["unit"] == "PLN/kWh"
    start = dt_util.parse_datetime(r["start"])
    assert start.hour not in (7, 8, 9, 10, 11, 12, 16, 17, 18, 19, 20)   # outside G13 peaks
    r2 = await call(duration=2, period="today", mode="most_expensive")
    assert dt_util.parse_datetime(r2["start"]).hour == 18
    # exchange-only ranking finds the midday dip
    r3 = await call(duration=3, period="today", price="energy")
    assert dt_util.parse_datetime(r3["start"]).hour == 11
    # upcoming from 12:30 to end of known data (24:00)
    r4 = await call(duration=4)
    assert r4["found"] and dt_util.parse_datetime(r4["start"]) >= dt_util.parse_datetime("2026-10-13T12:00:00+02:00")
    # tomorrow not published yet
    r5 = await call(duration=2, period="tomorrow")
    assert r5["found"] is False
    # deadline
    r6 = await call(duration=2, period="today", end_before="2026-10-13T07:00:00")
    assert dt_util.parse_datetime(r6["end"]) <= dt_util.parse_datetime("2026-10-13T07:00:00+02:00")
    # non-contiguous 8 cheapest hours
    r7 = await call(duration=8, period="today", contiguous=False)
    assert r7["contiguous"] is False and len(r7["slots"]) == 8


async def test_fixed_g11_entry(hass: HomeAssistant, freezer):
    await hass.config.async_set_time_zone("Europe/Warsaw")
    freezer.move_to("2026-10-13 12:30:00+02:00")
    entry = MockConfigEntry(domain=DOMAIN, title="Taryfa G11 stała",
                            data={"group": "G11", "energy_mode": "fixed"}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await _done(hass)
    st = hass.states.get("sensor.taryfa_g11_stala_total_price")
    assert float(st.state) == pytest.approx((0.4970 + 0.005 + 0.2464 + 0.0331 + 0.0073 + 0.0030) * 1.23, abs=1e-5)
    assert len(st.attributes["prices"]) == 48


async def test_two_tariffs_need_entry_id(hass: HomeAssistant, g13_dynamic):
    from homeassistant.exceptions import ServiceValidationError
    e2 = MockConfigEntry(domain=DOMAIN, title="Taryfa G11 stała", data={"group": "G11", "energy_mode": "fixed"}, options={})
    e2.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e2.entry_id)
    await _done(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "find_window", {"duration": 2}, blocking=True, return_response=True)
    r = await hass.services.async_call(DOMAIN, "find_window", {"duration": 2, "config_entry_id": e2.entry_id},
                                       blocking=True, return_response=True)
    assert r["found"] is True


async def test_missing_source_is_unavailable_not_crash(hass: HomeAssistant, freezer):
    await hass.config.async_set_time_zone("Europe/Warsaw")
    freezer.move_to("2026-10-13 12:30:00+02:00")
    entry = MockConfigEntry(domain=DOMAIN, title="Taryfa G13 dynamiczna",
                            data={"group": "G13", "energy_mode": "dynamic"}, options={"price_entity": SRC})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await _done(hass)
    assert hass.states.get("sensor.taryfa_g13_dynamiczna_total_price").state == "unavailable"
    hass.states.async_set(SRC, "536.09", tge_attrs())   # source appears later (HA startup order)
    await _done(hass)
    assert hass.states.get("sensor.taryfa_g13_dynamiczna_total_price").state != "unavailable"


async def test_flow_rejects_bad_entity(hass: HomeAssistant):
    hass.states.async_set("sensor.foo", "1", {"unit_of_measurement": "°C"})
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"operator": "tauron", "energy_mode": "dynamic"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"group": "g13"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {
        "price_entity": "sensor.foo", "source_includes_vat": False, "margin": 0.0892, "excise": 0.0})
    assert r["errors"] == {"price_entity": "unsupported_unit"}


async def test_options_change_margin(hass: HomeAssistant, g13_dynamic):
    entry = g13_dynamic
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "price_entity": SRC, "source_includes_vat": False, "margin": 0.1, "excise": 0.005})
    assert r["step_id"] == "distribution"
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "dist_morning_peak": 0.2203, "dist_afternoon_peak": 0.3898, "dist_other": 0.0392,
        "quality_fee": 0.0331, "oze_fee": 0.0073, "cogeneration_fee": 0.0030, "vat": 0.23,
        "phases": "1", "billing_months": "1", "capacity_bracket": "1200_2800"})
    assert r["step_id"] == "zones"
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "hours_morning_peak": "7-13", "hours_morning_peak_summer": "7-13",
        "hours_afternoon_peak": "16-21", "hours_afternoon_peak_summer": "19-22"})
    assert r["step_id"] == "indicators"
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "window_hours": 16, "cheap_fraction": 0.25, "extreme_fraction": 0.1667, "reference_days": 7,
        "charge_very_cheap": 100, "charge_cheap": 81, "charge_average": 66, "charge_expensive": 20})
    assert r["type"] == "create_entry"
    await _done(hass)
    st = hass.states.get("sensor.taryfa_g13_dynamiczna_energy_price")
    assert float(st.state) == pytest.approx((0.53609 + 0.1 + 0.005) * 1.23, abs=1e-5)


async def test_indicator_entities(hass: HomeAssistant, g13_dynamic):
    ref = hass.states.get("sensor.taryfa_g13_dynamiczna_reference_price")
    # no recorder in tests: reference = forecast inertia only (11.5 h to the end of today)
    assert ref.attributes["forecast_hours"] == pytest.approx(11.5)
    assert ref.attributes["history_inertia"] is not None   # slots seen since midnight
    assert float(ref.state) > 0
    med = hass.states.get("sensor.taryfa_g13_dynamiczna_window_median")
    assert med.attributes["window_hours"] == pytest.approx(11.5)   # only 11.5 h known ahead
    level = hass.states.get("sensor.taryfa_g13_dynamiczna_price_level").state
    assert level in ("very_cheap", "cheap", "normal", "expensive", "very_expensive")
    cheap = hass.states.get("binary_sensor.taryfa_g13_dynamiczna_cheap_now").state
    exp = hass.states.get("binary_sensor.taryfa_g13_dynamiczna_expensive_now").state
    assert (cheap == "on") == (level in ("very_cheap", "cheap"))
    assert (exp == "on") == (level in ("expensive", "very_expensive"))
    tgt = float(hass.states.get("sensor.taryfa_g13_dynamiczna_charge_target").state)
    assert 0 <= tgt <= 100
    assert hass.states.get("sensor.taryfa_g13_dynamiczna_price_score").state not in ("unknown", "unavailable")



# ---------- several meters, operators, names, zone hours ----------

async def _create(hass, name, operator, group, mode="fixed", dist=None, zones=None, names=None):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"name": name, "operator": operator, "energy_mode": mode})
    assert r["step_id"] == "group"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"group": group})
    assert r["step_id"] == f"energy_{mode}"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {})   # defaults
    assert r["step_id"] == "distribution", r
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {**(names or {}), **(dist or {})})
    if r.get("step_id") == "zones":
        r = await hass.config_entries.flow.async_configure(r["flow_id"], zones or {})
    assert r["type"] == "create_entry", r
    await _done(hass)
    return r["result"]


async def test_two_meters_different_operators(hass: HomeAssistant, freezer):
    from homeassistant.helpers import device_registry as dr
    await hass.config.async_set_time_zone("Europe/Warsaw")
    freezer.move_to("2026-10-13 14:30:00+02:00")   # Tuesday, winter
    home = await _create(hass, "Dom", "tauron", "g11")
    garage = await _create(hass, "Garaż", "pge", "g12")
    assert home.title == "Dom" and garage.title == "Garaż"
    assert garage.data["operator"] == "pge"
    st = hass.states.get("sensor.garaz_zone")
    assert st.state == "night"                          # PGE G12 winter: night 13–15
    assert st.attributes["operator"] == "pge"
    assert hass.states.get("sensor.dom_total_price") is not None
    dev = dr.async_get(hass).async_get_device({(DOMAIN, garage.entry_id)})
    assert dev.manufacturer == "PGE Dystrybucja"
    dev = dr.async_get(hass).async_get_device({(DOMAIN, home.entry_id)})
    assert dev.manufacturer == "TAURON Dystrybucja / TAURON Sprzedaż"
    g = float(hass.states.get("sensor.garaz_distribution_price").state)
    assert g == pytest.approx((0.0765 + 0.0331 + 0.0073 + 0.0030) * 1.23, abs=1e-5)


async def test_pge_g12_summer_hours(hass: HomeAssistant, freezer):
    await hass.config.async_set_time_zone("Europe/Warsaw")
    freezer.move_to("2026-07-14 14:30:00+02:00")
    await _create(hass, "Lato", "pge", "g12")
    assert hass.states.get("sensor.lato_zone").state == "day"       # summer night is 15–17


async def test_custom_names_and_hours(hass: HomeAssistant, freezer):
    from homeassistant.helpers import device_registry as dr
    await hass.config.async_set_time_zone("Europe/Warsaw")
    freezer.move_to("2026-10-13 16:30:00+02:00")
    e = await _create(hass, "", "enea", "g12",
                      names={"operator_name": "Enea Operator Poznań", "seller_name": "Mój sprzedawca"},
                      zones={"hours_night": "15:00-17:00; 22-6"})
    assert e.title == "Taryfa Enea G12 stała"
    assert e.options["hours_night"] == "15-17, 22-6"
    assert hass.states.get("sensor.taryfa_enea_g12_stala_zone").state == "night"
    dev = dr.async_get(hass).async_get_device({(DOMAIN, e.entry_id)})
    assert dev.manufacturer == "Enea Operator Poznań / Mój sprzedawca"


async def test_zone_hours_validation(hass: HomeAssistant):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"operator": "energa", "energy_mode": "fixed"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"group": "g12r"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {})
    assert r["step_id"] == "zones"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"hours_offpeak": "13-16, 25-7"})
    assert r["errors"] == {"hours_offpeak": "invalid_hours"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"hours_offpeak": ""})
    assert r["errors"] == {"hours_offpeak": "empty_hours"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"hours_offpeak": "13-16, 22-7"})
    assert r["type"] == "create_entry"


async def test_group_list_depends_on_operator(hass: HomeAssistant):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"operator": "stoen", "energy_mode": "fixed"})
    sel = next(v for k, v in r["data_schema"].schema.items() if k == "group")
    assert sel.config["options"] == ["g11", "g12", "g12w", "g12as"]


async def test_same_title_gets_suffix(hass: HomeAssistant, g13_dynamic):
    e2 = MockConfigEntry(domain=DOMAIN, title="Taryfa G13 dynamiczna",
                         data={"group": "G13", "energy_mode": "dynamic"}, options={"price_entity": SRC})
    e2.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e2.entry_id)
    await _done(hass)
    assert hass.states.get("sensor.taryfa_g13_dynamiczna_total_price_2") is not None
