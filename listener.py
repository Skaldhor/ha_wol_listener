from __future__ import annotations

import asyncio
import logging
import socket
import struct
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    ATTR_DESTINATION_IP,
    ATTR_DESTINATION_PORT,
    ATTR_DEVICE_NAME,
    ATTR_INTERFACE,
    ATTR_SOURCE_IP,
    ATTR_SOURCE_MAC,
    ATTR_TARGET_MAC,
    ATTR_TIMESTAMP,
    EVENT_WOL_PACKET,
)

_LOGGER = logging.getLogger(__name__)

ETH_HEADER_LEN = 14
IPV4_MIN_HEADER_LEN = 20
UDP_HEADER_LEN = 8
WOL_UDP_PORTS = {7, 9}
MAGIC_PREFIX = b"\xff" * 6


def _format_mac(data: bytes) -> str:
    return ":".join(f"{byte:02X}" for byte in data)


def _normalize_mac(mac: str) -> str:
    return mac.strip().upper().replace("-", ":")


def _magic_packet_target(payload: bytes) -> str | None:
    if len(payload) < 6 + 16 * 6:
        return None

    start = payload.find(MAGIC_PREFIX)
    while start >= 0:
        candidate_start = start + 6
        candidate_end = candidate_start + 6
        if candidate_end > len(payload):
            return None

        mac = payload[candidate_start:candidate_end]
        if mac != b"\x00" * 6:
            repeated = mac * 16
            if payload[candidate_start:candidate_start + len(repeated)] == repeated:
                return _format_mac(mac)

        start = payload.find(MAGIC_PREFIX, start + 1)

    return None


def _parse_ipv4_udp(frame: bytes) -> dict[str, Any] | None:
    if len(frame) < ETH_HEADER_LEN + IPV4_MIN_HEADER_LEN + UDP_HEADER_LEN:
        return None

    if struct.unpack("!H", frame[12:14])[0] != 0x0800:
        return None

    ip_offset = ETH_HEADER_LEN
    first = frame[ip_offset]
    if first >> 4 != 4:
        return None

    ihl = (first & 0x0F) * 4
    if ihl < IPV4_MIN_HEADER_LEN:
        return None

    if len(frame) < ip_offset + ihl + UDP_HEADER_LEN:
        return None

    if frame[ip_offset + 9] != socket.IPPROTO_UDP:
        return None

    source_ip = socket.inet_ntoa(frame[ip_offset + 12:ip_offset + 16])
    destination_ip = socket.inet_ntoa(frame[ip_offset + 16:ip_offset + 20])

    udp_offset = ip_offset + ihl
    source_port, destination_port = struct.unpack(
        "!HH", frame[udp_offset:udp_offset + 4]
    )

    return {
        "source_ip": source_ip,
        "destination_ip": destination_ip,
        "source_port": source_port,
        "destination_port": destination_port,
        "payload": frame[udp_offset + UDP_HEADER_LEN:],
    }


class WolListener:
    """Listen for WOL magic packets on Linux using AF_PACKET."""

    def __init__(
        self,
        hass: HomeAssistant,
        interface: str,
        devices: dict[str, str],
    ) -> None:
        self.hass = hass
        self.interface = interface
        self.devices = {
            _normalize_mac(mac): name
            for mac, name in devices.items()
        }
        self._socket: socket.socket | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        self.last_packet: dict[str, Any] | None = None

    async def async_start(self) -> None:
        if self._task is not None:
            return

        interface = await self.hass.async_add_executor_job(
            self._resolve_interface
        )
        self.interface = interface

        sock = await self.hass.async_add_executor_job(
            self._create_socket, interface
        )

        self._socket = sock
        self._running = True
        self._task = self.hass.async_create_task(
            self._listen_loop(),
            name="ha_wol_listener",
        )

        _LOGGER.info(
            "Listening for WOL magic packets on %s (%d device mappings)",
            interface,
            len(self.devices),
        )

    async def async_stop(self, _event=None) -> None:
        self._running = False

        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._socket is not None:
            sock = self._socket
            self._socket = None
            await self.hass.async_add_executor_job(sock.close)

    def _resolve_interface(self) -> str:
        if self.interface != "auto":
            return self.interface

        candidates = [
            name for _, name in socket.if_nameindex()
            if name != "lo"
        ]
        if not candidates:
            raise OSError("No non-loopback network interface found")

        # Prefer conventional Docker/Linux Ethernet names.
        preferred = [
            name for name in candidates
            if name.startswith(("eth", "en", "br"))
        ]
        return preferred[0] if preferred else candidates[0]

    @staticmethod
    def _create_socket(interface: str) -> socket.socket:
        if not hasattr(socket, "AF_PACKET"):
            raise OSError("This integration requires Linux AF_PACKET")

        sock = socket.socket(
            socket.AF_PACKET,
            socket.SOCK_RAW,
            socket.htons(0x0003),
        )
        sock.bind((interface, 0))
        sock.setblocking(False)
        return sock

    async def _listen_loop(self) -> None:
        assert self._socket is not None
        loop = asyncio.get_running_loop()
        sock = self._socket

        while self._running:
            try:
                frame = await loop.sock_recv(sock, 65535)
            except asyncio.CancelledError:
                raise
            except OSError as err:
                if self._running:
                    _LOGGER.error("Raw socket receive failed: %s", err)
                break

            try:
                self._process_frame(frame)
            except Exception:
                _LOGGER.exception("Error processing network frame")

    def _process_frame(self, frame: bytes) -> None:
        if len(frame) < ETH_HEADER_LEN:
            return

        parsed = _parse_ipv4_udp(frame)
        if parsed is None:
            return

        if (
            parsed["destination_port"] not in WOL_UDP_PORTS
            and parsed["source_port"] not in WOL_UDP_PORTS
        ):
            return

        target_mac = _magic_packet_target(parsed["payload"])
        if target_mac is None:
            return

        source_mac = _format_mac(frame[6:12])
        device_name = self.devices.get(target_mac)

        timestamp = datetime.now(timezone.utc).isoformat()

        data = {
            ATTR_TARGET_MAC: target_mac,
            ATTR_DEVICE_NAME: device_name,
            ATTR_SOURCE_MAC: source_mac,
            ATTR_SOURCE_IP: parsed["source_ip"],
            ATTR_DESTINATION_IP: parsed["destination_ip"],
            ATTR_DESTINATION_PORT: parsed["destination_port"],
            ATTR_INTERFACE: self.interface,
            ATTR_TIMESTAMP: timestamp,
        }

        self.last_packet = data

        _LOGGER.info(
            "WOL detected: %s (%s), source=%s/%s, destination=%s:%s",
            device_name or "unknown device",
            target_mac,
            source_mac,
            parsed["source_ip"],
            parsed["destination_ip"],
            parsed["destination_port"],
        )

        self.hass.bus.async_fire(EVENT_WOL_PACKET, data)
