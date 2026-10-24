from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from custom_components.pl_energy_tariff import tariffs as T
from custom_components.pl_energy_tariff.holidays_pl import easter_sunday, is_day_off
from custom_components.pl_energy_tariff.pricing import (
    MODE_DYNAMIC,
    MODE_FIXED,
    TZ,
    SourcePoint,
    TariffConfig,
    build_series,
    daily_fixed,
    hourly_slots,
    monthly_fixed,
    price_slot,
    slot_at,
)
from custom_components.pl_energy_tariff.source import parse_points
from custom_components.pl_energy_tariff.windows import (
    MODE_CHEAPEST,
    MODE_EXPENSIVE,
    PricePoint,
    find_window,
)

# TGE RDN Fixing I, 13.10.2026, zł/MWh
F1 = [660.25, 653.98, 647.52, 643.66, 660.29, 709.00, 958.49, 1106.40, 1032.94, 794.39,
      612.67, 600.21, 536.09, 611.16, 648.96, 727.54, 880.71, 1211.72, 1341.35, 1299.99,
      986.34, 730.08, 600.66, 511.22]


def dt(*a):
    return datetime(*a, tzinfo=TZ)


def source_13oct():
    return [SourcePoint(s, e, p / 1000) for (s, e), p in zip(hourly_slots(date(2026, 10, 13), 1), F1)]


# ---------- holidays ----------

def test_easter():
    assert easter_sunday(2026) == date(2026, 4, 5)
    assert easter_sunday(2027) == date(2027, 3, 28)
    assert easter_sunday(2025) == date(2025, 4, 20)


def test_days_off():
    assert is_day_off(date(2026, 6, 4))     # Boże Ciało 2026
    assert is_day_off(date(2026, 4, 6))     # Poniedziałek Wielkanocny
    assert is_day_off(date(2026, 12, 24))   # Wigilia od 2025
    assert is_day_off(date(2026, 11, 11))
    assert is_day_off(date(2026, 10, 17))   # sobota
    assert not is_day_off(date(2026, 10, 13))


# ---------- zones ----------

@pytest.mark.parametrize("when,zone", [
    (dt(2026, 10, 13, 6, 59), "other"),
    (dt(2026, 10, 13, 7, 0), "morning_peak"),
    (dt(2026, 10, 13, 12, 59), "morning_peak"),
    (dt(2026, 10, 13, 13, 0), "other"),
    (dt(2026, 10, 13, 16, 0), "afternoon_peak"),   # winter 16–21
    (dt(2026, 10, 13, 20, 59), "afternoon_peak"),
    (dt(2026, 10, 13, 21, 0), "other"),
    (dt(2026, 7, 1, 16, 0), "other"),              # summer: 16 is off-peak
    (dt(2026, 7, 1, 19, 0), "afternoon_peak"),     # summer 19–22
    (dt(2026, 7, 1, 21, 59), "afternoon_peak"),
    (dt(2026, 11, 11, 8, 0), "other"),             # holiday
    (dt(2026, 10, 17, 18, 0), "other"),            # Saturday
    (dt(2026, 3, 31, 17, 0), "afternoon_peak"),    # last winter day
    (dt(2026, 4, 1, 17, 0), "other"),              # first summer day
])
def test_g13_zones(when, zone):
    assert T.GROUPS["G13"].classify(when)[0] == zone


def test_g12_g12w_g12as_zones():
    g12, g12w, g12as = T.GROUPS["G12"].classify, T.GROUPS["G12w"].classify, T.GROUPS["G12as"].classify
    assert g12(dt(2026, 10, 13, 14, 0))[0] == "night"
    assert g12(dt(2026, 10, 13, 15, 0))[0] == "day"
    assert g12(dt(2026, 10, 17, 10, 0))[0] == "day"          # no weekend rule in G12
    assert g12w(dt(2026, 10, 17, 10, 0))[0] == "offpeak"     # weekend
    assert g12w(dt(2026, 10, 13, 10, 0))[0] == "peak"
    assert g12w(dt(2026, 10, 13, 5, 0))[0] == "offpeak"
    assert g12as(dt(2026, 10, 13, 21, 59))[0] == "day"
    assert g12as(dt(2026, 10, 13, 22, 0))[0] == "night"


def test_g13s_zones_and_rate_keys():
    c = T.GROUPS["G13s"].classify
    assert c(dt(2026, 7, 1, 12, 0)) == ("day_offpeak", "summer_workday_day_offpeak")
    assert c(dt(2026, 7, 4, 8, 0)) == ("day_peak", "summer_dayoff_day_peak")
    assert c(dt(2026, 10, 13, 9, 0)) == ("day_peak", "winter_workday_day_peak")
    assert c(dt(2026, 10, 13, 12, 0)) == ("day_offpeak", "winter_workday_day_offpeak")
    assert c(dt(2026, 10, 13, 23, 0)) == ("night", "winter_workday_night")


def test_rates_match_brutto_published():
    """Netto rates × 1,23 must equal TAURON Dystrybucja published brutto rates 2026."""
    brutto = {
        ("G11", "allday"): 0.3031, ("G12", "day"): 0.3494, ("G12", "night"): 0.0686,
        ("G12w", "peak"): 0.4057, ("G12w", "offpeak"): 0.0630,
        ("G13", "morning_peak"): 0.2710, ("G13", "afternoon_peak"): 0.4795, ("G13", "other"): 0.0482,
        ("G13s", "summer_workday_day_offpeak"): 0.1230, ("G13s", "winter_dayoff_day_peak"): 0.2411,
    }
    for (g, k), b in brutto.items():
        assert round(T.GROUPS[g].dist_rates[k] * 1.23, 4) == b
    assert round(T.QUALITY_FEE * 1.23, 4) == 0.0407 or round(T.QUALITY_FEE * 1.23, 4) == 0.0408


def test_seller_prices_match_published_brutto():
    """(URE tariff netto + akcyza) × 1,23 = brutto prices published for TAURON 2026."""
    g13 = T.GROUPS["G13"].energy_rates
    assert round((g13["other"] + T.EXCISE) * 1.23, 4) == 0.5240
    assert round((g13["morning_peak"] + T.EXCISE) * 1.23, 4) == 0.5803
    assert round((g13["afternoon_peak"] + T.EXCISE) * 1.23, 4) == 0.9631
    assert round((T.GROUPS["G11"].energy_rates["allday"] + T.EXCISE) * 1.23, 4) == 0.6175


# ---------- prices ----------

def test_dynamic_g13_example_from_doc():
    cfg = TariffConfig.defaults("G13", MODE_DYNAMIC)
    s = price_slot(cfg, dt(2026, 10, 13, 0), dt(2026, 10, 13, 1), 0.66025)
    assert s.zone == "other"
    assert s.energy == pytest.approx(0.92182, abs=1e-5)
    # VAT on the netto sum, as invoiced (brutto-rounded rates would give 1,02352)
    assert s.distribution == pytest.approx(0.0826 * 1.23, abs=1e-5)
    assert s.total == pytest.approx((0.66025 + 0.0892 + 0.0826) * 1.23, abs=1e-5)


def test_dynamic_g13_peak_matches_live_templates():
    # 13.10.2026 12:48: HA templates (brutto-rounded rates) showed 0,76911 + 0,3245 = 1,09361
    cfg = TariffConfig.defaults("G13", MODE_DYNAMIC)
    s = price_slot(cfg, dt(2026, 10, 13, 12), dt(2026, 10, 13, 13), 0.53609)
    assert s.zone == "morning_peak"
    assert s.energy == pytest.approx(0.76911, abs=1e-5)
    assert s.total == pytest.approx(1.09361, abs=2e-4)


def test_fixed_g13_series():
    cfg = TariffConfig.defaults("G13", MODE_FIXED)
    series = build_series(cfg, None, date(2026, 10, 13))
    assert len(series) == 48
    assert series[0].energy == pytest.approx(0.52398, abs=1e-5)
    s18 = slot_at(series, dt(2026, 10, 13, 18, 30))
    assert s18.zone == "afternoon_peak"
    assert s18.total == pytest.approx((0.7780 + 0.005 + 0.3898 + 0.0331 + 0.0073 + 0.0030) * 1.23, abs=1e-5)


def test_dst_series_length():
    cfg = TariffConfig.defaults("G11", MODE_FIXED)
    assert len(build_series(cfg, None, date(2026, 10, 25))) == 25 + 24
    assert len(build_series(cfg, None, date(2026, 3, 29))) == 23 + 24


def test_monthly_fixed():
    m = monthly_fixed(TariffConfig.defaults("G13"))
    assert m["network_fixed"] == 9.08
    assert m["subscription"] == 5.61
    assert m["capacity"] == 21.13
    assert m["total"] == round((7.38 + 4.56 + 17.18) * 1.23, 2)


def test_daily_fixed_sums_to_monthly():
    cfg = TariffConfig.defaults("G13")
    m = monthly_fixed(cfg)
    for d, days in ((date(2026, 2, 1), 28), (date(2028, 2, 1), 29), (date(2026, 4, 1), 30), (date(2026, 10, 1), 31)):
        f = daily_fixed(cfg, d)
        assert f["days_in_month"] == days
        assert f["total"] * days == pytest.approx(m["total"], abs=0.01)


# ---------- source ----------

def test_parse_tge_rdn_attributes():
    attrs = {
        "prices_today": [{"time": "2026-10-13T00:00:00+02:00", "price": 660.25},
                         {"time": "2026-10-13T01:00:00+02:00", "price": 653.98}],
        "prices_tomorrow": [],
        "prices": [{"time": "2026-10-13T00:00:00+02:00", "price": 660.25}],
    }
    pts = parse_points(attrs, "zł/MWh")
    assert [p.price for p in pts] == [0.66025, 0.65398]
    assert pts[0].end - pts[0].start == timedelta(hours=1)


def test_parse_units_and_vat():
    attrs = {"prices": [{"start": "2026-10-13T00:00:00+02:00", "value": 61.5}]}
    pts = parse_points(attrs, "gr/kWh", includes_vat=True)
    assert pts[0].price == pytest.approx(0.5)
    with pytest.raises(ValueError):
        parse_points(attrs, "EUR/MWh")


# ---------- windows on total price ----------

def test_cheapest_window_total_vs_exchange():
    """With G13 distribution the cheapest 3 h differ from the cheapest exchange hours."""
    cfg = TariffConfig.defaults("G13", MODE_DYNAMIC)
    series = build_series(cfg, source_13oct(), date(2026, 10, 13))
    total = [PricePoint(s.start, s.end, s.total) for s in series]
    exch = [PricePoint(s.start, s.end, s.exchange) for s in series]
    w_total = find_window(total, timedelta(hours=3), MODE_CHEAPEST)
    w_exch = find_window(exch, timedelta(hours=3), MODE_CHEAPEST)
    def lh(d):  # slot boundaries are UTC; compare local hours
        return d.astimezone(TZ).hour

    assert (lh(w_exch.start), lh(w_exch.end)) == (11, 14)   # midday dip on the exchange
    assert lh(w_total.start) in (13, 21, 22, 0, 1, 2, 3)     # outside G13 peaks
    assert lh(w_total.start) != 11
    w_max = find_window(total, timedelta(hours=2), MODE_EXPENSIVE)
    assert (lh(w_max.start), lh(w_max.end)) == (18, 20)


# ---------- operators and editable zone hours ----------

def test_parse_ranges():
    assert T.parse_ranges("13-15, 22-6") == ((13, 15), (22, 6))
    assert T.parse_ranges("13:00 – 15:00; 22-24") == ((13, 15), (22, 0))
    assert T.parse_ranges("") == ()
    for bad in ("13", "25-6", "6-6", "a-b", "13-15,,x"):
        with pytest.raises(ValueError):
            T.parse_ranges(bad)
    assert T.format_ranges(((13, 15), (22, 6))) == "13-15, 22-6"


def test_operator_catalogue_consistent():
    for op in T.OPERATORS.values():
        assert op.subscription[1] > 0
        for g in op.groups.values():
            assert set(g.energy_rates) == set(g.energy_zones), (op.key, g.key)
            if g.classify_fn is None:
                assert set(g.dist_rates) == set(g.energy_zones), (op.key, g.key)
            sch = g.schedule
            if sch:
                zones = {sch.default, *sch.winter, *(sch.summer or {})}
                if sch.dayoff_zone:
                    zones.add(sch.dayoff_zone)
                assert zones <= set(g.energy_zones), (op.key, g.key)
            # every hour of a week, summer and winter, maps to a known zone
            for day in (date(2026, 1, 12), date(2026, 7, 13)):
                for h in range(24 * 7):
                    t = datetime.combine(day, datetime.min.time(), TZ) + timedelta(hours=h)
                    z, k = g.classify(t)
                    assert z in g.energy_zones and k in g.dist_rates


def c(op, grp, *a):
    return T.group(op, grp).classify(dt(*a))[0]


def test_pge_zones():
    assert c("pge", "G12", 2026, 1, 13, 14) == "night"     # winter 13–15
    assert c("pge", "G12", 2026, 7, 14, 14) == "day"       # summer 15–17
    assert c("pge", "G12", 2026, 7, 14, 16) == "night"
    assert c("pge", "G12w", 2026, 7, 18, 10) == "offpeak"  # Saturday
    assert c("pge", "G12n", 2026, 10, 17, 10) == "day"     # Saturday is a normal day in G12n
    assert c("pge", "G12n", 2026, 10, 17, 2) == "night"    # 1–5
    assert c("pge", "G12n", 2026, 10, 18, 10) == "night"   # Sunday
    assert c("pge", "G12n", 2026, 11, 11, 12) == "night"   # holiday


def test_enea_energa_stoen_zones():
    assert c("enea", "G12w", 2026, 10, 13, 20) == "peak"      # Enea G12w peak 6–21
    assert c("enea", "G12w", 2026, 10, 13, 21) == "offpeak"
    assert c("energa", "G12r", 2026, 10, 13, 15) == "offpeak"  # 13–16
    assert c("energa", "G12r", 2026, 10, 13, 6) == "offpeak"   # 22–7
    assert c("energa", "G12r", 2026, 10, 13, 7) == "peak"
    assert c("stoen", "G12w", 2026, 10, 13, 14) == "peak"      # Stoen G12w: no afternoon valley
    assert c("stoen", "G12w", 2026, 10, 13, 22) == "offpeak"


def test_schedule_from_options():
    base = T.group("pge", "G12").schedule
    s = T.schedule_from_options(base, {"hours_night": "22-7", "hours_night_summer": ""})
    assert s.zone(dt(2026, 7, 14, 16)) == "day"      # empty summer = winter hours
    assert s.zone(dt(2026, 7, 14, 6)) == "night"
    s = T.schedule_from_options(base, {})
    assert s == base
    with pytest.raises(ValueError):
        T.schedule_from_options(base, {"hours_night": "x"})


def test_config_uses_custom_schedule_and_operator_fees():
    sch = T.schedule_from_options(T.group("enea", "G12").schedule, {"hours_night": "15-17, 22-6"})
    cfg = replace(TariffConfig.defaults("G12", MODE_FIXED, "enea"), schedule=sch)
    assert cfg.classify(dt(2026, 10, 13, 16))[0] == "night"
    assert cfg.quality_fee == 0.0332
    assert monthly_fixed(cfg)["subscription"] == round(3.84 * 1.23, 2)
    assert cfg.manufacturer == "ENEA Operator"


def test_dst_25h_day_keeps_repeated_hour():
    """2026-10-25: 02:00+02:00 and 02:00+01:00 are distinct slots (PEP 495 fold)."""
    d = date(2026, 10, 25)
    starts = [s for s, _ in hourly_slots(d, 1)]
    attrs = {"prices_tomorrow": [
        {"time": s.astimezone(TZ).isoformat(), "price": 100.0 + i} for i, s in enumerate(starts)
    ]}
    pts = parse_points(attrs, "PLN/MWh")
    assert len(pts) == 25
    cfg = TariffConfig.defaults("G13")
    series = build_series(cfg, pts, d)
    assert len(series) == 25
    assert [p.exchange for p in series] == pytest.approx([(100.0 + i) / 1000 for i in range(25)])
    second_two = datetime(2026, 10, 25, 2, 30, tzinfo=TZ, fold=1)
    assert slot_at(series, second_two).exchange == pytest.approx(0.103)


def test_dst_23h_day():
    """2026-03-29: 02:00–03:00 does not exist -> 23 consecutive slots, zones by local hour."""
    d = date(2026, 3, 29)
    slots = hourly_slots(d, 1)
    assert len(slots) == 23
    assert all(a[1] == b[0] for a, b in zip(slots, slots[1:]))
    starts = [s for s, _ in slots]
    attrs = {"prices_today": [
        {"time": s.astimezone(TZ).isoformat(), "price": 100.0 + i} for i, s in enumerate(starts)
    ]}
    pts = parse_points(attrs, "PLN/MWh")
    series = build_series(TariffConfig.defaults("G13"), pts, d)
    assert len(series) == 23
    assert [p.start.astimezone(TZ).hour for p in series[:4]] == [0, 1, 3, 4]
    assert series[2].start.astimezone(TZ).utcoffset() == timedelta(hours=2)
    assert slot_at(series, datetime(2026, 3, 29, 3, 30, tzinfo=TZ)).exchange == pytest.approx(0.102)


def test_window_horizon_is_elapsed_time_across_dst():
    """16 h ahead from 2026-10-24 18:00 covers 16 real hours (17 wall-clock hours later)."""
    from datetime import timezone

    from custom_components.pl_energy_tariff.indicators import Slot, window_stats

    start = datetime(2026, 10, 24, 0, 0, tzinfo=TZ).astimezone(timezone.utc)
    slots = [Slot(start + timedelta(hours=i), start + timedelta(hours=i + 1), float(i)) for i in range(49)]
    now = datetime(2026, 10, 24, 18, 0, tzinfo=TZ)
    w = window_stats(slots, now, hours=16.0)
    assert w is not None and w.hours == pytest.approx(16.0)
