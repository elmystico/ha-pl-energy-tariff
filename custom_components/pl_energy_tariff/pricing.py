"""Total electricity price per time slot. Pure Python, no HA imports."""

from __future__ import annotations

import calendar

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import tariffs as T

TZ = ZoneInfo("Europe/Warsaw")

MODE_DYNAMIC = "dynamic"
MODE_FIXED = "fixed"


@dataclass(frozen=True)
class SourcePoint:
    """Exchange price for one slot, netto zł/kWh."""

    start: datetime
    end: datetime
    price: float


@dataclass(frozen=True)
class TariffConfig:
    group: str
    energy_mode: str = MODE_DYNAMIC
    operator: str = T.DEFAULT_OPERATOR
    schedule: T.Schedule | None = None  # user zone hours; None = operator default
    operator_name: str | None = None    # shown as the device manufacturer; None = preset
    seller_name: str | None = None
    dist_rates: dict[str, float] = field(default_factory=dict)
    energy_rates: dict[str, float] = field(default_factory=dict)
    margin: float = T.DYNAMIC_MARGIN
    excise: float = 0.0
    quality_fee: float = T.QUALITY_FEE
    oze_fee: float = T.OZE_FEE
    cogeneration_fee: float = T.COGENERATION_FEE
    vat: float = T.VAT
    phases: int = 1
    billing_months: int = 1
    capacity_bracket: str = "1200_2800"
    fixed_network: float | None = None
    trade_fee: float = T.TRADE_FEE

    @property
    def tariff(self) -> T.TariffGroup:
        return T.group(self.operator, self.group)

    @property
    def op(self) -> T.Operator:
        return T.operator(self.operator)

    @property
    def manufacturer(self) -> str | None:
        op = self.operator_name if self.operator_name is not None else self.op.name
        sl = self.seller_name if self.seller_name is not None else self.op.seller
        return " / ".join(x.strip() for x in (op, sl) if x and x.strip()) or None

    def classify(self, local: datetime) -> tuple[str, str]:
        return self.tariff.classify(local, self.schedule)

    def dist_rate(self, key: str) -> float:
        return self.dist_rates.get(key, self.tariff.dist_rates[key])

    def energy_rate(self, zone: str) -> float:
        return self.energy_rates.get(zone, self.tariff.energy_rates[zone])

    @staticmethod
    def defaults(group: str, energy_mode: str = MODE_DYNAMIC,
                 operator: str = T.DEFAULT_OPERATOR) -> "TariffConfig":
        g = T.group(operator, group)
        return TariffConfig(
            group=group,
            energy_mode=energy_mode,
            operator=operator,
            quality_fee=T.operator(operator).quality_fee,
            dist_rates=dict(g.dist_rates),
            energy_rates=dict(g.energy_rates),
            excise=0.0 if energy_mode == MODE_DYNAMIC else T.EXCISE,
        )


@dataclass(frozen=True)
class PricedSlot:
    start: datetime
    end: datetime
    zone: str
    energy: float        # brutto zł/kWh
    distribution: float  # brutto zł/kWh (variable network + quality + OZE + cogeneration)
    total: float         # brutto zł/kWh
    exchange: float | None = None  # netto zł/kWh from source (dynamic only)


def price_slot(cfg: TariffConfig, start: datetime, end: datetime, exchange: float | None) -> PricedSlot:
    local = start.astimezone(TZ)
    zone, rate_key = cfg.classify(local)
    k = 1 + cfg.vat
    if cfg.energy_mode == MODE_DYNAMIC:
        if exchange is None:
            raise ValueError("dynamic tariff needs an exchange price")
        energy_net = exchange + cfg.margin + cfg.excise
    else:
        energy_net = cfg.energy_rate(zone) + cfg.excise
    dist_net = cfg.dist_rate(rate_key) + cfg.quality_fee + cfg.oze_fee + cfg.cogeneration_fee
    return PricedSlot(
        start=start,
        end=end,
        zone=zone,
        energy=round(energy_net * k, 5),
        distribution=round(dist_net * k, 5),
        total=round((energy_net + dist_net) * k, 5),
        exchange=exchange,
    )


def hourly_slots(first_day: date, days: int) -> list[tuple[datetime, datetime]]:
    """Consecutive hours in local time, DST-aware (23/24/25 h days)."""
    start = datetime.combine(first_day, time(0), TZ).astimezone(timezone.utc)
    end = datetime.combine(first_day + timedelta(days=days), time(0), TZ).astimezone(timezone.utc)
    out = []
    t = start
    while t < end:
        out.append((t.astimezone(TZ), (t + timedelta(hours=1)).astimezone(TZ)))
        t += timedelta(hours=1)
    return out


def build_series(cfg: TariffConfig, source: list[SourcePoint] | None, today: date) -> list[PricedSlot]:
    """Priced slots: dynamic → wherever the source has prices; fixed → today and tomorrow."""
    if cfg.energy_mode == MODE_DYNAMIC:
        pts = sorted(source or [], key=lambda p: p.start)
        return [price_slot(cfg, p.start, p.end, p.price) for p in pts]
    return [price_slot(cfg, s, e, None) for s, e in hourly_slots(today, 2)]


def slot_at(series: list[PricedSlot], t: datetime) -> PricedSlot | None:
    for s in series:
        if s.start <= t < s.end:
            return s
    return None


def monthly_fixed(cfg: TariffConfig) -> dict[str, float]:
    """Monthly fixed charges, brutto zł."""
    k = 1 + cfg.vat
    network = cfg.fixed_network if cfg.fixed_network is not None else cfg.tariff.fixed_network[
        0 if cfg.phases == 1 else 1
    ]
    parts = {
        "network_fixed": network,
        "subscription": cfg.op.subscription.get(cfg.billing_months, cfg.op.subscription[1]),
        "capacity": T.CAPACITY_FEE.get(cfg.capacity_bracket, T.CAPACITY_FEE["1200_2800"]),
        "trade": cfg.trade_fee,
    }
    out = {k_: round(v * k, 2) for k_, v in parts.items()}
    out["total"] = round(sum(parts.values()) * k, 2)
    return out


def daily_fixed(cfg: TariffConfig, day: date) -> dict[str, float]:
    """Fixed charges per day, brutto zł/d.

    Fixed components (network fixed, subscription, capacity, trade) are priced per month
    and prorated by days, so one day of month M costs monthly / days_in(M). Summed over
    the days of a month this gives exactly the monthly amount, for every tariff group.
    """
    days = calendar.monthrange(day.year, day.month)[1]
    m = monthly_fixed(cfg)
    out = {k_: round(v / days, 4) for k_, v in m.items()}
    out["days_in_month"] = days
    out.update({f"monthly_{k_}": v for k_, v in m.items()})
    return out
