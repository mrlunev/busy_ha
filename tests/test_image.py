"""Unit tests for the screen-frame → BMP conversion."""

from __future__ import annotations

import struct

from custom_components.busybar.image import _PX, SCREEN_H, SCREEN_W, _bmp_from_frame

_EXPECTED_SIZE = 54 + SCREEN_W * 3 * SCREEN_H


def _parse_header(bmp: bytes) -> dict:
    assert bmp[:2] == b"BM"
    file_size, _, _, offset = struct.unpack_from("<IHHI", bmp, 2)
    width, height, planes, bpp = struct.unpack_from("<iiHH", bmp, 18)
    return {
        "file_size": file_size,
        "offset": offset,
        "width": width,
        "height": height,
        "bpp": bpp,
    }


def test_bmp_from_bgr_frame() -> None:
    bmp = _bmp_from_frame(bytes([10, 20, 30]) * _PX)
    assert bmp is not None
    assert len(bmp) == _EXPECTED_SIZE
    hdr = _parse_header(bmp)
    assert hdr == {
        "file_size": _EXPECTED_SIZE,
        "offset": 54,
        "width": SCREEN_W,
        "height": SCREEN_H,
        "bpp": 24,
    }


def test_bmp_from_rgba_frame() -> None:
    # RGBA pixel (1,2,3,255) must become BGR (3,2,1) in the BMP body.
    bmp = _bmp_from_frame(bytes([1, 2, 3, 255]) * _PX)
    assert bmp is not None
    assert len(bmp) == _EXPECTED_SIZE
    assert bmp[54:57] == bytes([3, 2, 1])


def test_bmp_rejects_wrong_length() -> None:
    assert _bmp_from_frame(b"\x00\x01\x02\x03\x04") is None
    assert _bmp_from_frame(b"") is None
