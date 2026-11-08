"""Lossless compression for osu! replays with the ORZ format."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum
from typing import Literal

from ._core import FORMAT_VERSION
from ._core import OrzError
from ._core import compress_osr as _compress_osr
from ._core import compress_replay_data as _compress_replay_data
from ._core import decompress as _decompress
from ._core import device_segments as _device_segments
from ._core import orz_device as _orz_device

__all__ = [
    "FORMAT_VERSION",
    "AxisSegment",
    "Coding",
    "CompressResult",
    "Device",
    "DeviceKind",
    "Mode",
    "OrzError",
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


class Coding(IntEnum):
    """How an .orz codes its replay's frames."""

    # not coded: the replay data is stored as it was given
    VERBATIM = 0
    # the coder for osu!taiko, osu!taiko with Relax, osu!catch and osu!mania
    TAIKO_CATCH_MANIA = 1
    # osu!standard's coder (osu!, and osu!catch with Relax), positions as their decimal text: no device model fit
    TEXT = 2
    # osu!standard's coder, positions on a device model
    DEVICE = 3
    # osu!standard's coder, positions on the path osu!'s autopilot moves the cursor along
    AUTOPILOT = 4


class DeviceKind(IntEnum):
    """The model an axis's positions are coded on.

    It is the model that reproduces the positions, which only partly says what
    hardware made them: a mouse or a tablet with raw input off both move the
    OS cursor, so both code as RATIONAL.
    """

    # no model: every position is escaped
    NONE = 0
    # positions on the OS cursor's lattice, (a * k + b) / D for whole k. Mostly raw input off, from any device
    RATIONAL = 1
    # a device that reports movement: counts times sensitivity, polled poll_rate times a second (a mouse)
    MOUSE = 2
    # a device that reports where it points, mapped onto the window or the desktop (a tablet or touch screen)
    ABSOLUTE = 3
    # no model fit: positions as their decimal text
    TEXT = 4


@dataclass(frozen=True)
class AxisSegment:
    """One axis's device model from frame ``start`` on.

    ``start`` counts the frames whose position is coded, so frames that repeat
    the frame before them are not counted. Parameters a kind does not have are
    None. The codec's parameters are float32: each reads as the shortest decimal
    that gives the same float32, and ``Device.data`` holds them exactly.
    """

    start: int
    kind: DeviceKind
    # RATIONAL: (a, b, D), positions are (a * k + b) / D for whole k
    rational: tuple[int, int, int] | None = None
    # MOUSE
    sensitivity: float | None = None
    poll_rate: float | None = None
    # ABSOLUTE: what the device maps onto, its size in pixels, the speed setting, half the window's size, and the
    # window's origin relative to the screen's
    mapping: Literal["window", "desktop"] | None = None
    span: float | None = None
    speed: float | None = None
    window_half: float | None = None
    origin: float | None = None
    # ABSOLUTE: whether osu! did the float maths on the x87 unit (else SSE)
    x87: bool | None = None
    # MOUSE and ABSOLUTE: window pixels to playfield position, (pixels - offset) / scale. unrounded_sub: pixels - offset
    # stays at full precision before the division
    scale: float | None = None
    offset: float | None = None
    unrounded_sub: bool | None = None


@dataclass(frozen=True)
class Device:
    """The device model a replay's cursor positions are coded on, per axis.

    ``data`` is the device as .orz files store it: pass it, or the Device, to
    ``compress`` as a hint. It is tied to the format version that wrote it.
    ``x`` and ``y`` read it out: one segment per axis, or more when the setup
    changed during the replay (window moved, device swapped).
    """

    data: bytes
    x: tuple[AxisSegment, ...]
    y: tuple[AxisSegment, ...]

    @classmethod
    def from_bytes(cls, data: bytes | bytearray | memoryview) -> Device:
        """Read a device's ``data``. Raises OrzError when it is not one."""
        data = bytes(data)
        x, y = _device_segments(data)
        return cls(data, _segments(x), _segments(y))


def _segments(axis: list[dict[str, object]]) -> tuple[AxisSegment, ...]:
    return tuple(AxisSegment(**{**s, "kind": DeviceKind(s["kind"])}) for s in axis)  # type: ignore[arg-type]


@dataclass(frozen=True)
class CompressResult:
    """What ``compress`` made.

    ``device`` is None unless osu!standard's coder put some axis on a device
    model (``coding`` is DEVICE). ``matched_hint`` is the index of the first
    hint whose device the .orz is coded with (a mouse's poll rate may differ:
    the encoder picks the one that codes the replay best), None for none.
    """

    compressed_bytes: bytes
    device: Device | None
    matched_hint: int | None
    coding: Coding


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
        orz, device_data, hint, coding = _compress_osr(bytes(data), check_round_trip, hints)
    else:
        orz, device_data, hint, coding = _compress_replay_data(bytes(data), Mode(mode), check_round_trip, hints)

    return CompressResult(
        orz,
        Device.from_bytes(device_data) if device_data is not None else None,
        hint,
        Coding(coding),
    )


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
    device_data = _orz_device(bytes(data))

    return Device.from_bytes(device_data) if device_data is not None else None
