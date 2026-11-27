"""Config flow for frigidaire integration."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult

import frigidaire

from .auth import METHODS
from .auth.errors import CannotConnect, InvalidAuth
from .const import (
    BINARY_SENSOR_OPTIONS,
    CONF_COMPRESSOR_ESTIMATE,
    CONF_COMPRESSOR_OFF_DELAY,
    CONF_COOL_HYSTERESIS,
    CONF_HEAT_SUPPORTED,
    DEFAULT_COMPRESSOR_OFF_DELAY,
    DEFAULT_COOL_HYSTERESIS,
    DOMAIN,
    SENSOR_OPTIONS,
    SWITCH_OPTIONS,
)
from .coordinator import FrigidaireConfigEntry

_LOGGER = logging.getLogger(__name__)

ALL_OPTIONS = {**SWITCH_OPTIONS, **BINARY_SENSOR_OPTIONS, **SENSOR_OPTIONS}


def _device_schema(current: dict, appliance: frigidaire.Appliance) -> vol.Schema:
    fields: dict = {vol.Optional(key, default=current.get(key, False)): bool for key in ALL_OPTIONS}

    if appliance.destination is frigidaire.Destination.AIR_CONDITIONER:
        fields[vol.Optional(CONF_HEAT_SUPPORTED, default=current.get(CONF_HEAT_SUPPORTED, False))] = bool
        fields[vol.Optional(CONF_COMPRESSOR_ESTIMATE, default=current.get(CONF_COMPRESSOR_ESTIMATE, False))] = bool
        fields[
            vol.Optional(
                CONF_COOL_HYSTERESIS,
                default=float(current.get(CONF_COOL_HYSTERESIS, DEFAULT_COOL_HYSTERESIS)),
            )
        ] = vol.All(vol.Coerce(float), vol.Range(min=0, max=10))
        fields[
            vol.Optional(
                CONF_COMPRESSOR_OFF_DELAY,
                default=int(current.get(CONF_COMPRESSOR_OFF_DELAY, DEFAULT_COMPRESSOR_OFF_DELAY)),
            )
        ] = vol.All(vol.Coerce(int), vol.Range(min=0, max=3600))

    return vol.Schema(fields)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for frigidaire.

    Generic over ``auth.METHODS``: the first step is a menu with one option per sign-in method,
    each option is a form whose step id is the method's name, and reauth asks again for the
    entry's own method. Entry data is flat: ``auth_method`` plus that method's credentials.
    """

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._pending_appliances: list[frigidaire.Appliance] = []
        self._options: dict[str, dict[str, Any]] = {}

    @staticmethod
    def async_get_options_flow(config_entry: FrigidaireConfigEntry) -> config_entries.OptionsFlow:
        return OptionsFlowHandler()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose how to sign in."""
        return self.async_show_menu(step_id="user", menu_options=list(METHODS))

    async def _async_step_method(self, method: str, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """One sign-in method's form: validate, refuse a configured account, then per-device options."""
        module = METHODS[method]
        errors: dict[str, str] = {}

        if user_input is not None:
            # The method may update this in place during validation.
            data = dict(user_input)
            try:
                email, appliances = await module.async_validate(self.hass, data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                if not appliances:
                    errors["base"] = "no_appliances"
                else:
                    await self.async_set_unique_id(email.lower())
                    self._abort_if_unique_id_configured()
                    self._data = {"auth_method": method, **data}
                    self._pending_appliances = list(appliances)
                    return await self._async_next_device_step()

        return self.async_show_form(
            step_id=method,
            data_schema=module.SCHEMA,
            description_placeholders=module.DESCRIPTION_PLACEHOLDERS,
            errors=errors,
        )

    async def _async_next_device_step(self) -> ConfigFlowResult:
        if not self._pending_appliances:
            return self.async_create_entry(title="Frigidaire", data=self._data, options=self._options)
        return await self.async_step_device()

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the optional-entity checkboxes for the next appliance in the queue."""
        appliance = self._pending_appliances[0]

        if user_input is not None:
            self._options[appliance.appliance_id] = user_input
            self._pending_appliances.pop(0)
            return await self._async_next_device_step()

        return self.async_show_form(
            step_id="device",
            data_schema=_device_schema({}, appliance),
            description_placeholders={"device_name": appliance.nickname},
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """The stored credentials stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask again for the entry's own method's credentials and reload the entry with them.

        The method cannot change here: switching means deleting the entry and adding it again.
        """
        entry = self._get_reauth_entry()
        module = METHODS[entry.data["auth_method"]]
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**entry.data, **user_input}
            try:
                email, _appliances = await module.async_validate(self.hass, data, entry)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                if entry.unique_id is not None and email.lower() != entry.unique_id:
                    return self.async_abort(reason="wrong_account")
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=module.REAUTH_SCHEMA,
            description_placeholders=module.reauth_description_placeholders(entry),
            errors=errors,
        )


def _method_step(method: str) -> Callable[..., Coroutine[Any, Any, ConfigFlowResult]]:
    async def step(self: ConfigFlow, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_method(method, user_input)

    step.__name__ = f"async_step_{method}"
    step.__doc__ = f"The {method} sign-in form."
    return step


for _method in METHODS:
    setattr(ConfigFlow, f"async_step_{_method}", _method_step(_method))


class OptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Handle options for the frigidaire integration; saving reloads the entry so entity selection takes effect."""

    def __init__(self) -> None:
        self._pending_appliances: list[frigidaire.Appliance] = []
        self._options: dict[str, dict[str, Any]] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Load appliances then start per-device steps."""
        coordinator = self.config_entry.runtime_data
        self._pending_appliances = list(coordinator.data.values())
        self._options = dict(self.config_entry.options)
        return await self._async_next_device_step()

    async def _async_next_device_step(self) -> ConfigFlowResult:
        if not self._pending_appliances:
            return self.async_create_entry(title="", data=self._options)
        return await self.async_step_device()

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the optional-entity checkboxes for the next appliance in the queue."""
        appliance = self._pending_appliances[0]
        current = self._options.get(appliance.appliance_id, {})

        if user_input is not None:
            self._options[appliance.appliance_id] = {**current, **user_input}
            self._pending_appliances.pop(0)
            return await self._async_next_device_step()

        return self.async_show_form(
            step_id="device",
            data_schema=_device_schema(current, appliance),
            description_placeholders={"device_name": appliance.nickname},
        )
