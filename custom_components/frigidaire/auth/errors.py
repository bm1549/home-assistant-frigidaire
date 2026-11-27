"""Errors every sign-in method's validation raises, so the config flow can stay generic."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError


class CannotConnect(HomeAssistantError):
    """The service could not be reached, or failed in a way retrying may fix."""


class InvalidAuth(HomeAssistantError):
    """The credentials were rejected, or the account cannot sign in this way."""


class CredentialsInUse(HomeAssistantError):
    """The credentials are the ones another configured entry is using; validating them would harm it."""
