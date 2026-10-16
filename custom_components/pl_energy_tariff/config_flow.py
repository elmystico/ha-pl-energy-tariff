"""Config flow: name + operator → tariff group → energy price → distribution → zone hours."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from . import tariffs as T
from .const import (
    CONF_BILLING,
    CONF_CAPACITY,
    CONF_COGEN,
    CONF_ENERGY_MODE,
    CONF_EXCISE,
    CONF_GROUP,
    CONF_MARGIN,
    CONF_OPERATOR,
    CONF_OPERATOR_NAME,
    CONF_OZE,
    CONF_PHASES,
    CONF_PRICE_ENTITY,
    CONF_QUALITY,
    CONF_SELLER_NAME,
    CONF_SOURCE_VAT,
    CONF_TITLE,
    CONF_TRADE_FEE,
    CONF_VAT,
    DEFAULT_PRICE_ENTITY,
    DIST_PREFIX,
    DOMAIN,
    ENERGY_PREFIX,
    HOURS_PREFIX,
    INDICATOR_DEFAULTS,
    SUMMER_SUFFIX,
)
from .pricing import MODE_DYNAMIC, MODE_FIXED
from .source import parse_points

# Selector option keys must be lowercase (hassfest); labels come from translations.
GROUP_OPTIONS = {k.lower(): k for k in T.ALL_GROUP_KEYS}
OPERATOR_SHORT = {"tauron": "", "enea": "Enea", "energa": "Energa", "pge": "PGE", "stoen": "Stoen", "other": ""}


def _num(lo: float = 0, hi: float = 100) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=lo, max=hi, step="any", mode=selector.NumberSelectorMode.BOX)
    )


def _text() -> selector.TextSelector:
    return selector.TextSelector()


def _select(options: list[str], key: str) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(options=options, translation_key=key,
                                      mode=selector.SelectSelectorMode.DROPDOWN)
    )


def _pl(hass: HomeAssistant) -> bool:
    return (hass.config.language or "en").lower().startswith("pl")


def energy_schema(op: str, group: str, mode: str, cur: dict[str, Any]) -> vol.Schema:
    g = T.group(op, group)
    if mode == MODE_DYNAMIC:
        return vol.Schema({
            vol.Required(CONF_PRICE_ENTITY, default=cur.get(CONF_PRICE_ENTITY, DEFAULT_PRICE_ENTITY)):
                selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Required(CONF_SOURCE_VAT, default=cur.get(CONF_SOURCE_VAT, False)): selector.BooleanSelector(),
            vol.Required(CONF_MARGIN, default=cur.get(CONF_MARGIN, T.DYNAMIC_MARGIN)): _num(-10, 10),
            vol.Required(CONF_EXCISE, default=cur.get(CONF_EXCISE, 0.0)): _num(0, 1),
        })
    fields: dict[Any, Any] = {}
    for zone in g.energy_zones:
        fields[vol.Required(ENERGY_PREFIX + zone, default=cur.get(ENERGY_PREFIX + zone, g.energy_rates[zone]))] = _num(-10, 10)
    fields[vol.Required(CONF_EXCISE, default=cur.get(CONF_EXCISE, T.EXCISE))] = _num(0, 1)
    fields[vol.Required(CONF_TRADE_FEE, default=cur.get(CONF_TRADE_FEE, T.TRADE_FEE))] = _num(0, 1000)
    return vol.Schema(fields)


def distribution_schema(op: str, group: str, cur: dict[str, Any]) -> vol.Schema:
    o = T.operator(op)
    g = T.group(op, group)
    fields: dict[Any, Any] = {
        vol.Optional(CONF_OPERATOR_NAME, description={"suggested_value": cur.get(CONF_OPERATOR_NAME) or o.name}): _text(),
        vol.Optional(CONF_SELLER_NAME, description={"suggested_value": cur.get(CONF_SELLER_NAME) or o.seller}): _text(),
    }
    for key, rate in g.dist_rates.items():
        fields[vol.Required(DIST_PREFIX + key, default=cur.get(DIST_PREFIX + key, rate))] = _num(-10, 10)
    fields.update({
        vol.Required(CONF_QUALITY, default=cur.get(CONF_QUALITY, o.quality_fee)): _num(0, 1),
        vol.Required(CONF_OZE, default=cur.get(CONF_OZE, T.OZE_FEE)): _num(0, 1),
        vol.Required(CONF_COGEN, default=cur.get(CONF_COGEN, T.COGENERATION_FEE)): _num(0, 1),
        vol.Required(CONF_VAT, default=cur.get(CONF_VAT, T.VAT)): _num(0, 1),
        vol.Required(CONF_PHASES, default=str(cur.get(CONF_PHASES, 1))): _select(["1", "3"], "phases"),
        vol.Required(CONF_BILLING, default=str(cur.get(CONF_BILLING, 1))): _select(["1", "2", "6", "12"], "billing"),
        vol.Required(CONF_CAPACITY, default=cur.get(CONF_CAPACITY, "1200_2800")): _select(list(T.CAPACITY_FEE), "capacity"),
    })
    return vol.Schema(fields)


def zones_schema(op: str, group: str, cur: dict[str, Any]) -> vol.Schema | None:
    sch = T.group(op, group).schedule
    if sch is None:
        return None
    fields: dict[Any, Any] = {}
    for z, r in sch.winter.items():
        key = HOURS_PREFIX + z
        fields[vol.Optional(key, default=str(cur.get(key, T.format_ranges(r))))] = _text()
        if sch.summer is not None:
            skey = key + SUMMER_SUFFIX
            fields[vol.Optional(skey, default=str(cur.get(skey, T.format_ranges(sch.summer.get(z, r)))))] = _text()
    return vol.Schema(fields)


def validate_zones(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    for k, v in user_input.items():
        if not k.startswith(HOURS_PREFIX):
            continue
        try:
            r = T.parse_ranges(str(v))
        except ValueError:
            errors[k] = "invalid_hours"
            continue
        if not r and not k.endswith(SUMMER_SUFFIX):
            errors[k] = "empty_hours"
    return errors


def zones_placeholders(hass: HomeAssistant, op: str, group: str) -> dict[str, str]:
    sch = T.group(op, group).schedule
    pl = _pl(hass)
    default = sch.default if sch else ""
    zone = T.ZONE_NAMES_PL.get(default, default) if pl else default
    if sch and sch.dayoff_zone:
        dz = T.ZONE_NAMES_PL.get(sch.dayoff_zone, sch.dayoff_zone) if pl else sch.dayoff_zone
        days = ("niedziele i święta" if pl else "Sundays and holidays") if sch.dayoff == T.DAYOFF_SUNDAY \
            else ("soboty, niedziele i święta" if pl else "Saturdays, Sundays and holidays")
        dayoff = (f"{days}: cała doba w strefie „{dz}”." if pl else f"{days}: all day in zone “{dz}”.")
    else:
        dayoff = "Dni wolne liczone jak robocze." if pl else "Days off are treated as workdays."
    return {"group": group, "default_zone": zone, "dayoff": dayoff}


def dist_placeholders(hass: HomeAssistant, op: str, group: str) -> dict[str, str]:
    o = T.operator(op)
    pl = _pl(hass)
    if o.key == "other":
        note = ("Domyślne stawki to TAURON 2026 – wpisz stawki swojego operatora z faktury lub taryfy."
                if pl else "Defaults are TAURON 2026 rates – enter your operator's rates from the invoice.")
    elif not o.verified:
        note = (f"Uwaga: domyślne stawki {o.name} pochodzą ze źródeł pośrednich i nie zostały sprawdzone z taryfą – porównaj je z fakturą."
                if pl else f"Note: the {o.name} defaults come from secondary sources and were not checked against the tariff – compare with your invoice.")
    else:
        note = (f"Domyślne stawki: taryfa {o.name} na 2026 r., netto." if pl
                else f"Defaults: {o.name} 2026 tariff, net.")
    extra = []
    for n in T.group(op, group).notes:
        if n.startswith("night_excess_rate_"):
            rate = n.rsplit("_", 1)[1].replace(".", ",") if pl else n.rsplit("_", 1)[1]
            extra.append(f"Stawka nocna {rate} dotyczy tylko nadwyżki zużycia nocnego ponad analogiczny okres poprzedniego roku."
                         if pl else f"Night rate {rate} applies only to night volume above the same period of the previous year.")
    return {"group": group, "operator": o.name or ("inny operator" if pl else "other operator"),
            "rates_note": " ".join([note, *extra])}


INDICATOR_RANGES = {
    "window_hours": (2, 48), "cheap_fraction": (0.05, 0.5), "extreme_fraction": (0.02, 0.5),
    "reference_days": (1, 60), "charge_very_cheap": (0, 100), "charge_cheap": (0, 100),
    "charge_average": (0, 100), "charge_expensive": (0, 100),
}


def indicator_schema(cur: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required(k, default=cur.get(k, d)): _num(*INDICATOR_RANGES[k]) for k, d in INDICATOR_DEFAULTS.items()
    })


def validate_price_entity(hass: HomeAssistant, entity_id: str, includes_vat: bool) -> str | None:
    st = hass.states.get(entity_id)
    if st is None:
        return "entity_not_found"
    try:
        pts = parse_points(dict(st.attributes), st.attributes.get(ATTR_UNIT_OF_MEASUREMENT), includes_vat)
    except ValueError:
        return "unsupported_unit"
    return None if pts else "no_price_list"


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    out = dict(user_input)
    for k in (CONF_PHASES, CONF_BILLING):
        if k in out:
            out[k] = int(out[k])
    for k in (CONF_OPERATOR_NAME, CONF_SELLER_NAME):
        out[k] = str(out.get(k) or "").strip() or None   # empty → operator preset
    return out


def _clean_zones(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalise '13:00 - 15:00;22-6' → '13-15, 22-6'."""
    return {k: T.format_ranges(T.parse_ranges(str(v))) for k, v in user_input.items()}


def default_title(op: str, group: str, mode: str) -> str:
    label = "dynamiczna" if mode == MODE_DYNAMIC else "stała"
    short = OPERATOR_SHORT.get(op, "")
    return " ".join(x for x in ("Taryfa", short, group, label) if x)


class TariffConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = {}
        self._title: str = ""

    @property
    def _op(self) -> str:
        return self._data[CONF_OPERATOR]

    @property
    def _group(self) -> str:
        return self._data[CONF_GROUP]

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._title = str(user_input.get(CONF_TITLE) or "").strip()
            self._data = {CONF_OPERATOR: user_input[CONF_OPERATOR], CONF_ENERGY_MODE: user_input[CONF_ENERGY_MODE]}
            return await self.async_step_group()
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Optional(CONF_TITLE): _text(),
            vol.Required(CONF_OPERATOR, default=T.DEFAULT_OPERATOR): _select(list(T.OPERATORS), "operator"),
            vol.Required(CONF_ENERGY_MODE, default=MODE_DYNAMIC): _select([MODE_DYNAMIC, MODE_FIXED], "energy_mode"),
        }))

    async def async_step_group(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        groups = list(T.operator(self._op).groups)
        if user_input is not None:
            self._data[CONF_GROUP] = GROUP_OPTIONS.get(user_input[CONF_GROUP], user_input[CONF_GROUP])
            return await self.async_step_energy()
        default = "g13" if "G13" in groups else groups[0].lower()
        return self.async_show_form(
            step_id="group",
            data_schema=vol.Schema({vol.Required(CONF_GROUP, default=default): _select([g.lower() for g in groups], "group")}),
            description_placeholders={"operator": T.operator(self._op).name or "—"},
        )

    async def async_step_energy(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        mode = self._data[CONF_ENERGY_MODE]
        errors: dict[str, str] = {}
        if user_input is not None:
            if mode == MODE_DYNAMIC:
                err = validate_price_entity(self.hass, user_input[CONF_PRICE_ENTITY], user_input[CONF_SOURCE_VAT])
                if err:
                    errors[CONF_PRICE_ENTITY] = err
            if not errors:
                self._options.update(user_input)
                return await self.async_step_distribution()
        return self.async_show_form(
            step_id=f"energy_{mode}", data_schema=energy_schema(self._op, self._group, mode, user_input or {}),
            errors=errors,
        )

    async_step_energy_dynamic = async_step_energy
    async_step_energy_fixed = async_step_energy

    async def async_step_distribution(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._options.update(_clean(user_input))
            if T.group(self._op, self._group).schedule is not None:
                return await self.async_step_zones()
            return self._create()
        return self.async_show_form(step_id="distribution", data_schema=distribution_schema(self._op, self._group, {}),
                                    description_placeholders=dist_placeholders(self.hass, self._op, self._group))

    async def async_step_zones(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_zones(user_input)
            if not errors:
                self._options.update(_clean_zones(user_input))
                return self._create()
        return self.async_show_form(step_id="zones", data_schema=zones_schema(self._op, self._group, user_input or {}),
                                    errors=errors,
                                    description_placeholders=zones_placeholders(self.hass, self._op, self._group))

    def _create(self) -> ConfigFlowResult:
        title = self._title or default_title(self._op, self._group, self._data[CONF_ENERGY_MODE])
        return self.async_create_entry(title=title, data=self._data, options=self._options)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TariffOptionsFlow()


class TariffOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._new: dict[str, Any] = {}

    @property
    def _op(self) -> str:
        return self.config_entry.data.get(CONF_OPERATOR, T.DEFAULT_OPERATOR)

    @property
    def _group(self) -> str:
        return self.config_entry.data[CONF_GROUP]

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        mode = self.config_entry.data[CONF_ENERGY_MODE]
        errors: dict[str, str] = {}
        if user_input is not None:
            if mode == MODE_DYNAMIC:
                err = validate_price_entity(self.hass, user_input[CONF_PRICE_ENTITY], user_input[CONF_SOURCE_VAT])
                if err:
                    errors[CONF_PRICE_ENTITY] = err
            if not errors:
                self._new = dict(user_input)
                return await self.async_step_distribution()
        cur = user_input or dict(self.config_entry.options)
        return self.async_show_form(step_id="init", data_schema=energy_schema(self._op, self._group, mode, cur),
                                    errors=errors)

    async def async_step_distribution(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._new.update(_clean(user_input))
            if T.group(self._op, self._group).schedule is not None:
                return await self.async_step_zones()
            return await self.async_step_indicators()
        return self.async_show_form(step_id="distribution",
                                    data_schema=distribution_schema(self._op, self._group, dict(self.config_entry.options)),
                                    description_placeholders=dist_placeholders(self.hass, self._op, self._group))

    async def async_step_zones(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_zones(user_input)
            if not errors:
                self._new.update(_clean_zones(user_input))
                return await self.async_step_indicators()
        cur = user_input or dict(self.config_entry.options)
        return self.async_show_form(step_id="zones", data_schema=zones_schema(self._op, self._group, cur),
                                    errors=errors,
                                    description_placeholders=zones_placeholders(self.hass, self._op, self._group))

    async def async_step_indicators(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options, **self._new, **user_input})
        return self.async_show_form(step_id="indicators", data_schema=indicator_schema(dict(self.config_entry.options)))
