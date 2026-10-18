"""Lossless compression for osu! replays with the ORZ format."""

from __future__ import annotations

from enum import IntEnum

from ._core import FORMAT_VERSION
from ._core import OrzError
from ._core import compress as _compress
from ._core import decompress as _decompress

__all__ = ["FORMAT_VERSION", "Mode", "OrzError", "compress", "decompress"]


class Mode(IntEnum):
    """An osu! game mode, numbered as in .osr files."""

    OSU = 0
    TAIKO = 1
    CATCH = 2
    MANIA = 3


def compress(
    data: bytes | bytearray | memoryview,
    mode: Mode | int | None = None,
    *,
    relax: bool = False,
) -> bytes:
    """Compress an .osr file, or bare replay data when ``mode`` is given.

    Bare replay data is the LZMA stream osu! stores for a score (an .osr's replay
    data field). It carries no header, so ``mode`` says which game mode it is and
    ``relax`` whether it is a relax replay. An .osr has both in its header.

    Raises OrzError when the input is not a replay.
    """
    if mode is None:
        if relax:
            raise ValueError("relax only applies to bare replay data; an .osr has it in its mods")
        return _compress(bytes(data), -1, False)

    return _compress(bytes(data), int(Mode(mode)), relax)


def decompress(data: bytes | bytearray | memoryview) -> bytes:
    """Rebuild the .osr file, or the bare replay data, that an .orz was made from.

    Replay data osu! wrote comes back byte for byte. Raises OrzError when the input
    is not a valid .orz file, was made by a newer format version, or fails its CRC.
    """
    return _decompress(bytes(data))
