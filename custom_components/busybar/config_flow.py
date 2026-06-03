"""Config flow for BUSY Bar."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .api import BusyBarApi, BusyBarApiError, BusyBarAuthError
from .const import CONF_TOKEN, DOMAIN, MIN_API_MAJOR

_LOGGER = logging.getLogger(__name__)


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

        Identity is anchored on the device serial. If the bar answers without a
        token (no Password protection — the common case) we read the serial now,
        which lets us silently refresh the stored host on an IP change. If it is
        password-protected we can't read the serial yet, so we de-dupe the
        discovery by MAC and ask for the token in the confirm step.
        """
        host = f"http://{discovery_info.ip}"
        self._discovered_host = host
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

        self.context["title_placeholders"] = {"name": self._discovered_name or "BUSY Bar"}
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
