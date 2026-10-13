import math
from datetime import date, datetime, timedelta

import pytest

from custom_components.pl_energy_tariff.indicators import (
    ChargeLevels,
    Slot,
    charge_target,
    forecast_inertia,
    history_inertia,
    price_level,
    price_score,
    reference_price,
    window_stats,
)
from custom_components.pl_energy_tariff.pricing import TZ, hourly_slots
from tests.test_engine import F1

T0 = datetime(2026, 10, 13, 0, 0, tzinfo=TZ)


def day_slots(prices=F1, day=date(2026, 10, 13)):
    return [Slot(s, e, p / 1000) for (s, e), p in zip(hourly_slots(day, 1), prices)]


def test_history_inertia_step_response():
    tau = 10.0
    samples = [(T0, 1.0), (T0 + timedelta(hours=100), 2.0)]
    m = history_inertia(samples, T0 + timedelta(hours=110), tau)
    assert m.m1 == pytest.approx(2 - math.exp(-1), abs=1e-9)   # 1 − e^(−t/τ) of the step
    assert history_inertia([], T0, tau) is None


def test_forecast_inertia_constant_and_weighting():
    flat = [Slot(T0 + timedelta(hours=i), T0 + timedelta(hours=i + 1), 0.5) for i in range(24)]
    m, h = forecast_inertia(flat, T0)
    assert h == 24 and m.m1 == pytest.approx(0.5)
    # near hours weigh more: rising prices → mean below the plain average
    rising = [Slot(s.start, s.end, i / 10) for i, s in enumerate(flat)]
    m2, _ = forecast_inertia(rising, T0)
    assert m2.m1 < sum(i / 10 for i in range(24)) / 24


def test_reference_weights_by_time_constants():
    hist = [(T0 - timedelta(days=30), 1.0)]
    fc = [Slot(T0 + timedelta(hours=i), T0 + timedelta(hours=i + 1), 2.0) for i in range(24)]
    r = reference_price(hist, fc, T0, week_h=168)
    assert r.tau_forecast_h == 24 and r.tau_history_h == 144
    assert r.price == pytest.approx((24 * 2.0 + 144 * 1.0) / 168)
    assert r.sigma == pytest.approx(math.sqrt((24 * 4 + 144 * 1) / 168 - r.price ** 2))
    assert price_score(r.price, r) == 0
    assert price_score(2.0, r) > 0


def test_window_ranking_13oct():
    w = window_stats(day_slots(), T0, hours=16, fraction=0.25, extreme=1 / 6)
    assert w.slots == 16 and w.hours == 16
    prices = sorted(p / 1000 for p in F1[:16])
    assert w.cheap_max == prices[3] and w.very_cheap_max == prices[2]
    assert w.expensive_min == prices[-4] and w.very_expensive_min == prices[-3]
    assert price_level(prices[0], w) == "very_cheap"
    assert price_level(prices[3], w) == "cheap"
    assert price_level(prices[8], w) == "normal"
    assert price_level(prices[-1], w) == "very_expensive"
    # too little data ahead
    assert window_stats(day_slots(), T0 + timedelta(hours=21), hours=16) is None


def test_charge_target_curve():
    w = window_stats(day_slots(), T0, hours=16)
    ref = (w.cheap_max + w.expensive_min) / 2
    lv = ChargeLevels()
    assert charge_target(w.very_cheap_max, w, ref) == 100
    assert charge_target(w.cheap_max, w, ref) == 81
    assert charge_target(ref, w, ref) == 66
    assert charge_target(w.expensive_min, w, ref) == 0
    just_below = w.expensive_min - 1e-6
    assert charge_target(just_below, w, ref) == pytest.approx(lv.expensive, abs=0.1)
    xs = [w.very_cheap_max - 0.1 + i * 0.01 for i in range(200)]
    ys = [charge_target(x, w, ref) for x in xs]
    assert all(a >= b for a, b in zip(ys, ys[1:]))           # monotone
    # reference outside [cheap, expensive] is clamped, curve stays monotone
    ys2 = [charge_target(x, w, 5.0) for x in xs]
    assert all(a >= b for a, b in zip(ys2, ys2[1:]))
