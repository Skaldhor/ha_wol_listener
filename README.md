# Wake-on-LAN Listener – Home Assistant

Custom integration that listens for IPv4/UDP Wake-on-LAN magic packets using
Linux `AF_PACKET`, fires a `wol_packet` event and exposes a sensor for the
last packet.

## Docker requirement

Home Assistant must use host networking and have `CAP_NET_RAW`:

```yaml
services:
  homeassistant:
    image: ghcr.io/home-assistant/home-assistant:stable
    network_mode: host
    cap_add:
      - NET_RAW
    volumes:
      - /PATH/TO/CONFIG:/config
    restart: unless-stopped
```

## Installation

Copy `wol_listener` to:

`/config/custom_components/wol_listener/`

Restart Home Assistant and add:

Settings -> Devices & services -> Add integration -> Wake-on-LAN Listener

## Configuration

Interface:

```text
auto
```

or e.g.:

```text
eth0
```

Device mapping uses one line per device:

```text
AA:BB:CC:DD:EE:FF=Wohnzimmer-PC
11:22:33:44:55:66=NAS
77:88:99:AA:BB:CC=Media-PC
```

MAC addresses may also use `-` instead of `:`.

The mapping is normalized to uppercase and invalid entries are rejected.

## Event

Each detected WOL packet fires:

`wol_packet`

Example:

```yaml
target_mac: "AA:BB:CC:DD:EE:FF"
device_name: "Wohnzimmer-PC"
source_mac: "11:22:33:44:55:66"
source_ip: "192.168.1.20"
destination_ip: "192.168.1.255"
destination_port: 9
interface: "eth0"
timestamp: "2026-08-09T21:18:00+00:00"
```

If a target MAC is not mapped, `device_name` is `null` and the sensor falls
back to displaying the MAC address.

## Sensor

The sensor state is the mapped device name, or the target MAC when unknown.

Attributes:

- `device_name`
- `target_mac`
- `source_mac`
- `source_ip`
- `destination_ip`
- `destination_port`
- `interface`
- `timestamp`

## Logbook automation

```yaml
alias: WOL im Logbuch protokollieren
triggers:
  - trigger: event
    event_type: wol_packet
actions:
  - action: logbook.log
    data:
      name: Wake-on-LAN
      message: >
        {% set name = trigger.event.data.device_name
           or trigger.event.data.target_mac %}
        {{ name }} wurde per WOL geweckt
        (Quelle {{ trigger.event.data.source_ip }}).
      entity_id: sensor.letztes_wol
mode: queued
```

The target MAC, source IP/MAC and timestamp remain available as event data and
sensor attributes.

## Notes

This implementation handles the common Ethernet -> IPv4 -> UDP -> port 7/9
WOL format. It does not attempt to capture IPv6 or arbitrary encapsulations.

A packet must actually reach the interface being monitored. VLANs and switch
configuration can affect visibility.

Only `CAP_NET_RAW` is required; `privileged: true` is not needed.
