"""Polish public holidays (dni ustawowo wolne od pracy). Pure Python, no dependencies."""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (Meeus/Jones/Butcher algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=16)
def holidays(year: int) -> frozenset[date]:
    """Statutory days off in Poland (ustawa o dniach wolnych od pracy)."""
    e = easter_sunday(year)
    days = {
        date(year, 1, 1),   # Nowy Rok
        date(year, 1, 6),   # Trzech Króli
        e,                  # Wielkanoc
        e + timedelta(days=1),   # Poniedziałek Wielkanocny
        date(year, 5, 1),   # Święto Pracy
        date(year, 5, 3),   # Święto Konstytucji 3 Maja
        e + timedelta(days=49),  # Zielone Świątki
        e + timedelta(days=60),  # Boże Ciało
        date(year, 8, 15),  # Wniebowzięcie NMP
        date(year, 11, 1),  # Wszystkich Świętych
        date(year, 11, 11), # Święto Niepodległości
        date(year, 12, 25), # Boże Narodzenie
        date(year, 12, 26), # drugi dzień Bożego Narodzenia
    }
    if year >= 2025:
        days.add(date(year, 12, 24))  # Wigilia – dzień wolny od 2025 r.
    return frozenset(days)


def is_holiday(d: date) -> bool:
    return d in holidays(d.year)


def is_day_off(d: date) -> bool:
    """Saturday, Sunday or a statutory holiday."""
    return d.weekday() >= 5 or is_holiday(d)
