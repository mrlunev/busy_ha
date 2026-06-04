# BUSY Bar for Home Assistant

Draft integration of the BUSY Bar into Home Assistant.

## What you can try

Once installed, the bar can be wired to anything in your home through standard Home Assistant automations. For example:

- Washing machine finishes → the bar pops up a "Laundry done" message with an icon and a marquee.
- CO₂ in the bedroom is too high → the bar shows "Ventilate the room".
- You plug the car in to charge → the bar shows the charge percentage.
- You start a BUSY timer on the bar → the lights and music turn off at home.
- You turn the rotary selector to `off` → the desk lamp turns off.
- The bar goes offline → you get a notification on your phone.

What the bar can show and control: the timer and its state, battery level, Wi-Fi, brightness, volume, theme (11 themes), start/pause/stop buttons, a screen image, firmware updates, and a set of actions (`notify`, `start_timer`, `set_theme`, `play_sound`, and more).

## How to install it in your Home Assistant

### Via HACS

If you use HACS: HACS → ⋮ → **Custom repositories** → add the URL of this repository with the **Integration** category, install **BUSY Bar**, restart Home Assistant, and then continue from step 4 below.

### Without HACS, manually

You need the BUSY Bar on the same network as Home Assistant, with its HTTP API enabled.

**1. Enable the API on the bar.** On the device: **Settings → API → enable HTTP API access**. Preferably without a password.

**2. Put the integration into Home Assistant.** Copy the `custom_components/busybar` folder from this repository into your Home Assistant configuration folder, so that you end up with:

```
<config>/custom_components/busybar/
```

(`<config>` is where your `configuration.yaml` lives.)

**3. Restart Home Assistant.** Settings → System → Restart.

**4. Add the bar.**
- Home Assistant usually discovers the bar on its own and shows a **"Discovered: BUSY Bar"** notification — click **Configure** and confirm. If it isn't discovered, reboot the bar and let it connect to Wi-Fi.
- If it isn't found automatically: **Settings → Devices & Services → Add Integration → BUSY Bar**, and enter the bar's address as `http://<bar-ip>`. You can find the bar's IP in its local web UI.
- If you set a password, enter it; if you didn't, leave the field empty.

Done — the bar will appear under **Settings → Devices & Services**, with all of its sensors and buttons.

> The bar is tied to its serial number, not to its IP or name. So changing its IP on the network or renaming the bar won't break anything.
