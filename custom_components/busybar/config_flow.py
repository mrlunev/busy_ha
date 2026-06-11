"""Config flow for BUSY Bar."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import BusyBarApi, BusyBarApiError, BusyBarAuthError
from .const import CONF_TOKEN, DOMAIN, MIN_API_MAJOR


class UnsupportedApiVersion(Exception):
    """Device firmware exposes an API version older than we support."""


def _api_major(status: dict) -> int | None:
    """Major component of system.api_semver, or None if unknown/unparseable."""
    sem = (status.get("system") or {}).get("api_semver")
    try:
        return int(str(sem).split(".")[0])
    except (ValueError, AttributeError):
        return None

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        # Auth is optional on the device — leave empty unless "Password
        # protection" is enabled on the BUSY Bar.
        vol.Optional(CONF_TOKEN, default=""): str,
    }
)


async def _validate(hass, host: str, token: str) -> tuple[str, str]:
    """Return (serial, name) or raise. Raises BusyBarAuthError / BusyBarApiError."""
    api = BusyBarApi(host, token, async_get_clientsession(hass))
    status = await api.get_status()
    major = _api_major(status)
    if major is not None and major < MIN_API_MAJOR:
        raise UnsupportedApiVersion(f"API v{major} < {MIN_API_MAJOR}")
    name = await api.get_name()
    serial = (status.get("device") or {}).get("serial_number")
    if not serial:
        raise BusyBarApiError("Device did not report a serial number")
    return serial, name.get("name", "BUSY Bar")


class BusyBarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_host: str | None = None
        self._discovered_name: str | None = None

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle a bar found via DHCP (auto-onboarding, IP self-heal).

        Two discovery matchers feed this step (see manifest ``dhcp``): a broad
        Wi-Fi OUI matcher (``8C8B48*``) for onboarding NEW bars, and
        ``registered_devices`` which fires for ANY already-added bar whose
        registered MAC reappears on a new IP — regardless of OUI. That second
        path is how we self-heal a changed IP for a bar we already manage.

        Order matters:
        1. Self-heal by MAC first. If this MAC already belongs to one of our
           config entries, just refresh its host and reload — this works even
           for password-protected bars (the hardware MAC identifies the device
           unambiguously, so we don't need to read the serial via the API).
        2. Otherwise it's a new bar: read the serial without a token (works
           when Password protection is off — the common case) so we can anchor
           identity on the serial; if protected, de-dupe by MAC and collect the
           token in the confirm step.
        """
        host = f"http://{discovery_info.ip}"
        self._discovered_host = host

        mac = format_mac(discovery_info.macaddress)
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get_device(
            connections={(CONNECTION_NETWORK_MAC, mac)}
        )
        if device is not None:
            for entry_id in device.config_entries:
                entry = self.hass.config_entries.async_get_entry(entry_id)
                if (
                    entry is not None
                    and entry.domain == DOMAIN
                    and entry.data.get(CONF_HOST) != host
                ):
                    self.hass.config_entries.async_update_entry(
                        entry, data={**entry.data, CONF_HOST: host}
                    )
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
            return self.async_abort(reason="already_configured")

        try:
            serial, name = await _validate(self.hass, discovery_info.ip, "")
        except BusyBarAuthError:
            await self.async_set_unique_id(format_mac(discovery_info.macaddress))
            self._abort_if_unique_id_configured()
        except (UnsupportedApiVersion, BusyBarApiError, aiohttp.ClientError):
            return self.async_abort(reason="cannot_connect")
        else:
            await self.async_set_unique_id(serial)
            # Self-heal: if this bar is already configured, just update its host.
            self._abort_if_unique_id_configured(updates={CONF_HOST: host})
            self._discovered_name = name

        # flow_title is "{name} ({host})" — both placeholders must be provided or
        # the frontend renders a formatjs MISSING_VALUE error on the discovery card.
        self.context["title_placeholders"] = {
            "name": self._discovered_name or "BUSY Bar",
            "host": discovery_info.ip,
        }
        return await self.async_step_discovery_confirm()

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a bar found via zeroconf/mDNS (one-click onboarding + instant IP self-heal).

        This is the preferred discovery path per HA guidance (zeroconf over dhcp):
        the bar advertises ``_busybar._tcp`` and carries its stable ``serial`` in
        the TXT record, so identity is anchored on the serial directly from the
        announcement — no API read needed. An already-added bar that re-announces
        on a new IP therefore self-heals instantly, even when password-protected.

        Requires firmware to advertise the service over Wi-Fi (BUSY-19). Until
        then this step simply never fires; the dhcp path keeps us covered.
        """
        host = f"http://{discovery_info.host}"
        self._discovered_host = host

        serial = discovery_info.properties.get("serial")
        if serial:
            # Anchor on the serial straight from the TXT record. If the bar is
            # already configured, refresh its host (IP self-heal) and abort.
            await self.async_set_unique_id(serial)
            self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        # flow_title is "{name} ({host})" — both placeholders must be provided or
        # the frontend renders a formatjs MISSING_VALUE error on the discovery card.
        name = discovery_info.properties.get("name") or discovery_info.name.split(".")[
            0
        ]
        self._discovered_name = name or "BUSY Bar"
        self.context["title_placeholders"] = {
            "name": self._discovered_name,
            "host": discovery_info.host,
        }
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered bar (and collect a token if protected)."""
        errors: dict[str, str] = {}
        host = self._discovered_host or ""
        ip = host.removeprefix("http://").removeprefix("https://")
        if user_input is not None:
            token = (user_input.get(CONF_TOKEN) or "").strip()
            try:
                serial, name = await _validate(self.hass, ip, token)
            except UnsupportedApiVersion:
                errors["base"] = "unsupported_version"
            except BusyBarAuthError:
                errors["base"] = "invalid_auth"
            except (BusyBarApiError, aiohttp.ClientError):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=name, data={CONF_HOST: host, CONF_TOKEN: token}
                )

        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=vol.Schema({vol.Optional(CONF_TOKEN, default=""): str}),
            description_placeholders={
                "name": self._discovered_name or "BUSY Bar",
                "host": host,
            },
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            token = (user_input.get(CONF_TOKEN) or "").strip()
            try:
                serial, name = await _validate(self.hass, host, token)
            except UnsupportedApiVersion:
                errors["base"] = "unsupported_version"
            except BusyBarAuthError:
                errors["base"] = "invalid_auth"
            except (BusyBarApiError, aiohttp.ClientError):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=name,
                    data={CONF_HOST: host, CONF_TOKEN: token},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the host/token of an existing bar without removing it.

        Identity stays anchored on the serial: the new host must resolve to the
        same physical bar, otherwise we abort with ``wrong_device`` rather than
        silently re-pointing the entry at a different device.
        """
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            token = (user_input.get(CONF_TOKEN) or "").strip()
            try:
                serial, _ = await _validate(self.hass, host, token)
            except UnsupportedApiVersion:
                errors["base"] = "unsupported_version"
            except BusyBarAuthError:
                errors["base"] = "invalid_auth"
            except (BusyBarApiError, aiohttp.ClientError):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data_updates={CONF_HOST: host, CONF_TOKEN: token},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=reconfigure_entry.data[CONF_HOST]
                    ): str,
                    vol.Optional(CONF_TOKEN, default=""): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-auth when the device rejects the stored token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        host = reauth_entry.data[CONF_HOST]
        if user_input is not None:
            token = (user_input.get(CONF_TOKEN) or "").strip()
            try:
                serial, _ = await _validate(self.hass, host, token)
            except UnsupportedApiVersion:
                errors["base"] = "unsupported_version"
            except BusyBarAuthError:
                errors["base"] = "invalid_auth"
            except (BusyBarApiError, aiohttp.ClientError):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    reauth_entry, data_updates={CONF_TOKEN: token}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Optional(CONF_TOKEN, default=""): str}),
            description_placeholders={"host": host},
            errors=errors,
        )
