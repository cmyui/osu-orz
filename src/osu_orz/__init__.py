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


def compress(
    data: bytes | bytearray | memoryview,
    *,
    mode: Mode | int | None = None,
    check_round_trip: bool = False,
) -> bytes:
    """Compress an .osr file, or bare replay data with its ``mode``.

    Bare replay data is the LZMA stream osu! stores for a score (an .osr's replay
    data field). It has no header to say what it is, so ``mode`` must. An .osr's
    header says it, so ``mode`` must not be given with one. The mode only changes
    how well a replay compresses, never the frames ``decompress`` gives back.

    ``check_round_trip`` decodes the .orz before returning it, and stores the replay
    data as it is if that does not give the replay back: slower, but a coding bug
    can not turn into a replay that decodes wrong.

    Raises OrzError for an .orz, for an .osr with ``mode``, and for anything else
    without ``mode`` that is not an .osr. Raises ValueError for a ``mode`` that is
    not a Mode.
    """
    if mode is None:
        return _compress_osr(bytes(data), check_round_trip)

    return _compress_replay_data(bytes(data), Mode(mode), check_round_trip)


def decompress(data: bytes | bytearray | memoryview, *, skip_crc: bool = False) -> bytes:
    """Rebuild the .osr file, or the bare replay data, that an .orz was made from.

    Replay data osu! wrote comes back byte for byte. Raises OrzError when the input
    is not a valid .orz file, was made by a newer format version, or fails its CRC.

    ``skip_crc`` gives back what a file decodes to even when it fails its CRC check
    (damaged, or written by an incompatible build), to recover what is left of it.
    """
    return _decompress(bytes(data), skip_crc)
