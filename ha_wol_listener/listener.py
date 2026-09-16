from __future__ import annotations

import asyncio
import binascii
import ipaddress
import logging
import socket
import struct
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant, callback

from .const import (
    ATTR_DESTINATION_IP,
    ATTR_DESTINATION_PORT,
    ATTR_INTERFACE,
    ATTR_SOURCE_IP,
    ATTR_SOURCE_MAC,
    ATTR_TARGET_MAC,
    ATTR_TIMESTAMP,
    EVENT_WOL_PACKET,
)

_LOGGER = logging.getLogger(__name__)

# Ethernet:
#   dst MAC 6 bytes
#   src MAC 6 bytes
#   EtherType 2 bytes
ETH_HEADER_LEN = 14
ETHERTYPE_IPV4 = 0x0800
ETHERTYPE_IPV6 = 0x86DD

# IPv4 header minimum is 20 bytes.
IPV4_MIN_HEADER_LEN = 20
UDP_HEADER_LEN = 8

WOL_UDP_PORTS = {7, 9}
MAGIC_PREFIX = b"\xff" * 6


def _format_mac(data: bytes) -> str:
    return ":".join(f"{byte:02X}" for byte in data)


def _is_mac(value: bytes) -> bool:
    return len(value) == 6 and value != b"\x00" * 6


def _magic_packet_target(payload: bytes) -> str | None:
    """Return target MAC if payload contains a standard WOL magic packet."""
    if len(payload) < 6 + 16 * 6:
        return None

    # A normal WOL magic packet starts with six FF bytes and then
    # 16 repetitions of the target MAC.
    start = payload.find(MAGIC_PREFIX)
    while start >= 0:
        candidate_start = start + 6
        candidate_end = candidate_start + 6

        if candidate_end > len(payload):
            return None

        mac = payload[candidate_start:candidate_end]
        if not _is_mac(mac):
            start = payload.find(MAGIC_PREFIX, start + 1)
            continue

        repeated = mac * 16
        if payload[candidate_start:candidate_start + len(repeated)] == repeated:
            return _format_mac(mac)

        start = payload.find(MAGIC_PREFIX, start + 1)

    return None


def _parse_ipv4_udp(frame: bytes) -> dict[str, Any] | None:
    """Parse Ethernet + IPv4 + UDP and return relevant fields."""
    if len(frame) < ETH_HEADER_LEN + IPV4_MIN_HEADER_LEN + UDP_HEADER_LEN:
        return None

    ethertype = struct.unpack("!H", frame[12:14])[0]
    if ethertype != ETHERTYPE_IPV4:
        return None

    ip_offset = ETH_HEADER_LEN
    first = frame[ip_offset]
    version = first >> 4
    ihl = (first & 0x0F) * 4

    if version != 4 or ihl < IPV4_MIN_HEADER_LEN:
        return None

    if len(frame) < ip_offset + ihl + UDP_HEADER_LEN:
        return None

    protocol = frame[ip_offset + 9]
    if protocol != socket.IPPROTO_UDP:
        return None

    source_ip = socket.inet_ntoa(frame[ip_offset + 12:ip_offset + 16])
    destination_ip = socket.inet_ntoa(frame[ip_offset + 16:ip_offset + 20])

    udp_offset = ip_offset + ihl
    source_port, destination_port = struct.unpack(
        "!HH", frame[udp_offset:udp_offset + 4]
    )

    payload = frame[udp_offset + UDP_HEADER_LEN:]

    return {
        "source_ip": source_ip,
        "destination_ip": destination_ip,
        "source_port": source_port,
        "destination_port": destination_port,
        "payload": payload,
    }


def _parse_linux_sll(frame: bytes) -> dict[str, Any] | None:
    """Parse Linux cooked capture (SLL/SLL2) if present.

    This is intentionally not used by the main listener. AF_PACKET with
    SOCK_RAW and an interface name normally gives Ethernet frames directly.
    Kept out of the hot path to avoid guessing link-layer formats.
    """
    return None


class WolListener:
    """Listen for Wake-on-LAN magic packets using a Linux AF_PACKET socket."""

    def __init__(self, hass: HomeAssistant, interface: str) -> None:
        self.hass = hass
        self.interface = interface
        self._socket: socket.socket | None = None
        self._task: asyncio.Task | None = None
        self._running = False

        self.last_packet: dict[str, Any] | None = None

    async def async_start(self) -> None:
        """Start listening."""
        if self._task is not None:
            return

        interface = await self.hass.async_add_executor_job(
            self._resolve_interface
        )

        self.interface = interface

        try:
            sock = await self.hass.async_add_executor_job(
                self._create_socket,
                interface,
            )
        except OSError as err:
            _LOGGER.error(
                "Unable to open raw packet socket on %s: %s. "
                "The Home Assistant container needs host networking and "
                "CAP_NET_RAW.",
                interface,
                err,
            )
            raise

        self._socket = sock
        self._running = True
        self._task = self.hass.async_create_task(
            self._listen_loop(),
            name="wol_listener",
        )

        _LOGGER.info("Listening for WOL magic packets on %s", interface)

    async def async_stop(self) -> None:
        """Stop listening."""
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

        _LOGGER.info("Stopped WOL listener")

    def _resolve_interface(self) -> str:
        """Resolve 'auto' to a suitable non-loopback interface."""
        if self.interface != "auto":
            return self.interface

        # Prefer an interface that has an IPv4 address and is not loopback.
        candidates: list[str] = []

        for name in socket.if_nameindex():
            ifname = name[1]
            if ifname == "lo":
                continue
            candidates.append(ifname)

        if not candidates:
            raise OSError("No non-loopback network interface found")

        # In Docker host mode eth0/en* are common. Return the first candidate.
        return candidates[0]

    @staticmethod
    def _create_socket(interface: str) -> socket.socket:
        """Create a Linux raw packet socket."""
        if not hasattr(socket, "AF_PACKET"):
            raise OSError("This integration requires Linux AF_PACKET support")

        sock = socket.socket(
            socket.AF_PACKET,
            socket.SOCK_RAW,
            socket.htons(0x0003),  # ETH_P_ALL
        )
        sock.bind((interface, 0))
        sock.setblocking(False)
        return sock

    async def _listen_loop(self) -> None:
        """Read Ethernet frames and inspect UDP WOL packets."""
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
                await self._process_frame(frame)
            except Exception:
                _LOGGER.exception("Error while processing network frame")

    async def _process_frame(self, frame: bytes) -> None:
        """Inspect a single Ethernet frame."""
        if len(frame) < ETH_HEADER_LEN:
            return

        # We currently handle the common IPv4/UDP WOL case.
        parsed = _parse_ipv4_udp(frame)
        if parsed is None:
            return

        destination_port = parsed["destination_port"]
        source_port = parsed["source_port"]

        if destination_port not in WOL_UDP_PORTS and source_port not in WOL_UDP_PORTS:
            return

        target_mac = _magic_packet_target(parsed["payload"])
        if target_mac is None:
            return

        source_mac = _format_mac(frame[6:12])

        timestamp = datetime.now(timezone.utc).isoformat()

        data = {
            ATTR_TARGET_MAC: target_mac,
            ATTR_SOURCE_MAC: source_mac,
            ATTR_SOURCE_IP: parsed["source_ip"],
            ATTR_DESTINATION_IP: parsed["destination_ip"],
            ATTR_DESTINATION_PORT: destination_port,
            ATTR_INTERFACE: self.interface,
            ATTR_TIMESTAMP: timestamp,
        }

        self.last_packet = data

        _LOGGER.info(
            "WOL detected: target=%s source=%s source_ip=%s destination=%s:%s",
            target_mac,
            source_mac,
            parsed["source_ip"],
            parsed["destination_ip"],
            destination_port,
        )

        self.hass.bus.async_fire(EVENT_WOL_PACKET, data)

        # Notify entities belonging to this integration.
        self.hass.bus.async_fire(
            f"{EVENT_WOL_PACKET}_internal",
            data,
        )
