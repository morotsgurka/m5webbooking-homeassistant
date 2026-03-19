from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DATA_VALIDATED_CLIENTS, DOMAIN, CONF_ADDRESS, CONF_USERNAME, CONF_PASSWORD
from .m5_client import (
    M5CannotConnectError,
    M5Client,
    M5InvalidAuthError,
    M5InvalidUrlError,
)


class M5ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    def _client_cache_key(user_input: dict) -> tuple[str, str, str]:
        return (
            user_input[CONF_ADDRESS],
            user_input[CONF_USERNAME],
            user_input[CONF_PASSWORD],
        )

    async def _async_validate_input(self, user_input: dict) -> M5Client:
        """Validate URL, login, and protected-page access."""

        client = M5Client(
            address=user_input[CONF_ADDRESS],
            username=user_input[CONF_USERNAME],
            password=user_input[CONF_PASSWORD],
        )
        await self.hass.async_add_executor_job(client.validate_connection)
        return client

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors = {}

        if user_input is not None:
            try:
                client = await self._async_validate_input(user_input)
            except M5InvalidUrlError:
                errors["base"] = "invalid_url"
            except M5InvalidAuthError:
                errors["base"] = "invalid_auth"
            except M5CannotConnectError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                validated_clients = self.hass.data.setdefault(DOMAIN, {}).setdefault(
                    DATA_VALIDATED_CLIENTS, {}
                )
                validated_clients[self._client_cache_key(user_input)] = client
                return self.async_create_entry(
                    title=user_input[CONF_ADDRESS],
                    data=user_input,
                )

        endpoint_default = user_input[CONF_ADDRESS] if user_input else "http://"

        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS, default=endpoint_default): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )