from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo

from .const import (
    ATTR_DESTINATION_IP,
    ATTR_DESTINATION_PORT,
    ATTR_INTERFACE,
    ATTR_SOURCE_IP,
    ATTR_SOURCE_MAC,
    ATTR_TARGET_MAC,
    ATTR_TIMESTAMP,
    DOMAIN,
    EVENT_WOL_PACKET,
)
from .listener import WolListener


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    listener: WolListener = hass.data[DOMAIN][entry.entry_id]

    entity = WolLastPacketSensor(listener, entry)

    async_add_entities([entity])

    @callback
    def _event_listener(event: Event) -> None:
        entity.update_from_event(event.data)

    remove_listener = hass.bus.async_listen(
        EVENT_WOL_PACKET,
        _event_listener,
    )
    entry.async_on_unload(remove_listener)


class WolLastPacketSensor(SensorEntity):
    """Sensor containing information about the last WOL packet."""

    _attr_has_entity_name = True
    _attr_name = "Letztes WOL"
    _attr_icon = "mdi:lan-connect"

    def __init__(self, listener: WolListener, entry: ConfigEntry) -> None:
        self._listener = listener
        self._attr_unique_id = f"{entry.entry_id}_last_wol"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Wake-on-LAN Listener",
            manufacturer="Custom",
        )

        self._state: str | None = None
        self._attributes: dict[str, Any] = {}

        if listener.last_packet:
            self.update_from_data(listener.last_packet)

    @property
    def native_value(self) -> str | None:
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attributes

    @callback
    def update_from_event(self, data: dict[str, Any]) -> None:
        self.update_from_data(data)
        self.async_write_ha_state()

    @callback
    def update_from_data(self, data: dict[str, Any]) -> None:
        self._state = data.get(ATTR_TARGET_MAC)

        self._attributes = {
            "target_mac": data.get(ATTR_TARGET_MAC),
            "source_mac": data.get(ATTR_SOURCE_MAC),
            "source_ip": data.get(ATTR_SOURCE_IP),
            "destination_ip": data.get(ATTR_DESTINATION_IP),
            "destination_port": data.get(ATTR_DESTINATION_PORT),
            "interface": data.get(ATTR_INTERFACE),
            "timestamp": data.get(ATTR_TIMESTAMP),
        }
