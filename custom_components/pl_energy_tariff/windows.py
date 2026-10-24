"""Cheapest / most expensive time windows. Pure Python, no HA imports."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from .pricing import iso_local

MODE_CHEAPEST = "cheapest"
MODE_EXPENSIVE = "most_expensive"


@dataclass(frozen=True)
class PricePoint:
    start: datetime
    end: datetime
    price: float


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    average: float
    points: tuple[PricePoint, ...]
    contiguous: bool

    @property
    def ranges(self) -> list[tuple[datetime, datetime]]:
        """Merged [start, end) ranges (one for a contiguous window)."""
        out: list[tuple[datetime, datetime]] = []
        for p in sorted(self.points, key=lambda x: x.start):
            if out and out[-1][1] == p.start:
                out[-1] = (out[-1][0], p.end)
            else:
                out.append((p.start, p.end))
        return out

    def contains(self, t: datetime) -> bool:
        return any(s <= t < e for s, e in self.ranges)

    def as_dict(self) -> dict:
        return {
            "start": iso_local(self.start),
            "end": iso_local(self.end),
            "average": round(self.average, 5),
            "contiguous": self.contiguous,
            "ranges": [{"start": iso_local(s), "end": iso_local(e)} for s, e in self.ranges],
            "slots": [{"start": iso_local(p.start), "price": p.price} for p in self.points],
        }


def find_window(
    points: Iterable[PricePoint],
    duration: timedelta,
    mode: str = MODE_CHEAPEST,
    contiguous: bool = True,
) -> Window | None:
    """Find the cheapest (or most expensive) window of the given duration.

    ``points`` must be equally spaced; a contiguous window may not cross a gap.
    Ties are resolved towards the earliest start.
    """
    pts = sorted(points, key=lambda p: p.start)
    if not pts:
        return None
    step = pts[0].end - pts[0].start
    # round up to whole slots (1,5 h on hourly prices -> 2 h)
    n = math.ceil(duration / step - 1e-9)
    if n <= 0 or n > len(pts):
        return None
    sign = 1 if mode == MODE_CHEAPEST else -1

    if not contiguous:
        chosen = sorted(pts, key=lambda p: (sign * p.price, p.start))[:n]
        chosen.sort(key=lambda p: p.start)
        return Window(
            start=chosen[0].start,
            end=chosen[-1].end,
            average=sum(p.price for p in chosen) / n,
            points=tuple(chosen),
            contiguous=False,
        )

    best: tuple[float, int] | None = None
    for i in range(len(pts) - n + 1):
        seg = pts[i : i + n]
        if any(seg[k + 1].start != seg[k].end for k in range(n - 1)):
            continue  # gap inside
        score = sign * sum(p.price for p in seg)
        if best is None or score < best[0]:
            best = (score, i)
    if best is None:
        return None
    seg = pts[best[1] : best[1] + n]
    return Window(
        start=seg[0].start,
        end=seg[-1].end,
        average=sum(p.price for p in seg) / n,
        points=tuple(seg),
        contiguous=True,
    )


SPEC_RE = re.compile(
    r"^(cheapest|expensive|most_expensive)\s*:\s*(\d+(?:[.,]\d+)?)\s*(?::\s*(split))?$", re.I
)


@dataclass(frozen=True)
class WindowSpec:
    mode: str
    hours: float
    contiguous: bool

    @property
    def key(self) -> str:
        kind = "cheapest" if self.mode == MODE_CHEAPEST else "expensive"
        h = f"{self.hours:g}".replace(".", "_")
        return f"{kind}_{h}h" + ("" if self.contiguous else "_split")

    def label(self, lang: str = "pl") -> str:
        h = f"{self.hours:g}"
        if lang == "pl":
            kind = "Najtańsze" if self.mode == MODE_CHEAPEST else "Najdroższe"
            return f"{kind} {h}h" + ("" if self.contiguous else " (rozproszone)")
        kind = "Cheapest" if self.mode == MODE_CHEAPEST else "Most expensive"
        return f"{kind} {h}h" + ("" if self.contiguous else " (split)")


def parse_specs(text: str) -> list[WindowSpec]:
    """Parse 'cheapest:4, expensive:3, cheapest:6:split'. Raises ValueError."""
    specs: list[WindowSpec] = []
    seen: set[str] = set()
    for part in re.split(r"[,;\n]+", text or ""):
        part = part.strip()
        if not part:
            continue
        m = SPEC_RE.match(part)
        if not m:
            raise ValueError(f"invalid window spec: {part!r}")
        hours = float(m.group(2).replace(",", "."))
        if hours <= 0 or hours > 24 or (hours * 4) != int(hours * 4):
            raise ValueError(f"window length must be a multiple of 0.25 h in (0, 24]: {part!r}")
        mode = MODE_CHEAPEST if m.group(1).lower() == "cheapest" else MODE_EXPENSIVE
        spec = WindowSpec(mode, hours, contiguous=m.group(3) is None)
        if spec.key not in seen:
            seen.add(spec.key)
            specs.append(spec)
    return specs
