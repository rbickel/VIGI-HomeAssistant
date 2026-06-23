"""Config flow for TP-Link VIGI NVR."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VigiApiError, VigiNvrClient
from .const import CONF_VERIFY_TLS, DEFAULT_PORT, DEFAULT_VERIFY_TLS, DOMAIN


class VigiNvrConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a VIGI NVR config flow."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await self._validate_input(user_input)
            except (aiohttp.ClientError, TimeoutError, VigiApiError):
                errors["base"] = "cannot_connect"
            else:
                unique_id = f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"VIGI NVR {user_input[CONF_HOST]}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                    vol.Optional(CONF_VERIFY_TLS, default=DEFAULT_VERIFY_TLS): bool,
                }
            ),
            errors=errors,
        )

    async def _validate_input(self, user_input: dict[str, Any]) -> None:
        session = async_get_clientsession(self.hass)
        client = VigiNvrClient(
            session=session,
            host=user_input[CONF_HOST],
            port=user_input[CONF_PORT],
            username=user_input[CONF_USERNAME],
            password=user_input[CONF_PASSWORD],
            verify_tls=user_input[CONF_VERIFY_TLS],
        )
        await client.authenticate()
