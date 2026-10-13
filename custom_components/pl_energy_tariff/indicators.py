"""Price indicators: reference (average) price, price window ranking, charge target. Pure Python.

Reference price ("weekly inertia with forecast"):
  * forecast inertia F – exponentially weighted mean of the known future prices, weight
    exp(-t/τf) for t hours ahead, τf = H = length of the remaining forecast;
  * history inertia P – exponential moving average of past prices (first-order lag, the
    same filter as the old "średnia cena prądu"), τh = W − H, W = one week;
  * reference R = (τf·F + τh·P) / W  (weighted by the time constants).
The same weights applied to p² give the second moment, so σ² = M2 − R².
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

HOUR = 3600.0


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime
    price: float


@dataclass(frozen=True)
class Moments:
    m1: float
    m2: float

    @property
    def sigma(self) -> float:
        return math.sqrt(max(self.m2 - self.m1 * self.m1, 0.0))


def history_inertia(samples: Sequence[tuple[datetime, float]], now: datetime, tau_h: float) -> Moments | None:
    """First-order lag over a piecewise-constant price history (exact integration).

    ``samples``: (time the price became valid, price), sorted. The filter starts at the
    first sample's value; with ≥3τ of history the start value no longer matters.
    """
    pts = [(t, p) for t, p in samples if t <= now]
    if not pts:
        return None
    tau = max(tau_h, 1e-9) * HOUR
    m1, m2 = pts[0][1], pts[0][1] ** 2
    for (t, p), nxt in zip(pts, [*(x[0] for x in pts[1:]), now]):
        dt = (nxt - t).total_seconds()
        if dt <= 0:
            continue
        k = math.exp(-dt / tau)
        m1 = m1 * k + p * (1 - k)
        m2 = m2 * k + p * p * (1 - k)
    return Moments(m1, m2)


def forecast_inertia(slots: Sequence[Slot], now: datetime) -> tuple[Moments | None, float]:
    """Exponentially weighted mean of prices from ``now`` to the end of the forecast.

    τ equals the forecast length H. Returns (moments, H in hours).
    """
    fut = [s for s in slots if s.end > now]
    if not fut:
        return None, 0.0
    horizon = (fut[-1].end - now).total_seconds() / HOUR
    if horizon <= 0:
        return None, 0.0
    tau = horizon
    w_sum = s1 = s2 = 0.0
    for s in fut:
        a = max((s.start - now).total_seconds() / HOUR, 0.0)
        b = (s.end - now).total_seconds() / HOUR
        w = tau * (math.exp(-a / tau) - math.exp(-b / tau))
        w_sum += w
        s1 += w * s.price
        s2 += w * s.price * s.price
    return Moments(s1 / w_sum, s2 / w_sum), horizon


@dataclass(frozen=True)
class Reference:
    price: float
    sigma: float
    forecast: float | None
    history: float | None
    horizon_h: float
    tau_forecast_h: float
    tau_history_h: float


def reference_price(history: Sequence[tuple[datetime, float]], slots: Sequence[Slot], now: datetime,
                    week_h: float = 168.0) -> Reference | None:
    fc, horizon = forecast_inertia(slots, now)
    horizon = min(horizon, week_h)
    tau_h = week_h - horizon
    hi = history_inertia(history, now, tau_h) if tau_h > 0 else None
    parts = [(horizon, fc), (tau_h, hi)]
    parts = [(w, m) for w, m in parts if m is not None and w > 0]
    if not parts:
        return None
    total = sum(w for w, _ in parts)
    m1 = sum(w * m.m1 for w, m in parts) / total
    m2 = sum(w * m.m2 for w, m in parts) / total
    return Reference(
        price=m1,
        sigma=math.sqrt(max(m2 - m1 * m1, 0.0)),
        forecast=fc.m1 if fc else None,
        history=hi.m1 if hi else None,
        horizon_h=horizon,
        tau_forecast_h=horizon,
        tau_history_h=tau_h,
    )


def price_score(price: float, ref: Reference) -> float | None:
    """Deviation from the reference, same scale as the old "standaryzowana cena":
    100 · (p − R) / (σ · R)."""
    if ref.sigma <= 0 or ref.price <= 0:
        return None
    return 100.0 * (price - ref.price) / (ref.sigma * ref.price)


@dataclass(frozen=True)
class WindowStats:
    start: datetime
    end: datetime
    hours: float
    median: float
    very_cheap_max: float   # price of the k-th cheapest slot (extreme fraction)
    cheap_max: float        # price of the k-th cheapest slot (fraction)
    expensive_min: float
    very_expensive_min: float
    slots: int


def _kth(prices: list[float], frac: float) -> int:
    return max(1, min(len(prices), round(len(prices) * frac)))


def window_stats(slots: Sequence[Slot], now: datetime, hours: float = 16.0, fraction: float = 0.25,
                 extreme: float = 1 / 6, min_hours: float = 4.0) -> WindowStats | None:
    """Rank the slots from the current one up to ``hours`` ahead.

    The cheapest ``fraction`` of the window is "cheap", the cheapest ``extreme`` is
    "very cheap"; symmetrically for expensive. Ties go to the cheaper/expensive side.
    """
    end = now + timedelta(hours=hours)
    win = [s for s in slots if s.end > now and s.start < end]
    if not win:
        return None
    span = (min(win[-1].end, end) - max(win[0].start, now)).total_seconds() / HOUR
    if span < min_hours:
        return None
    asc = sorted(s.price for s in win)
    n = len(asc)
    mid = n // 2
    median = asc[mid] if n % 2 else (asc[mid - 1] + asc[mid]) / 2
    return WindowStats(
        start=win[0].start,
        end=win[-1].end,
        hours=round(span, 2),
        median=median,
        very_cheap_max=asc[_kth(asc, extreme) - 1],
        cheap_max=asc[_kth(asc, fraction) - 1],
        expensive_min=asc[n - _kth(asc, fraction)],
        very_expensive_min=asc[n - _kth(asc, extreme)],
        slots=n,
    )


LEVELS = ("very_cheap", "cheap", "normal", "expensive", "very_expensive")


def price_level(price: float, w: WindowStats) -> str:
    if price <= w.very_cheap_max:
        return "very_cheap"
    if price <= w.cheap_max:
        return "cheap"
    if price >= w.very_expensive_min:
        return "very_expensive"
    if price >= w.expensive_min:
        return "expensive"
    return "normal"


@dataclass(frozen=True)
class ChargeLevels:
    very_cheap: float = 100.0   # at/below the very-cheap threshold
    cheap: float = 81.0         # at the cheap threshold
    average: float = 66.0       # at the reference price
    expensive: float = 20.0     # just below the expensive threshold
    # in the expensive part of the window: 0 (do not charge)


def charge_target(price: float, w: WindowStats, ref_price: float, lv: ChargeLevels = ChargeLevels()) -> float:
    """Battery charge target [%], piecewise linear and non-increasing in price.

    very cheap ≤ C6 → 100 · C4 → 81 · reference R → 66 · just below E4 → 20 · ≥ E4 → 0.
    R is clamped into [C4, E4] so the curve stays monotone on unusual days.
    """
    if price >= w.expensive_min:
        return 0.0
    c6, c4, e4 = w.very_cheap_max, w.cheap_max, w.expensive_min
    r = min(max(ref_price, c4), e4)
    pts = [(c6, lv.very_cheap), (c4, lv.cheap), (r, lv.average), (e4, lv.expensive)]
    if price <= pts[0][0]:
        return lv.very_cheap
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if price <= x1:
            if x1 <= x0:
                return y1
            return round(y0 + (y1 - y0) * (price - x0) / (x1 - x0), 1)
    return lv.expensive
