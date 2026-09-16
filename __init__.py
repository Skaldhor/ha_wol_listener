from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEVICES,
    CONF_INTERFACE,
    DEFAULT_DEVICES,
    DEFAULT_INTERFACE,
    DOMAIN,
    PLATFORMS,
)
from .listener import WolListener


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    interface = entry.options.get(
        CONF_INTERFACE,
        entry.data.get(CONF_INTERFACE, DEFAULT_INTERFACE),
    )
    devices = entry.options.get(
        CONF_DEVICES,
        entry.data.get(CONF_DEVICES, DEFAULT_DEVICES),
    )

    listener = WolListener(hass, interface, devices)
    await listener.async_start()

    hass.data[DOMAIN][entry.entry_id] = listener

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    listener = hass.data[DOMAIN].pop(entry.entry_id, None)
    if listener is not None:
        await listener.async_stop()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
