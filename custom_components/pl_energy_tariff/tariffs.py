"""Distribution operators (OSD), tariff groups G and default 2026 rates. Pure Python.

All rates are NETTO; VAT is added by the calculator. Every rate and every zone hour
can be changed by the user, the values below are only defaults.

Sources:
- TAURON Dystrybucja: "Wyciąg z Taryfy TAURON Dystrybucja S.A. na rok 2026 dla odbiorców
  grup G", rates valid 01.02.2026–31.12.2026 (cross-checked with "Stawki brutto w grupach G").
- ENEA Operator: "Wyciąg z Taryfy ENEA Operator Sp. z o.o. … 01.01.2026–31.12.2026".
  G12 night hours are set by the operator per meter (8 h of 22–7 and 2 h of 13–17);
  the default below is the most common 13–15 + 22–6.
- Energa-Operator: "Wyciąg z Taryfy Energa-Operator S.A. … 2026" (update 01.02.2026).
- PGE Dystrybucja: zone hours from "Taryfa … PGE Dystrybucja S.A. na rok 2026" (pkt 2);
  rates NOT verified against the tariff (secondary sources) – check them on the invoice.
- Stoen Operator: zone hours from "Taryfa Stoen Operator 2026" (pkt 2.2); rates NOT
  verified – check them on the invoice.
- Energy (fixed price): Taryfa TAURON Sprzedaż sp. z o.o., decyzja Prezesa URE
  DRE.WRE.4211.53.10.2025 z 17.12.2025, valid 01.01.2026–31.12.2026. Tariff prices exclude
  excise tax (akcyza 5 zł/MWh), added separately. The seller is independent of the
  operator, so these are defaults for every operator.
- Dynamic energy: Cennik "Prąd z Ceną Dynamiczną" (TAURON Sprzedaż) od 01.04.2026:
  hourly RDN Fixing I + składnik cenotwórczy SC 0,0892 zł/kWh netto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Callable

from .holidays_pl import is_day_off, is_holiday

VAT = 0.23
QUALITY_FEE = 0.0331      # opłata jakościowa, zł/kWh netto
OZE_FEE = 0.0073          # opłata OZE 7,30 zł/MWh
COGENERATION_FEE = 0.0030  # opłata kogeneracyjna 3,00 zł/MWh
EXCISE = 0.005            # akcyza 5 zł/MWh
DYNAMIC_MARGIN = 0.0892   # Tauron Ceny Dynamiczne, SC netto
TRADE_FEE = 0.0           # opłata handlowa zł/m-c netto (brak w taryfie 2026)

# Opłata abonamentowa zł/m-c netto, by billing period (months) – TAURON Dystrybucja
SUBSCRIPTION_FEE = {1: 4.56, 2: 2.28, 6: 0.76, 12: 0.38}
# Opłata mocowa zł/m-c netto, by yearly consumption bracket (national, PSE)
CAPACITY_FEE = {"lt500": 4.29, "500_1200": 10.31, "1200_2800": 17.18, "gt2800": 24.05}

SUMMER_MONTHS = range(4, 10)  # 1 April – 30 September

Ranges = tuple[tuple[int, int], ...]

DAYOFF_WEEKEND = "weekend"  # Saturday, Sunday and statutory holidays
DAYOFF_SUNDAY = "sunday"    # Sunday and statutory holidays (Saturday is a normal day)


def _in(h: int, ranges: Ranges) -> bool:
    """h in any [start, end) range; ranges may wrap midnight (22, 6)."""
    for s, e in ranges:
        if s < e:
            if s <= h < e:
                return True
        elif h >= s or h < e:
            return True
    return False


_RANGE_RE = re.compile(r"^\s*(\d{1,2})(?::00)?\s*[-–]\s*(\d{1,2})(?::00)?\s*$")


def parse_ranges(text: str) -> Ranges:
    """'13-15, 22-6' → ((13, 15), (22, 6)). Full hours only; 24 means midnight."""
    out: list[tuple[int, int]] = []
    for part in (text or "").replace(";", ",").split(","):
        if not part.strip():
            continue
        m = _RANGE_RE.match(part)
        if not m:
            raise ValueError(f"bad range: {part!r}")
        s, e = int(m[1]), int(m[2]) % 24 if int(m[2]) == 24 else int(m[2])
        if not (0 <= s <= 23 and 0 <= e <= 23) or s == e:
            raise ValueError(f"bad range: {part!r}")
        out.append((s, e))
    return tuple(out)


def format_ranges(ranges: Ranges) -> str:
    return ", ".join(f"{s}-{e}" for s, e in ranges)


@dataclass(frozen=True)
class Schedule:
    """Zone hours of a group. The first zone whose hours match wins; others → default.

    winter: zone hours all year, or 1 Oct – 31 Mar when summer is set.
    summer: zone hours 1 Apr – 30 Sep (None = same as winter); per zone, a missing
            zone also falls back to its winter hours.
    dayoff_zone: zone for the whole day on days off (None = days off are normal days).
    """

    default: str
    winter: dict[str, Ranges]
    summer: dict[str, Ranges] | None = None
    dayoff_zone: str | None = None
    dayoff: str = DAYOFF_WEEKEND

    def is_off(self, d: date) -> bool:
        if self.dayoff == DAYOFF_SUNDAY:
            return d.weekday() == 6 or is_holiday(d)
        return is_day_off(d)

    def zone(self, dt: datetime) -> str:
        if self.dayoff_zone and self.is_off(dt.date()):
            return self.dayoff_zone
        table = dict(self.winter)
        if self.summer is not None and dt.month in SUMMER_MONTHS:
            table.update(self.summer)
        for z, r in table.items():
            if _in(dt.hour, r):
                return z
        return self.default

    @property
    def editable_zones(self) -> tuple[str, ...]:
        return tuple(self.winter)

    def seasonal(self) -> bool:
        return self.summer is not None


@dataclass(frozen=True)
class TariffGroup:
    key: str
    energy_zones: tuple[str, ...]           # zones priced by the seller
    dist_rates: dict[str, float]            # distribution variable rates netto per rate key
    energy_rates: dict[str, float]          # seller fixed prices netto per energy zone
    schedule: Schedule | None = None        # editable zone hours
    classify_fn: Callable[[datetime], tuple[str, str]] | None = None  # fixed special cases
    fixed_network: tuple[float, float] = (7.38, 10.86)  # składnik stały 1f / 3f, zł/m-c netto
    notes: tuple[str, ...] = field(default_factory=tuple)

    def classify(self, dt: datetime, schedule: Schedule | None = None) -> tuple[str, str]:
        """local dt → (energy zone, distribution rate key)."""
        if self.classify_fn is not None:
            return self.classify_fn(dt)
        sch = schedule or self.schedule
        if sch is None:
            z = self.energy_zones[0]
        else:
            z = sch.zone(dt)
        return z, z


@dataclass(frozen=True)
class Operator:
    key: str
    name: str                               # default operator (OSD) name
    seller: str                             # default seller name
    groups: dict[str, TariffGroup]
    subscription: dict[int, float] = field(default_factory=lambda: dict(SUBSCRIPTION_FEE))
    quality_fee: float = QUALITY_FEE
    verified: bool = True                   # rates checked against the 2026 tariff


# ---------- special classifier (TAURON G13s: season × day type × zone rates) ----------

def _g13s(dt: datetime) -> tuple[str, str]:
    summer = dt.month in SUMMER_MONTHS
    if _in(dt.hour, ((21, 7),)):
        z = "night"
    elif summer:
        z = "day_offpeak" if _in(dt.hour, ((9, 17),)) else "day_peak"
    else:
        z = "day_offpeak" if _in(dt.hour, ((10, 15),)) else "day_peak"
    season = "summer" if summer else "winter"
    daytype = "dayoff" if is_day_off(dt.date()) else "workday"
    return z, f"{season}_{daytype}_{z}"


G13S_DIST = {
    "summer_workday_day_offpeak": 0.1000, "summer_workday_day_peak": 0.2842, "summer_workday_night": 0.1094,
    "summer_dayoff_day_offpeak": 0.0400, "summer_dayoff_day_peak": 0.1176, "summer_dayoff_night": 0.1094,
    "winter_workday_day_offpeak": 0.1999, "winter_workday_day_peak": 0.3332, "winter_workday_night": 0.1094,
    "winter_dayoff_day_offpeak": 0.1200, "winter_dayoff_day_peak": 0.1960, "winter_dayoff_night": 0.1094,
}

# Default seller prices (TAURON Sprzedaż 2026), per group
E_G11 = {"allday": 0.4970}
E_G12 = {"day": 0.5430, "night": 0.4130}
E_G12W = {"peak": 0.6220, "offpeak": 0.4130}
E_FLAT2 = {"day": 0.4970, "night": 0.4970}
E_FLAT2W = {"peak": 0.4970, "offpeak": 0.4970}

# ---------- schedules ----------

S_G12 = Schedule(default="day", winter={"night": ((13, 15), (22, 6))})
S_G12W = Schedule(default="peak", winter={"offpeak": ((13, 15), (22, 6))}, dayoff_zone="offpeak")
S_G12AS = Schedule(default="day", winter={"night": ((22, 6),)})
S_G13 = Schedule(
    default="other",
    winter={"morning_peak": ((7, 13),), "afternoon_peak": ((16, 21),)},
    summer={"morning_peak": ((7, 13),), "afternoon_peak": ((19, 22),)},
    dayoff_zone="other",
)


def _g(key, zones, dist, energy, schedule=None, **kw) -> TariffGroup:
    return TariffGroup(key=key, energy_zones=zones, dist_rates=dist, energy_rates=dict(energy),
                       schedule=schedule, **kw)


TAURON_GROUPS: dict[str, TariffGroup] = {
    "G11": _g("G11", ("allday",), {"allday": 0.2464}, E_G11),
    "G12": _g("G12", ("day", "night"), {"day": 0.2841, "night": 0.0558}, E_G12, S_G12),
    "G12w": _g("G12w", ("peak", "offpeak"), {"peak": 0.3298, "offpeak": 0.0512}, {"peak": 0.6220, "offpeak": 0.4130}, S_G12W),
    # Night rate 0,0246 applies only to night volume above the same period of the
    # previous year; 0,2464 is the conservative default (volume not exceeding).
    "G12as": _g("G12as", ("day", "night"), {"day": 0.2464, "night": 0.2464}, E_FLAT2, S_G12AS,
                fixed_network=(14.76, 21.72),
                notes=("night_excess_rate_0.0246", "energy_rates_not_in_seller_tariff")),
    "G13": _g("G13", ("morning_peak", "afternoon_peak", "other"),
              {"morning_peak": 0.2203, "afternoon_peak": 0.3898, "other": 0.0392},
              {"morning_peak": 0.4668, "afternoon_peak": 0.7780, "other": 0.4210}, S_G13),
    "G13s": _g("G13s", ("day_offpeak", "day_peak", "night"), dict(G13S_DIST),
               {"day_offpeak": 0.4970, "day_peak": 0.4970, "night": 0.4970},
               classify_fn=_g13s, notes=("energy_rates_not_in_seller_tariff",)),
}

ENEA_GROUPS: dict[str, TariffGroup] = {
    "G11": _g("G11", ("allday",), {"allday": 0.2456}, E_G11, fixed_network=(7.45, 10.41)),
    "G12": _g("G12", ("day", "night"), {"day": 0.2779, "night": 0.0913}, E_G12, S_G12,
              fixed_network=(9.59, 14.56), notes=("night_hours_set_by_operator",)),
    "G12w": _g("G12w", ("peak", "offpeak"), {"peak": 0.2702, "offpeak": 0.0813}, E_G12W,
               Schedule(default="offpeak", winter={"peak": ((6, 21),)}, dayoff_zone="offpeak"),
               fixed_network=(16.85, 26.23)),
    "G12as": _g("G12as", ("day", "night"), {"day": 0.2456, "night": 0.2456}, E_FLAT2, S_G12AS,
                fixed_network=(14.90, 20.82), notes=("night_excess_rate_0.0246",)),
}

ENERGA_GROUPS: dict[str, TariffGroup] = {
    "G11": _g("G11", ("allday",), {"allday": 0.3485}, E_G11, fixed_network=(7.83, 11.77)),
    "G12": _g("G12", ("day", "night"), {"day": 0.3844, "night": 0.0827}, E_G12, S_G12,
              fixed_network=(14.35, 20.17)),
    "G12w": _g("G12w", ("peak", "offpeak"), {"peak": 0.4017, "offpeak": 0.0851}, E_G12W, S_G12W,
               fixed_network=(14.35, 20.17)),
    "G12r": _g("G12r", ("peak", "offpeak"), {"peak": 0.3640, "offpeak": 0.0882}, E_FLAT2W,
               Schedule(default="peak", winter={"offpeak": ((13, 16), (22, 7))}),
               fixed_network=(14.35, 20.17), notes=("energy_rates_not_in_seller_tariff",)),
    "G12as": _g("G12as", ("day", "night"), {"day": 0.3485, "night": 0.3485}, E_FLAT2, S_G12AS,
                fixed_network=(15.66, 23.54), notes=("night_excess_rate_0.0337",)),
}

PGE_G12 = Schedule(default="day", winter={"night": ((13, 15), (22, 6))},
                   summer={"night": ((15, 17), (22, 6))})
PGE_GROUPS: dict[str, TariffGroup] = {
    "G11": _g("G11", ("allday",), {"allday": 0.3469}, E_G11, fixed_network=(5.50, 9.98)),
    "G12": _g("G12", ("day", "night"), {"day": 0.4014, "night": 0.0765}, E_G12, PGE_G12,
              fixed_network=(5.50, 9.98)),
    "G12w": _g("G12w", ("peak", "offpeak"), {"peak": 0.4014, "offpeak": 0.0765}, E_G12W,
               Schedule(default="peak", winter={"offpeak": ((13, 15), (22, 6))},
                        summer={"offpeak": ((15, 17), (22, 6))}, dayoff_zone="offpeak"),
               fixed_network=(5.50, 9.98)),
    "G12n": _g("G12n", ("day", "night"), {"day": 0.4014, "night": 0.0765}, E_FLAT2,
               Schedule(default="day", winter={"night": ((1, 5),)}, dayoff_zone="night",
                        dayoff=DAYOFF_SUNDAY),
               fixed_network=(5.50, 9.98), notes=("energy_rates_not_in_seller_tariff",)),
    "G12as": _g("G12as", ("day", "night"), {"day": 0.3469, "night": 0.3469}, E_FLAT2, S_G12AS,
                fixed_network=(5.50, 9.98)),
}

STOEN_GROUPS: dict[str, TariffGroup] = {
    "G11": _g("G11", ("allday",), {"allday": 0.2545}, E_G11, fixed_network=(11.46, 11.46)),
    "G12": _g("G12", ("day", "night"), {"day": 0.2545, "night": 0.0555}, E_G12, S_G12,
              fixed_network=(11.46, 11.46)),
    "G12w": _g("G12w", ("peak", "offpeak"), {"peak": 0.2545, "offpeak": 0.0555}, E_G12W,
               Schedule(default="offpeak", winter={"peak": ((6, 22),)}, dayoff_zone="offpeak"),
               fixed_network=(11.46, 11.46)),
    "G12as": _g("G12as", ("day", "night"), {"day": 0.2545, "night": 0.2545}, E_FLAT2, S_G12AS,
                fixed_network=(11.46, 11.46)),
}

OTHER_GROUPS: dict[str, TariffGroup] = {
    k: TAURON_GROUPS[k] for k in ("G11", "G12", "G12w", "G12as", "G13")
}

OPERATORS: dict[str, Operator] = {
    "tauron": Operator("tauron", "TAURON Dystrybucja", "TAURON Sprzedaż", TAURON_GROUPS),
    "enea": Operator("enea", "ENEA Operator", "", ENEA_GROUPS,
                     subscription={1: 3.84, 2: 1.92, 6: 0.64, 12: 0.32}, quality_fee=0.0332),
    "energa": Operator("energa", "Energa-Operator", "", ENERGA_GROUPS,
                       subscription={1: 4.64, 2: 2.32, 6: 2.32, 12: 2.32}, quality_fee=0.0332),
    "pge": Operator("pge", "PGE Dystrybucja", "", PGE_GROUPS,
                    subscription={1: 4.50, 2: 2.25, 6: 0.75, 12: 0.75}, verified=False),
    "stoen": Operator("stoen", "Stoen Operator", "", STOEN_GROUPS, verified=False),
    "other": Operator("other", "", "", OTHER_GROUPS, verified=False),
}
DEFAULT_OPERATOR = "tauron"

# Backwards compatibility: TAURON groups
GROUPS = TAURON_GROUPS
ALL_GROUP_KEYS: tuple[str, ...] = tuple(dict.fromkeys(k for o in OPERATORS.values() for k in o.groups))


def operator(key: str | None) -> Operator:
    return OPERATORS.get(key or DEFAULT_OPERATOR, OPERATORS[DEFAULT_OPERATOR])


def group(op: str | None, key: str) -> TariffGroup:
    o = operator(op)
    return o.groups.get(key) or OPERATORS[DEFAULT_OPERATOR].groups[key]


def schedule_from_options(base: Schedule | None, o: dict) -> Schedule | None:
    """Apply user zone hours (hours_<zone>, hours_<zone>_summer) over the default schedule."""
    if base is None:
        return None
    winter = {z: parse_ranges(o[f"hours_{z}"]) if f"hours_{z}" in o else r for z, r in base.winter.items()}
    summer = None
    if base.summer is not None:
        summer = {}
        for z in base.winter:
            key = f"hours_{z}_summer"
            if key in o:
                txt = str(o[key]).strip()
                summer[z] = parse_ranges(txt) if txt else winter[z]
            else:
                summer[z] = base.summer.get(z, winter[z])
    return replace(base, winter=winter, summer=summer)


ZONE_NAMES_PL = {
    "allday": "całodobowa", "day": "dzienna", "night": "nocna",
    "peak": "szczytowa", "offpeak": "pozaszczytowa",
    "morning_peak": "szczyt przedpołudniowy", "afternoon_peak": "szczyt popołudniowy",
    "other": "pozostałe godziny", "day_offpeak": "dzienna pozaszczytowa", "day_peak": "dzienna szczytowa",
}
