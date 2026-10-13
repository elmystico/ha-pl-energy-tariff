"""Tariff groups G (TAURON Dystrybucja) and default 2026 rates. Pure Python.

Sources (all rates NETTO, VAT added by the calculator):
- Distribution: "Wyciąg z Taryfy TAURON Dystrybucja S.A. na rok 2026 dla odbiorców grup G",
  rates valid 01.02.2026–31.12.2026 (cross-checked with "Stawki brutto w grupach G na rok 2026").
- Energy (fixed price): Taryfa TAURON Sprzedaż sp. z o.o., decyzja Prezesa URE
  DRE.WRE.4211.53.10.2025 z 17.12.2025, valid 01.01.2026–31.12.2026. Tariff prices exclude
  excise tax (akcyza 5 zł/MWh), added separately.
- Dynamic energy: Cennik "Prąd z Ceną Dynamiczną" (TAURON Sprzedaż) od 01.04.2026:
  hourly RDN Fixing I + składnik cenotwórczy SC 0,0892 zł/kWh netto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .holidays_pl import is_day_off

DSO_TAURON = "tauron"

VAT = 0.23
QUALITY_FEE = 0.0331      # opłata jakościowa, zł/kWh netto
OZE_FEE = 0.0073          # opłata OZE 7,30 zł/MWh
COGENERATION_FEE = 0.0030  # opłata kogeneracyjna 3,00 zł/MWh
EXCISE = 0.005            # akcyza 5 zł/MWh
DYNAMIC_MARGIN = 0.0892   # Tauron Ceny Dynamiczne, SC netto
TRADE_FEE = 0.0           # opłata handlowa zł/m-c netto (brak w taryfie 2026)

# Opłata abonamentowa zł/m-c netto, by billing period (months)
SUBSCRIPTION_FEE = {1: 4.56, 2: 2.28, 6: 0.76, 12: 0.38}
# Opłata mocowa zł/m-c netto, by yearly consumption bracket
CAPACITY_FEE = {"lt500": 4.29, "500_1200": 10.31, "1200_2800": 17.18, "gt2800": 24.05}

SUMMER_MONTHS = range(4, 10)  # 1 April – 30 September


def _in(h: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    """h in any [start, end) range; ranges may wrap midnight (22, 6)."""
    for s, e in ranges:
        if s < e:
            if s <= h < e:
                return True
        elif h >= s or h < e:
            return True
    return False


@dataclass(frozen=True)
class TariffGroup:
    key: str
    energy_zones: tuple[str, ...]           # zones priced by the seller
    dist_rates: dict[str, float]            # distribution variable rates netto per rate key
    energy_rates: dict[str, float]          # seller fixed prices netto per energy zone
    classify: Callable[[datetime], tuple[str, str]]  # local dt -> (energy zone, dist rate key)
    fixed_network: tuple[float, float] = (7.38, 10.86)  # składnik stały 1f / 3f, zł/m-c netto
    notes: tuple[str, ...] = field(default_factory=tuple)


# ---------- classifiers (local wall-clock time) ----------

def _g11(dt: datetime) -> tuple[str, str]:
    return "allday", "allday"


def _g12(dt: datetime) -> tuple[str, str]:
    z = "day" if _in(dt.hour, ((6, 13), (15, 22))) else "night"
    return z, z


def _g12w(dt: datetime) -> tuple[str, str]:
    peak = not is_day_off(dt.date()) and _in(dt.hour, ((6, 13), (15, 22)))
    z = "peak" if peak else "offpeak"
    return z, z


def _g12as(dt: datetime) -> tuple[str, str]:
    z = "day" if _in(dt.hour, ((6, 22),)) else "night"
    return z, z


def _g13(dt: datetime) -> tuple[str, str]:
    if is_day_off(dt.date()):
        z = "other"
    elif _in(dt.hour, ((7, 13),)):
        z = "morning_peak"
    elif dt.month in SUMMER_MONTHS and _in(dt.hour, ((19, 22),)):
        z = "afternoon_peak"
    elif dt.month not in SUMMER_MONTHS and _in(dt.hour, ((16, 21),)):
        z = "afternoon_peak"
    else:
        z = "other"
    return z, z


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

GROUPS: dict[str, TariffGroup] = {
    "G11": TariffGroup(
        key="G11", energy_zones=("allday",),
        dist_rates={"allday": 0.2464}, energy_rates={"allday": 0.4970}, classify=_g11,
    ),
    "G12": TariffGroup(
        key="G12", energy_zones=("day", "night"),
        dist_rates={"day": 0.2841, "night": 0.0558},
        energy_rates={"day": 0.5430, "night": 0.4130}, classify=_g12,
    ),
    "G12w": TariffGroup(
        key="G12w", energy_zones=("peak", "offpeak"),
        dist_rates={"peak": 0.3298, "offpeak": 0.0512},
        energy_rates={"peak": 0.6220, "offpeak": 0.4130}, classify=_g12w,
    ),
    "G12as": TariffGroup(
        key="G12as", energy_zones=("day", "night"),
        # Night rate 0,0246 applies only to night volume above the same period of the
        # previous year; 0,2464 is the conservative default (volume not exceeding).
        dist_rates={"day": 0.2464, "night": 0.2464},
        energy_rates={"day": 0.4970, "night": 0.4970}, classify=_g12as,
        fixed_network=(14.76, 21.72),
        notes=("night_excess_rate_0.0246", "energy_rates_not_in_seller_tariff"),
    ),
    "G13": TariffGroup(
        key="G13", energy_zones=("morning_peak", "afternoon_peak", "other"),
        dist_rates={"morning_peak": 0.2203, "afternoon_peak": 0.3898, "other": 0.0392},
        energy_rates={"morning_peak": 0.4668, "afternoon_peak": 0.7780, "other": 0.4210},
        classify=_g13,
    ),
    "G13s": TariffGroup(
        key="G13s", energy_zones=("day_offpeak", "day_peak", "night"),
        dist_rates=dict(G13S_DIST),
        energy_rates={"day_offpeak": 0.4970, "day_peak": 0.4970, "night": 0.4970},
        classify=_g13s,
        notes=("energy_rates_not_in_seller_tariff",),
    ),
}

ZONE_NAMES_PL = {
    "allday": "całodobowa", "day": "dzienna", "night": "nocna",
    "peak": "szczytowa", "offpeak": "pozaszczytowa",
    "morning_peak": "szczyt przedpołudniowy", "afternoon_peak": "szczyt popołudniowy",
    "other": "pozostałe godziny", "day_offpeak": "dzienna pozaszczytowa", "day_peak": "dzienna szczytowa",
}
