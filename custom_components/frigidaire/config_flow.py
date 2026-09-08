"""Config flow for frigidaire integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

import frigidaire

from .const import (
    BINARY_SENSOR_OPTIONS,
    CONF_COMPRESSOR_ESTIMATE,
    CONF_COMPRESSOR_OFF_DELAY,
    CONF_COOL_HYSTERESIS,
    DEFAULT_COMPRESSOR_OFF_DELAY,
    DEFAULT_COOL_HYSTERESIS,
    DOMAIN,
    SENSOR_OPTIONS,
    SWITCH_OPTIONS,
)
from .coordinator import FrigidaireConfigEntry
from .session import session_store

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({"username": str, "password": str})
STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required("password"): str})

ALL_OPTIONS = {**SWITCH_OPTIONS, **BINARY_SENSOR_OPTIONS, **SENSOR_OPTIONS}


def _device_schema(current: dict, appliance: frigidaire.Appliance) -> vol.Schema:
    fields: dict = {vol.Optional(key, default=current.get(key, False)): bool for key in ALL_OPTIONS}

    if appliance.destination is frigidaire.Destination.AIR_CONDITIONER:
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


async def _login(hass: HomeAssistant, username: str, password: str, entry_id: str | None) -> list[frigidaire.Appliance]:
    """Verify the credentials with a full login and return the account's appliances."""

    def connect() -> list[frigidaire.Appliance]:
        client = frigidaire.Frigidaire(username, password, timeout=60)
        # Save the session so setup reuses it instead of minting a second one: Frigidaire
        # caps active sessions per account.
        session_store(hass.config.path(), entry_id).save(client.session_key, client.regional_base_url)
        return client.get_appliances()

    try:
        return await hass.async_add_executor_job(connect)
    except frigidaire.AuthenticationError as err:
        raise InvalidAuth from err
    except frigidaire.FrigidaireException as err:
        raise CannotConnect from err


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for frigidaire."""

    VERSION = 1

    def __init__(self) -> None:
        self._user_input: dict[str, Any] = {}
        self._pending_appliances: list[frigidaire.Appliance] = []
        self._options: dict[str, dict[str, Any]] = {}

    @staticmethod
    def async_get_options_flow(config_entry: FrigidaireConfigEntry) -> config_entries.OptionsFlow:
        return OptionsFlowHandler()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)

        errors = {}

        try:
            appliances = await _login(self.hass, user_input["username"], user_input["password"], entry_id=None)
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
                await self.async_set_unique_id(user_input["username"].lower())
                self._abort_if_unique_id_configured()
                self._user_input = user_input
                self._pending_appliances = list(appliances)
                return await self._async_next_device_step()

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)

    async def _async_next_device_step(self) -> ConfigFlowResult:
        if not self._pending_appliances:
            return self.async_create_entry(title="Frigidaire", data=self._user_input, options=self._options)
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
        """The stored password stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for a new password and reload the entry with it."""
        entry = self._get_reauth_entry()
        errors = {}

        if user_input is not None:
            try:
                await _login(self.hass, entry.data["username"], user_input["password"], entry.entry_id)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates={"password": user_input["password"]})

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={"username": entry.data["username"]},
            errors=errors,
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for the frigidaire integration."""

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


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
