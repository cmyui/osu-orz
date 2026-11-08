"""Lossless compression for osu! replays with the ORZ format."""

from __future__ import annotations

from collections.abc import Iterable
from enum import IntEnum

from ._core import FORMAT_VERSION
from ._core import Absolute
from ._core import AxisSegment
from ._core import Coding
from ._core import CompressResult
from ._core import Device
from ._core import Mapping
from ._core import Mouse
from ._core import OrzError
from ._core import Playfield
from ._core import Rational
from ._core import Text
from ._core import compress_osr as _compress_osr
from ._core import compress_replay_data as _compress_replay_data
from ._core import decompress as _decompress
from ._core import orz_device as _orz_device

__all__ = [
    "FORMAT_VERSION",
    "Absolute",
    "AxisSegment",
    "Coding",
    "CompressResult",
    "Device",
    "Mapping",
    "Mode",
    "Mouse",
    "OrzError",
    "Playfield",
    "Rational",
    "Text",
    "compress",
    "decompress",
    "device",
]


class Mode(IntEnum):
    """What bare replay data is: its game mode, and whether Relax was on.

    Numbered as ORZ files store it. osu!mania has no Relax. Autopilot replays are
    OSU: the encoder recognises the autopilot path from the frames.
    """

    OSU = 0
    TAIKO = 1
    CATCH = 2
    MANIA = 3
    OSU_RELAX = 4
    TAIKO_RELAX = 5
    CATCH_RELAX = 6


def compress(
    data: bytes | bytearray | memoryview,
    *,
    mode: Mode | int | None = None,
    check_round_trip: bool = False,
    device_hints: Iterable[Device | bytes] = (),
) -> CompressResult:
    """Compress an .osr file, or bare replay data with its ``mode``.

    Bare replay data is the LZMA stream osu! stores for a score (an .osr's replay
    data field). It has no header to say what it is, so ``mode`` must. An .osr's
    header says it, so ``mode`` must not be given with one. The mode only changes
    how well a replay compresses, never the frames ``decompress`` gives back.

    ``check_round_trip`` decodes the .orz before returning it, and stores the replay
    data as it is if that does not give the replay back: slower, but a coding bug
    can not turn into a replay that decodes wrong.

    ``device_hints`` are the devices of the player's earlier replays, most likely
    first, as ``compress`` or ``device`` gave them for the same FORMAT_VERSION.
    The first that still fits the replay is used, skipping the encoder's device
    search. Hints never change what ``decompress`` gives back.

    Raises OrzError for an .orz, for an .osr with ``mode``, for anything else
    without ``mode`` that is not an .osr, and for a hint that is not a device.
    Raises ValueError for a ``mode`` that is not a Mode.
    """
    hints = [h.data if isinstance(h, Device) else bytes(h) for h in device_hints]

    if mode is None:
        return _compress_osr(bytes(data), check_round_trip, hints)

    return _compress_replay_data(bytes(data), Mode(mode), check_round_trip, hints)


def decompress(data: bytes | bytearray | memoryview, *, skip_crc: bool = False) -> bytes:
    """Rebuild the .osr file, or the bare replay data, that an .orz was made from.

    Replay data osu! wrote comes back byte for byte. Raises OrzError when the input
    is not a valid .orz file, was made by a newer format version, or fails its CRC.

    ``skip_crc`` gives back what a file decodes to even when it fails its CRC check
    (damaged, or written by an incompatible build), to recover what is left of it.
    """
    return _decompress(bytes(data), skip_crc)


def device(data: bytes | bytearray | memoryview) -> Device | None:
    """The device an .orz's frames are coded on: ``compress``'s ``device`` again.

    Reads only the file's head, so it does not check the CRC. Raises OrzError
    when the input is not a valid .orz file or was made by a newer format version.
    """
    return _orz_device(bytes(data))
