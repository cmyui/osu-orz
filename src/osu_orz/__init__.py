"""Lossless compression for osu! replays with the ORZ format."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from ._core import FORMAT_VERSION
from ._core import OrzError
from ._core import compress as _compress
from ._core import decompress as _decompress
from ._core import header_info as _header_info

__all__ = ["FORMAT_VERSION", "HeaderInfo", "Mode", "OrzError", "compress", "decompress"]


class Mode(IntEnum):
    """An osu! game mode, numbered as in .osr files."""

    OSU = 0
    TAIKO = 1
    CATCH = 2
    MANIA = 3


@dataclass(frozen=True)
class HeaderInfo:
    """What bare replay data is, in place of the .osr header that would say.

    ``relax`` is whether it is a relax replay; osu!mania has no relax.
    """

    mode: Mode | int
    relax: bool


def compress(
    data: bytes | bytearray | memoryview,
    *,
    header_info: HeaderInfo | None = None,
) -> bytes:
    """Compress an .osr file, or bare replay data with ``header_info``.

    Bare replay data is the LZMA stream osu! stores for a score (an .osr's replay
    data field). It has no header, so ``header_info`` must say what it is. An .osr
    has its own header, so ``header_info`` must not be given with one.

    Raises OrzError when the input is not a replay, when ``header_info`` is missing
    for bare replay data or given with an .osr, or for osu!mania with relax.
    """
    if header_info is None:
        return _compress(bytes(data), 0)

    return _compress(bytes(data), _header_info(Mode(header_info.mode), header_info.relax))


def decompress(data: bytes | bytearray | memoryview) -> bytes:
    """Rebuild the .osr file, or the bare replay data, that an .orz was made from.

    Replay data osu! wrote comes back byte for byte. Raises OrzError when the input
    is not a valid .orz file, was made by a newer format version, or fails its CRC.
    """
    return _decompress(bytes(data))
