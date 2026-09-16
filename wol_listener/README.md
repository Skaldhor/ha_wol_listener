# Wake-on-LAN Listener for Home Assistant

Custom Home Assistant integration that listens for Wake-on-LAN magic packets
directly on a Linux network interface using `AF_PACKET`.

## Requirements

- Home Assistant Container on Linux
- `network_mode: host`
- Docker capability `NET_RAW`
- An Ethernet interface visible inside the HA container
- The WOL traffic must reach that interface

## Docker Compose

```yaml
services:
  homeassistant:
    image: ghcr.io/home-assistant/home-assistant:stable
    container_name: homeassistant
    network_mode: host
    cap_add:
      - NET_RAW
    volumes:
      - /PATH/TO/CONFIG:/config
      - /etc/localtime:/etc/localtime:ro
    restart: unless-stopped
```

Do not use `privileged: true` just for this integration.

## Installation

Copy the `wol_listener` directory to:

`/config/custom_components/wol_listener/`

Restart Home Assistant.

Then go to:

Settings -> Devices & services -> Add integration -> Wake-on-LAN Listener

Use `auto` or the interface name, for example `eth0`.

## Events

For every detected magic packet the integration fires:

`wol_packet`

Example event data:

```yaml
target_mac: "AA:BB:CC:DD:EE:FF"
source_mac: "11:22:33:44:55:66"
source_ip: "192.168.1.20"
destination_ip: "192.168.1.255"
destination_port: 9
interface: "eth0"
timestamp: "2026-08-09T21:18:00+00:00"
```

## Logbook automation

The integration deliberately fires a normal Home Assistant event instead of
writing directly to the recorder. This keeps the listener independent from
the recorder/logbook implementation.

Add this automation:

```yaml
alias: WOL im Logbuch protokollieren
description: ""
triggers:
  - trigger: event
    event_type: wol_packet
actions:
  - action: logbook.log
    data:
      name: Wake-on-LAN
      message: >
        Ziel {{ trigger.event.data.target_mac }}
        von {{ trigger.event.data.source_ip }}
        ({{ trigger.event.data.source_mac }})
        über {{ trigger.event.data.destination_ip }}:{{ trigger.event.data.destination_port }}
      entity_id: sensor.letztes_wol
mode: queued
```

After the first startup, check the actual entity ID. Depending on your
installation it will normally be `sensor.letztes_wol`.

## Sensor

The sensor state is the target MAC address.

Attributes:

- `target_mac`
- `source_mac`
- `source_ip`
- `destination_ip`
- `destination_port`
- `interface`
- `timestamp`

## Limitations

This first implementation handles the common WOL form:

Ethernet -> IPv4 -> UDP -> port 7/9 -> magic packet

It intentionally does not claim to capture every possible WOL transport,
IPv6, or non-standard encapsulation.

A WOL packet can only be observed if the packet actually reaches the network
interface on which the listener is attached. On a switched network this is
usually fine for broadcast WOL, but VLANs and switch configuration can affect
what is visible.

## Security

The integration uses a raw packet socket. Grant only:

`CAP_NET_RAW`

Avoid `privileged: true` unless you have another reason to require it.
