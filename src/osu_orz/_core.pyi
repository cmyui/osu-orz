from collections.abc import Sequence
import enum


class OrzError(ValueError):
    pass

FORMAT_VERSION: int = 0

class Coding(enum.IntEnum):
    """How an .orz codes its replay's frames."""

    VERBATIM = 0
    """Not coded: the replay data is stored as it was given."""

    TAIKO_CATCH_MANIA = 1
    """
    The coder for osu!taiko, osu!taiko with Relax, osu!catch and osu!mania.
    """

    TEXT = 2
    """
    osu!standard's coder (osu!, and osu!catch with Relax), positions as their decimal text: no device model fit.
    """

    DEVICE = 3
    """osu!standard's coder, positions on a device model."""

    AUTOPILOT = 4
    """
    osu!standard's coder, positions on the path osu!'s autopilot moves the cursor along.
    """

class Mapping(enum.Enum):
    """What a tablet or touch screen's area maps onto."""

    WINDOW = 0
    """osu!'s window."""

    DESKTOP = 1
    """The desktop."""

class Playfield:
    """
    Where the playfield sits in osu!'s window: a position of window pixels is (pixels - offset) / scale on the
    playfield.
    """

    def __eq__(self, other: object, /) -> bool: ...

    def __hash__(self) -> int: ...

    def __repr__(self) -> str: ...

    @property
    def scale(self) -> float:
        """Window pixels per playfield pixel."""

    @property
    def offset(self) -> float:
        """The playfield's origin, in window pixels."""

    @property
    def unrounded_sub(self) -> bool:
        """
        pixels - offset stays at full precision (osu! did it on the x87 unit) before the division.
        """

class Rational:
    """
    Positions on the OS cursor's lattice, (a * k + b) / d for whole k: mostly raw input off, from any device.
    """

    def __eq__(self, other: object, /) -> bool: ...

    def __hash__(self) -> int: ...

    def __repr__(self) -> str: ...

    @property
    def a(self) -> int: ...

    @property
    def b(self) -> int: ...

    @property
    def d(self) -> int: ...

class Mouse:
    """
    A device that reports movement (a mouse, with raw input on): counts times sensitivity, polled poll_rate
    times a second.
    """

    def __eq__(self, other: object, /) -> bool: ...

    def __hash__(self) -> int: ...

    def __repr__(self) -> str: ...

    @property
    def sensitivity(self) -> float: ...

    @property
    def poll_rate(self) -> float:
        """Reports a second."""

    @property
    def playfield(self) -> Playfield: ...

class Absolute:
    """
    A device that reports where it points (a tablet or touch screen), mapped onto the window or the desktop.
    """

    def __eq__(self, other: object, /) -> bool: ...

    def __hash__(self) -> int: ...

    def __repr__(self) -> str: ...

    @property
    def mapping(self) -> Mapping: ...

    @property
    def span(self) -> float:
        """The size of what the device maps onto, in pixels."""

    @property
    def speed(self) -> float:
        """The speed setting."""

    @property
    def window_half(self) -> float:
        """Half the window's size, in pixels."""

    @property
    def origin(self) -> float:
        """The window's origin relative to the screen's, in pixels."""

    @property
    def x87(self) -> bool:
        """osu! did the float maths on the x87 unit (else SSE)."""

    @property
    def playfield(self) -> Playfield: ...

class Text:
    """No model fit: positions as their decimal text."""

    def __eq__(self, other: object, /) -> bool: ...

    def __hash__(self) -> int: ...

    def __repr__(self) -> str: ...

class AxisSegment:
    """
    One axis's device model from frame start on. start counts the frames whose position is coded, so frames
    that repeat the frame before them are not counted.
    """

    def __eq__(self, other: object, /) -> bool: ...

    def __hash__(self) -> int: ...

    def __repr__(self) -> str: ...

    @property
    def start(self) -> int: ...

    @property
    def model(self) -> Rational | Mouse | Absolute | Text: ...

class Device:
    """
    The device model a replay's cursor positions are coded on, per axis.

    data is the device as .orz files store it: pass it, or the Device, to compress as a hint. It is tied to the
    format version that wrote it. x and y read it out: one segment per axis, or more when the setup changed during
    the replay (window moved, device swapped).
    """

    def __eq__(self, other: object, /) -> bool: ...

    def __hash__(self) -> int: ...

    def __repr__(self) -> str: ...

    @property
    def data(self) -> bytes: ...

    @property
    def x(self) -> tuple[AxisSegment, ...]: ...

    @property
    def y(self) -> tuple[AxisSegment, ...]: ...

    @staticmethod
    def from_bytes(data: bytes) -> Device:
        """Read a device's data. Raises OrzError when it is not one."""

class CompressResult:
    """
    What compress made.

    device is None unless osu!standard's coder put some axis on a device model (coding is DEVICE). hint_used is
    the index of the hint the encoder took, skipping its own device search (a mouse's poll rate is picked again),
    None when it searched. A search can find a hint's device too: compare devices to tell whether a replay's is a
    hint's.
    """

    def __eq__(self, other: object, /) -> bool: ...

    def __hash__(self) -> int: ...

    def __repr__(self) -> str: ...

    @property
    def compressed_bytes(self) -> bytes: ...

    @property
    def device(self) -> Device | None: ...

    @property
    def hint_used(self) -> int | None: ...

    @property
    def coding(self) -> Coding: ...

def compress_osr(data: bytes, check_round_trip: bool, device_hints: Sequence[bytes]) -> CompressResult: ...

def compress_replay_data(data: bytes, mode: int, check_round_trip: bool, device_hints: Sequence[bytes]) -> CompressResult: ...

def decompress(data: bytes, skip_crc: bool) -> bytes: ...

def orz_device(data: bytes) -> Device | None: ...
