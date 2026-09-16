from __future__ import annotations

import json
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import CONF_DEVICES, CONF_INTERFACE, DEFAULT_DEVICES, DEFAULT_INTERFACE, DOMAIN


def _parse_devices(value: str) -> dict[str, str]:
    """Parse lines of MAC=Name into a normalized mapping."""
    devices: dict[str, str] = {}
    for line in value.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        mac, name = line.split("=", 1)
        mac = mac.strip().upper().replace("-", ":")
        name = name.strip()
        if mac and name:
            devices[mac] = name
    return devices


def _devices_to_text(devices: dict[str, str]) -> str:
    return "\n".join(f"{mac}={name}" for mac, name in sorted(devices.items()))


class WolListenerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Wake-on-LAN Listener."""

    VERSION = 2

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            interface = user_input[CONF_INTERFACE].strip() or DEFAULT_INTERFACE
            devices = _parse_devices(user_input[CONF_DEVICES])

            await self.async_set_unique_id(interface)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"WOL Listener ({interface})",
                data={
                    CONF_INTERFACE: interface,
                    CONF_DEVICES: devices,
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_INTERFACE,
                        default=DEFAULT_INTERFACE,
                    ): str,
                    vol.Optional(
                        CONF_DEVICES,
                        default="",
                    ): str,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return WolListenerOptionsFlow(config_entry)


class WolListenerOptionsFlow(config_entries.OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            interface = user_input[CONF_INTERFACE].strip() or DEFAULT_INTERFACE
            devices = _parse_devices(user_input[CONF_DEVICES])
            return self.async_create_entry(
                title="",
                data={
                    CONF_INTERFACE: interface,
                    CONF_DEVICES: devices,
                },
            )

        current_interface = self.config_entry.options.get(
            CONF_INTERFACE,
            self.config_entry.data.get(CONF_INTERFACE, DEFAULT_INTERFACE),
        )
        current_devices = self.config_entry.options.get(
            CONF_DEVICES,
            self.config_entry.data.get(CONF_DEVICES, DEFAULT_DEVICES),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_INTERFACE,
                        default=current_interface,
                    ): str,
                    vol.Optional(
                        CONF_DEVICES,
                        default=_devices_to_text(current_devices),
                    ): str,
                }
            ),
        )
