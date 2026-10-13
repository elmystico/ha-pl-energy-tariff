"""Config flow: tariff group → energy price (dynamic or fixed) → distribution rates."""

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
    CONF_OZE,
    CONF_PHASES,
    CONF_PRICE_ENTITY,
    CONF_QUALITY,
    CONF_SOURCE_VAT,
    CONF_TRADE_FEE,
    CONF_VAT,
    DEFAULT_PRICE_ENTITY,
    DIST_PREFIX,
    DOMAIN,
    ENERGY_PREFIX,
    INDICATOR_DEFAULTS,
)
from .pricing import MODE_DYNAMIC, MODE_FIXED
from .source import parse_points

# Selector option keys must be lowercase (hassfest); labels come from translations.
GROUP_OPTIONS = {k.lower(): k for k in T.GROUPS}


def _num(lo: float = 0, hi: float = 100) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=lo, max=hi, step="any", mode=selector.NumberSelectorMode.BOX)
    )


def _select(options: list[str], key: str) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(options=options, translation_key=key,
                                      mode=selector.SelectSelectorMode.DROPDOWN)
    )


def energy_schema(group: str, mode: str, cur: dict[str, Any]) -> vol.Schema:
    g = T.GROUPS[group]
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


def distribution_schema(group: str, cur: dict[str, Any]) -> vol.Schema:
    g = T.GROUPS[group]
    fields: dict[Any, Any] = {}
    for key, rate in g.dist_rates.items():
        fields[vol.Required(DIST_PREFIX + key, default=cur.get(DIST_PREFIX + key, rate))] = _num(-10, 10)
    fields.update({
        vol.Required(CONF_QUALITY, default=cur.get(CONF_QUALITY, T.QUALITY_FEE)): _num(0, 1),
        vol.Required(CONF_OZE, default=cur.get(CONF_OZE, T.OZE_FEE)): _num(0, 1),
        vol.Required(CONF_COGEN, default=cur.get(CONF_COGEN, T.COGENERATION_FEE)): _num(0, 1),
        vol.Required(CONF_VAT, default=cur.get(CONF_VAT, T.VAT)): _num(0, 1),
        vol.Required(CONF_PHASES, default=str(cur.get(CONF_PHASES, 1))): _select(["1", "3"], "phases"),
        vol.Required(CONF_BILLING, default=str(cur.get(CONF_BILLING, 1))): _select(["1", "2", "6", "12"], "billing"),
        vol.Required(CONF_CAPACITY, default=cur.get(CONF_CAPACITY, "1200_2800")): _select(list(T.CAPACITY_FEE), "capacity"),
    })
    return vol.Schema(fields)


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
    return out


class TariffConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data = dict(user_input)
            self._data[CONF_GROUP] = GROUP_OPTIONS.get(user_input[CONF_GROUP], user_input[CONF_GROUP])
            return await self.async_step_energy()
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required(CONF_GROUP, default="g13"): _select(list(GROUP_OPTIONS), "group"),
            vol.Required(CONF_ENERGY_MODE, default=MODE_DYNAMIC): _select([MODE_DYNAMIC, MODE_FIXED], "energy_mode"),
        }))

    async def async_step_energy(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        group, mode = self._data[CONF_GROUP], self._data[CONF_ENERGY_MODE]
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
            step_id=f"energy_{mode}", data_schema=energy_schema(group, mode, user_input or {}), errors=errors,
        )

    async_step_energy_dynamic = async_step_energy
    async_step_energy_fixed = async_step_energy

    async def async_step_distribution(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        group, mode = self._data[CONF_GROUP], self._data[CONF_ENERGY_MODE]
        if user_input is not None:
            self._options.update(_clean(user_input))
            label = "dynamiczna" if mode == MODE_DYNAMIC else "stała"
            return self.async_create_entry(title=f"Taryfa {group} {label}", data=self._data, options=self._options)
        return self.async_show_form(step_id="distribution", data_schema=distribution_schema(group, {}),
                                    description_placeholders={"group": group})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TariffOptionsFlow()


class TariffOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._new: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        group = self.config_entry.data[CONF_GROUP]
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
        return self.async_show_form(step_id="init", data_schema=energy_schema(group, mode, cur), errors=errors)

    async def async_step_distribution(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        group = self.config_entry.data[CONF_GROUP]
        if user_input is not None:
            self._new.update(_clean(user_input))
            return await self.async_step_indicators()
        return self.async_show_form(step_id="distribution",
                                    data_schema=distribution_schema(group, dict(self.config_entry.options)),
                                    description_placeholders={"group": group})

    async def async_step_indicators(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options, **self._new, **user_input})
        return self.async_show_form(step_id="indicators", data_schema=indicator_schema(dict(self.config_entry.options)))
