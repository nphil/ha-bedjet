# BedJet for Home Assistant

A local-push Home Assistant custom integration for a single [BedJet V3](https://bedjet.com) climate device, talking over Bluetooth Low Energy through Home Assistant's built-in `bluetooth` component. It works with any Bluetooth adapter or ESPHome Bluetooth proxy Home Assistant already sees the device through - no dedicated ESPHome device or extra hardware required.

## ⚠️ The single-connection rule

A BedJet only accepts **one** BLE connection at a time, and it **stops advertising while something is connected to it**. That has two consequences:

- If the BedJet mobile app is connected, Home Assistant cannot connect until the app disconnects.
- If Home Assistant is holding the connection, the app cannot connect until Home Assistant lets go.

There is no way to share the connection, and no way to detect "the app wants in" from the Home Assistant side - the only signal available is "the device started advertising again", which means *something* released it.

### Handing the phone app the connection: the Bluetooth Connection switch

Instead of disabling the whole integration to free the device for the app (the old workaround), this integration exposes a **Bluetooth Connection** switch entity (enabled by default, no entity category, and always available - even when the device itself is unreachable). Turn it off before opening the BedJet app (for example, to edit biorhythm programs); turn it back on when you're done and Home Assistant reconnects as soon as the device starts advertising again. Every other entity goes unavailable while the switch is off, since there is genuinely nothing to report - the connection has been intentionally given away.

### Bluetooth proxy slot economics

If your BedJet is only reachable through an ESPHome Bluetooth proxy, remember that a proxy also multiplexes a limited number of GATT connection slots across every device it serves. A held BedJet connection consumes one of those slots for as long as `hold_connection` is on, same as it would with a local adapter. This integration only ever holds zero or one connection to the BedJet itself; it does not open extra connections for probing or diagnostics.

## How it works

- No polling: the BedJet notify characteristic streams a status frame at roughly 4 Hz whenever a connection is held - even while the unit is in standby - so every entity updates the moment a real frame arrives instead of on a timer.
- Commands (mode, temperature, fan speed, runtime, LED, mute) are confirmed against the next status frame that reflects them, with a 5 second timeout. There is no optimistic/local echo: if the timeout expires, the service call fails with a clear error instead of silently pretending the change happened.
- The integration listens passively to Home Assistant's Bluetooth scanner (including proxies) for advertisements from this device's address. An advertisement means the device is currently free (nothing is connected to it), which is what lets the library reconnect automatically after the app - or anything else - lets go.

## ⬇️ Installation

### HACS (recommended)

1. Add this repository to HACS as a custom repository (category: Integration), or install it directly if it's in the default HACS list.
2. Search for **BedJet** and download it.
3. Restart Home Assistant.

### Manual

1. Copy the `custom_components/bedjet` folder from this repository into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

## ➕ Setup

Home Assistant will normally discover a BedJet automatically via Bluetooth and prompt you to add it. Otherwise, go to **Settings → Devices & services → Add integration**, search for **BedJet**, and pick your device from the list of nearby BedJets.

## Entities

All unique IDs are of the form `<mac-address>_<key>` (the climate entity's unique ID is the bare MAC address, unchanged since the original integration, to preserve history).

| Platform | Key | Category | Enabled by default | Notes |
|---|---|---|---|---|
| Climate | *(bare address)* | — | ✅ | Modes off/heat/cool/dry; presets none/Turbo/Extended Heat/M1/M2/M3 (uses the memory slot's custom name if the device reports one, otherwise "M1"/"M2"/"M3"); fixed 19-43 °C (66-104 °F) limits |
| Fan | `fan` | — | ✅ | 5-100 % in 5 % steps; turning on sets Cool mode, turning off sets Off |
| Number | `runtime_remaining` | — | ✅ | Minutes remaining in the current run |
| Sensor | `ambient_temperature` | — | ✅ | °C |
| Sensor | `outlet_temperature` | — | ✅ | °C, the air temperature at the unit's outlet |
| Sensor | `notification` | — | ✅ | Enum: filter/firmware/biorhythm notifications the unit is reporting |
| Switch | `bluetooth_connection` | — | ✅ | Always available; turn off to hand the connection slot to the BedJet app |
| Button | `acknowledge_notification` | — | ✅ | Clears the current notification on the device |
| Switch | `enable_led` | Config | ❌ | Unit's status LED |
| Switch | `mute_beeps` | Config | ❌ | Unit's beeper |
| Button | `sync_clock` | Config | ❌ | Pushes Home Assistant's current time to the unit's clock |
| Button | `firmware_update` | Config | ❌ | ⚠️ **Reboots the unit** to check for and apply a firmware update |
| Binary sensor | `connection_test` | Diagnostic | ❌ | Unit reports its internal connection test passed |
| Binary sensor | `dual_zone` | Diagnostic | ❌ | |
| Binary sensor | `units_setup` | Diagnostic | ❌ | |
| Sensor | `bio_sequence_step` | Diagnostic | ❌ | Current step while running a biorhythm program |
| Sensor | `shutdown_reason` | Diagnostic | ❌ | Raw shutdown reason code from the last frame |
| Sensor | `turbo_time` | Diagnostic | ❌ | Seconds of Turbo boost remaining |
| Sensor | `update_phase` | Diagnostic | ❌ | Raw firmware update phase code |
| Sensor | `scanner` | Diagnostic | ❌ | Which Bluetooth adapter/proxy currently sees this device |

Every entity above the connection switch goes unavailable when the device is disconnected or `bluetooth_connection` is off; there is nothing to report while the connection is intentionally given away.

## Diagnostics

Download diagnostics from the device page (⋮ → Download diagnostics) to get the current connection state (connected/available/holding, which scanner source last saw it, time since the last frame) plus a full decode of the most recent status frame - handy when reporting a problem.

## Debug logging

To see connection attempts, frame decodes, and command confirmations, add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.bedjet: debug
    bleak_retry_connector: debug
    habluetooth: debug
```

## Credits

This integration descends from [robert-friedland/homeassistant-bedjet](https://github.com/robert-friedland/homeassistant-bedjet), continued by [asheliahut](https://github.com/asheliahut), then rewritten and maintained by [natekspencer](https://github.com/natekspencer), and now maintained here by [nphil](https://github.com/nphil). Thank you to everyone in that chain for the reverse-engineering work that made this possible.
