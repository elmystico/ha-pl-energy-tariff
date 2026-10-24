"""Read exchange prices (RDN, RCE, …) from another entity's attributes. Pure Python.

Supported shape (TGE RDN, PGE-TGE, TGE and most price integrations):
    attributes = {"prices_today": [{"time": iso, "price": x}, …], "prices_tomorrow": […]}
or a single list under "prices". Item keys are matched loosely (time/start/…, price/value/…).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .pricing import TZ, SourcePoint

LIST_KEYS = ("prices_today", "prices_tomorrow", "prices", "today", "tomorrow", "raw_today", "raw_tomorrow", "data")
TIME_KEYS = ("time", "start", "start_time", "startsAt", "from", "datetime", "dtime", "period_start")
END_KEYS = ("end", "end_time", "endsAt", "to", "period_end")
VALUE_KEYS = ("price", "value", "rce_pln", "rce", "cena", "total")

UNIT_FACTORS = {
    "zł/mwh": 0.001, "pln/mwh": 0.001,
    "zł/kwh": 1.0, "pln/kwh": 1.0,
    "gr/kwh": 0.01,
}


def unit_factor(unit: str | None) -> float | None:
    if not unit:
        return None
    return UNIT_FACTORS.get(unit.replace(" ", "").lower())


def _parse_time(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(timezone.utc)  # UTC: see pricing.hourly_slots


def _first(d: dict, keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def parse_points(attributes: dict[str, Any], unit: str | None, includes_vat: bool = False,
                 vat: float = 0.23) -> list[SourcePoint]:
    """Netto zł/kWh points, deduplicated and sorted. Raises ValueError on unknown unit."""
    factor = unit_factor(unit)
    if factor is None:
        raise ValueError(f"unsupported price unit: {unit!r}")
    raw: list[tuple[datetime, datetime | None, float]] = []
    keys = [k for k in LIST_KEYS if isinstance(attributes.get(k), list)]
    if "prices" in keys and ("prices_today" in keys or "prices_tomorrow" in keys):
        keys.remove("prices")  # same data twice
    for key in keys:
        for item in attributes[key]:
            if not isinstance(item, dict):
                continue
            start = _parse_time(_first(item, TIME_KEYS))
            val = _first(item, VALUE_KEYS)
            if start is None or val is None:
                continue
            try:
                price = float(val) * factor
            except (TypeError, ValueError):
                continue
            if includes_vat:
                price /= 1 + vat
            raw.append((start, _parse_time(_first(item, END_KEYS)), price))

    by_start: dict[datetime, tuple[datetime | None, float]] = {}
    for s, e, p in raw:
        by_start[s] = (e, p)
    starts = sorted(by_start)
    if not starts:
        return []
    # default slot length = most common gap, fallback 1 h
    gaps = [b - a for a, b in zip(starts, starts[1:]) if b > a]
    step = max(set(gaps), key=gaps.count) if gaps else timedelta(hours=1)
    out = []
    for s in starts:
        e, p = by_start[s]
        out.append(SourcePoint(s, e or s + step, round(p, 6)))
    return out
