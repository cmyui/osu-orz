"""Lossless compression for osu! replays with the ORZ format."""

from __future__ import annotations

from enum import IntEnum

from ._core import FORMAT_VERSION
from ._core import OrzError
from ._core import compress_osr as _compress_osr
from ._core import compress_replay_data as _compress_replay_data
from ._core import decompress as _decompress

__all__ = ["FORMAT_VERSION", "Mode", "OrzError", "compress", "decompress"]


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


def compress(data: bytes | bytearray | memoryview, *, mode: Mode | int | None = None) -> bytes:
    """Compress an .osr file, or bare replay data with its ``mode``.

    Bare replay data is the LZMA stream osu! stores for a score (an .osr's replay
    data field). It has no header to say what it is, so ``mode`` must. An .osr's
    header says it, so ``mode`` must not be given with one. The mode only changes
    how well a replay compresses, never what ``decompress`` gives back.

    Raises OrzError for an .orz, for an .osr with ``mode``, and for anything else
    without ``mode`` that is not an .osr. Raises ValueError for a ``mode`` that is
    not a Mode.
    """
    if mode is None:
        return _compress_osr(bytes(data))

    return _compress_replay_data(bytes(data), Mode(mode))


def decompress(data: bytes | bytearray | memoryview) -> bytes:
    """Rebuild the .osr file, or the bare replay data, that an .orz was made from.

    Replay data osu! wrote comes back byte for byte. Raises OrzError when the input
    is not a valid .orz file, was made by a newer format version, or fails its CRC.
    """
    return _decompress(bytes(data))
