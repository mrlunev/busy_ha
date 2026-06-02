---
title: BUSY Bar
description: Instructions on how to integrate the BUSY Bar into Home Assistant.
ha_category:
  - Binary sensor
  - Button
  - Image
  - Number
  - Select
  - Sensor
  - Switch
  - Update
ha_release: "2026.7"
ha_iot_class: Local Polling
ha_config_flow: true
ha_domain: busybar
ha_integration_type: device
ha_codeowners:
  - "@busy-bar"
ha_platforms:
  - binary_sensor
  - button
  - image
  - number
  - select
  - sensor
  - switch
  - update
---

<!--
DRAFT for the future home-assistant.io PR (BUSY-9). Not published yet.
Mirror any capability/wording changes from the repo README here before submitting.
-->

The **BUSY Bar** {% term integration %} lets you control and monitor a
[BUSY Bar](https://busy.app) productivity device over its local HTTP API — no
cloud and no Matter required.

## Prerequisites

- The BUSY Bar and Home Assistant must be on the same network.
- Enable **HTTP API access** on the device under **Settings → API**.
- A token is **optional**. It is only required if you turn on **Password
  protection** on the device; in that case enter that password as the token.

{% include integrations/config_flow.md %}

{% configuration_basic %}
Host:
  description: "IP address or hostname of the BUSY Bar (for example `192.168.1.50`)."
Token:
  description: "Only required when Password protection is enabled on the device. Leave empty otherwise."
{% endconfiguration_basic %}

## Supported functionality

The integration creates a device with the following entities.

### Timer

- **Timer state** sensor (not started / open-ended / timer / pomodoro), plus
  **Phase**, **Time remaining** and **Current interval** sensors.
- **Active** and **Paused** binary sensors.
- **Theme** select (changes the active session's theme, or starts an open-ended
  session when idle).
- **Stop**, **Pause** and **Resume** buttons.

### Device

- **Battery**, **Charging**, **Wi-Fi signal** and **Firmware** sensors.
- **Brightness** and **Volume** number controls.
- **Selector** select that mirrors the physical rotary switch
  (BUSY / CUSTOM / OFF / APPS / SETTINGS).
- **Smart home switch** (available only after the bar is commissioned into a
  Matter fabric).
- **Screen** image — a live snapshot of the front display.
- **Firmware** update entity for over-the-air updates.
- **OK** and **Back** navigation buttons.

## Actions

The integration provides actions such as `busybar.notify`,
`busybar.display_text`, `busybar.display_countdown`, `busybar.start_busy`,
`busybar.start_pomodoro`, `busybar.stop_busy` and `busybar.set_theme`. With a
single bar configured the `target` may be omitted.

Display text is limited to printable ASCII; other characters are replaced.

## Re-authentication

If you enable or change **Password protection** on the device, the integration
prompts you to re-enter the credential. The device serial number is verified so
a token from a different bar is rejected.

## Removing the integration

This integration follows standard integration removal. No extra steps are
required.

{% include integrations/remove_device_service.md %}
