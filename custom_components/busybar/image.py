"""Image platform — live snapshot of the BUSY Bar front display."""

from __future__ import annotations

import base64
import binascii
import struct

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import BusyBarApiError
from .coordinator import BusyBarCoordinator
from .entity import BusyBarEntity

PARALLEL_UPDATES = 0

# Front display geometry (reverse-engineered from the device web UI).
SCREEN_W = 72
SCREEN_H = 16
_PX = SCREEN_W * SCREEN_H


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BusyBarCoordinator = entry.runtime_data
    async_add_entities([BusyBarScreenImage(coordinator, hass)])


def _bmp_from_frame(raw: bytes) -> bytes | None:
    """Wrap a raw BUSY Bar front frame into a 24-bit BMP.

    The device sends either BGR888 (``_PX*3`` bytes) or RGBA (``_PX*4``). A
    24-bit BMP stores pixels as BGR, bottom-up — so BGR input maps directly and
    rows are emitted in reverse order.
    """
    if len(raw) == _PX * 3:
        bgr = raw
    elif len(raw) == _PX * 4:
        out = bytearray(_PX * 3)
        for i in range(_PX):
            out[i * 3] = raw[i * 4 + 2]
            out[i * 3 + 1] = raw[i * 4 + 1]
            out[i * 3 + 2] = raw[i * 4]
        bgr = bytes(out)
    else:
        return None

    row = SCREEN_W * 3  # 216 → already 4-byte aligned, no padding needed
    pixel_data = b"".join(
        bgr[y * row : (y + 1) * row] for y in range(SCREEN_H - 1, -1, -1)
    )
    file_size = 54 + len(pixel_data)
    file_header = b"BM" + struct.pack("<IHHI", file_size, 0, 0, 54)
    info_header = struct.pack(
        "<IiiHHIIiiII",
        40,            # header size
        SCREEN_W,
        SCREEN_H,      # positive → bottom-up
        1,             # planes
        24,            # bits per pixel
        0,             # BI_RGB (no compression)
        len(pixel_data),
        2835, 2835,    # ~72 DPI
        0, 0,
    )
    return file_header + info_header + pixel_data


class BusyBarScreenImage(BusyBarEntity, ImageEntity):
    """Periodically-refreshed snapshot of the front display."""

    _attr_translation_key = "screen"
    _attr_content_type = "image/bmp"

    def __init__(self, coordinator: BusyBarCoordinator, hass: HomeAssistant) -> None:
        super().__init__(coordinator, "screen")
        ImageEntity.__init__(self, hass)
        self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        # Bump the timestamp each poll so the frontend re-pulls the frame.
        self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        try:
            b64 = await self.coordinator.api.get_screen_b64(0)
        except BusyBarApiError:
            return None
        try:
            raw = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            return None
        return _bmp_from_frame(raw)
