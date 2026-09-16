from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import CONF_INTERFACE, DEFAULT_INTERFACE, DOMAIN


class WolListenerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Wake-on-LAN Listener."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            interface = user_input[CONF_INTERFACE].strip() or DEFAULT_INTERFACE
            return self.async_create_entry(
                title=f"WOL Listener ({interface})",
                data={CONF_INTERFACE: interface},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_INTERFACE,
                        default=DEFAULT_INTERFACE,
                    ): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "example": "auto, eth0, enp3s0, ...",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return WolListenerOptionsFlow(config_entry)


class WolListenerOptionsFlow(config_entries.OptionsFlow):
    """Handle options for the integration."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            interface = user_input[CONF_INTERFACE].strip() or DEFAULT_INTERFACE
            return self.async_create_entry(
                title="",
                data={CONF_INTERFACE: interface},
            )

        current = self.config_entry.options.get(
            CONF_INTERFACE,
            self.config_entry.data.get(CONF_INTERFACE, DEFAULT_INTERFACE),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_INTERFACE,
                        default=current,
                    ): str,
                }
            ),
        )
