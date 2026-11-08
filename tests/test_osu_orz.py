import concurrent.futures
import lzma
import random
import struct

import pytest

import osu_orz
from osu_orz import Coding
from osu_orz import Mode


def number(v: float) -> str:
    # as osu!stable prints floats: 7 significant digits, no trailing zeros
    return format(v, ".7g")


def replay_text(mode: Mode, frames: int = 2000, seed: int = 1) -> bytes:
    # frames of the mode's game mode, held for runs of frames as in play. Frames that change at random every frame code
    # worse than LZMA, so the codec would store them as they are and the coders would go untested
    mode = Mode(mode % 4)
    keys_of = {Mode.MANIA: range(16), Mode.TAIKO: [0, 0, 1, 2, 4, 8], Mode.CATCH: [0, 0, 1]}.get(mode, [0, 0, 1, 5, 10])
    rng = random.Random(seed)
    out = ["0|256|-500|0", "-1|256|-500|0"]
    x, y, dx, dy, walk, keys = 256.0, 192.0, 0.0, 0.0, 0, 0
    for _ in range(frames):
        delta = rng.choice([16, 17, 17])
        if rng.random() < 0.15:
            keys, dx, dy, walk = rng.choice(keys_of), rng.uniform(-6, 6), rng.uniform(-6, 6), rng.choice([-1, 0, 1])
        if mode == Mode.MANIA:
            out.append(f"{delta}|{keys}|1|0")
        elif mode == Mode.TAIKO:
            # x is the drum side hit: 0 for keys 1 and 2, 640 for keys 4 and 8
            out.append(f"{delta}|{0 if keys & 3 else 640 if keys & 12 else 320}|9999|{keys}")
        elif mode == Mode.CATCH:
            # the catcher walks 0.5 px per ms, and dashes at 1 px per ms on key 1
            x = min(max(x + walk * delta * (1.0 if keys & 1 else 0.5), 0), 512)
            out.append(f"{delta}|{number(x)}|9999|{keys}")
        else:
            x, y = min(max(x + dx, 0), 512), min(max(y + dy, 0), 384)
            out.append(f"{delta}|{number(round(x * 4) / 4)}|{number(round(y * 4) / 4)}|{keys}")
    return (",".join(out) + ",").encode()


def replay_data(text: bytes) -> bytes:
    # the layout osu! stores: LZMA properties, the u64 text size, the stream (liblzma's encoder here, not osu!'s)
    stream = lzma.compress(
        text,
        format=lzma.FORMAT_RAW,
        filters=[{"id": lzma.FILTER_LZMA1, "dict_size": 1 << 21, "lc": 3, "lp": 0, "pb": 2}],
    )
    return bytes([(2 * 5 + 0) * 9 + 3]) + (1 << 21).to_bytes(4, "little") + len(text).to_bytes(8, "little") + stream


def text_of(data: bytes) -> bytes:
    size = int.from_bytes(data[5:13], "little")
    decoder = lzma.LZMADecompressor(
        format=lzma.FORMAT_RAW,
        filters=[{"id": lzma.FILTER_LZMA1, "dict_size": 1 << 21, "lc": 3, "lp": 0, "pb": 2}],
    )
    return decoder.decompress(data[13:], max_length=size)


def osu_string(s: str) -> bytes:
    b = s.encode()
    length, uleb = len(b), bytearray()
    while True:
        byte, length = length & 127, length >> 7
        uleb.append(byte | (128 if length else 0))
        if not length:
            return b"\x0b" + bytes(uleb) + b


def osr(game_mode: int, data: bytes, mods: int = 0, life: str = "") -> bytes:
    return b"".join([
        struct.pack("<Bi", game_mode, 20240101),
        osu_string("d41d8cd98f00b204e9800998ecf8427e"),
        osu_string("player"),
        osu_string("0123456789abcdef0123456789abcdef"),
        struct.pack("<6hiHBi", 300, 20, 3, 40, 10, 2, 1234567, 512, 0, mods),
        osu_string(life) if life else b"\x00",
        struct.pack("<qi", 638000000000000000, len(data)),
        data,
        struct.pack("<q", 4242424242),
    ])


RELAX = 1 << 7


@pytest.mark.parametrize("mode", list(Mode))
def test_bare_replay_data_round_trips(mode: Mode) -> None:
    text = replay_text(mode)
    data = replay_data(text)

    orz = osu_orz.compress(data, mode=mode).compressed_bytes
    # the frames were coded, not stored as they are
    assert len(orz) < len(data)

    first = osu_orz.decompress(orz)
    # the frames come back exactly, recompressed the way osu! compresses them
    assert text_of(first) == text
    # data osu!'s encoder wrote comes back byte for byte
    assert osu_orz.decompress(osu_orz.compress(first, mode=mode).compressed_bytes) == first


@pytest.mark.parametrize("game_mode, mods", [(0, 0), (1, 0), (2, 0), (3, 0), (0, RELAX), (1, RELAX), (2, RELAX)])
def test_osr_round_trips(game_mode: int, mods: int) -> None:
    life = "0|1,4000|0.95,8000|0.8,12000|1," if game_mode != Mode.MANIA else ""
    original = osr(game_mode, replay_data(replay_text(Mode(game_mode))), mods=mods, life=life)

    first = osu_orz.decompress(osu_orz.compress(original).compressed_bytes)

    assert osu_orz.decompress(osu_orz.compress(first).compressed_bytes) == first
    assert len(first) < len(original) * 2


@pytest.mark.parametrize("frames_of", [Mode.OSU, Mode.TAIKO, Mode.CATCH, Mode.MANIA])
def test_a_wrong_mode_only_costs_size(frames_of: Mode) -> None:
    text = replay_text(frames_of)
    # replay data osu!'s encoder wrote: coded frames come back compressed the way osu! compresses them
    data = osu_orz.decompress(osu_orz.compress(replay_data(text), mode=frames_of).compressed_bytes)
    assert text_of(data) == text and data != replay_data(text)

    for mode in Mode:
        assert osu_orz.decompress(osu_orz.compress(data, mode=mode).compressed_bytes) == data


def test_data_that_is_not_replay_data_comes_back_as_it_is() -> None:
    data = bytes([0x5D]) + random.Random(2).randbytes(3000)

    result = osu_orz.compress(data, mode=Mode.OSU)
    assert osu_orz.decompress(result.compressed_bytes) == data
    assert result.coding == Coding.VERBATIM and result.device is None


def test_mode_is_for_bare_replay_data_only() -> None:
    data = replay_data(replay_text(Mode.OSU))

    # an .osr says what it is itself, so the two could disagree
    with pytest.raises(osu_orz.OrzError):
        osu_orz.compress(osr(0, data), mode=Mode.OSU)
    # bare replay data does not
    with pytest.raises(osu_orz.OrzError):
        osu_orz.compress(data)
    # 7 is autopilot, which the encoder finds itself
    for mode in (-1, 7, 8):
        with pytest.raises(ValueError):
            osu_orz.compress(data, mode=mode)


@pytest.mark.parametrize("mode", list(Mode))
def test_check_round_trip_only_checks(mode: Mode) -> None:
    data = replay_data(replay_text(mode))

    assert osu_orz.compress(data, mode=mode, check_round_trip=True) == osu_orz.compress(data, mode=mode)


def test_skip_crc() -> None:
    orz = osu_orz.compress(replay_data(replay_text(Mode.OSU)), mode=Mode.OSU).compressed_bytes
    assert osu_orz.decompress(orz, skip_crc=True) == osu_orz.decompress(orz)

    damaged = bytearray(orz)
    damaged[len(orz) // 2] ^= 0x40
    with pytest.raises(osu_orz.OrzError):
        osu_orz.decompress(bytes(damaged))
    # what is left of it
    osu_orz.decompress(bytes(damaged), skip_crc=True)


def test_compresses() -> None:
    data = replay_data(replay_text(Mode.OSU, frames=20000))

    assert len(osu_orz.compress(data, mode=Mode.OSU).compressed_bytes) < len(data) / 2


def test_bad_input() -> None:
    with pytest.raises(osu_orz.OrzError):
        osu_orz.compress(b"not a replay" * 20)
    with pytest.raises(osu_orz.OrzError):
        osu_orz.decompress(b"not an orz file")

    orz = osu_orz.compress(replay_data(replay_text(Mode.OSU)), mode=Mode.OSU).compressed_bytes
    with pytest.raises(osu_orz.OrzError):
        osu_orz.compress(orz)
    with pytest.raises(osu_orz.OrzError):
        osu_orz.compress(orz, mode=Mode.OSU)
    for cut in (1, 2, 8, len(orz) // 2):
        with pytest.raises(osu_orz.OrzError):
            osu_orz.decompress(orz[:cut])
    with pytest.raises(osu_orz.OrzError):
        osu_orz.device(b"not an orz file")


def test_threads() -> None:
    modes = [m for m in Mode for _ in range(3)]
    data = [replay_data(replay_text(m, seed=s)) for s, m in enumerate(modes)]
    expected = [osu_orz.compress(d, mode=m).compressed_bytes for d, m in zip(data, modes)]

    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        got = list(pool.map(lambda d, m: osu_orz.compress(d, mode=m).compressed_bytes, data, modes))
        back = list(pool.map(osu_orz.decompress, got))

    assert got == expected
    assert back == [osu_orz.decompress(o) for o in expected]


def test_device_reads_back() -> None:
    result = osu_orz.compress(replay_data(replay_text(Mode.OSU)), mode=Mode.OSU)

    assert result.coding == Coding.DEVICE and result.device is not None
    # the .orz stores the device the result gives
    assert osu_orz.device(result.compressed_bytes) == result.device
    assert osu_orz.Device.from_bytes(result.device.data) == result.device


@pytest.mark.parametrize("mode", [Mode.TAIKO, Mode.CATCH, Mode.MANIA, Mode.TAIKO_RELAX])
def test_no_device_outside_the_standard_coder(mode: Mode) -> None:
    result = osu_orz.compress(replay_data(replay_text(mode)), mode=mode)

    assert result.coding == Coding.TAIKO_CATCH_MANIA and result.device is None
    assert osu_orz.device(result.compressed_bytes) is None


def test_device_hints_only_change_the_search() -> None:
    data = replay_data(replay_text(Mode.OSU, seed=2))
    plain = osu_orz.compress(data, mode=Mode.OSU)
    own = plain.device
    other = osu_orz.compress(replay_data(replay_text(Mode.OSU, seed=1)), mode=Mode.OSU).device
    assert own is not None and other is not None

    # a replay's own device fits it
    for hints in ([own], [own.data], [own, other]):
        hinted = osu_orz.compress(data, mode=Mode.OSU, device_hints=hints)
        assert hinted.matched_hint == 0 and hinted.device == own

    # whether a hint fits or not, the replay decodes the same
    for hints in ([other], [other, own]):
        hinted = osu_orz.compress(data, mode=Mode.OSU, device_hints=hints)
        assert osu_orz.decompress(hinted.compressed_bytes) == osu_orz.decompress(plain.compressed_bytes)


def test_bad_device() -> None:
    data = replay_data(replay_text(Mode.OSU))
    device = osu_orz.compress(data, mode=Mode.OSU).device
    assert device is not None

    for bad in (b"", device.data + b"\x00", b"\xff" * 8):
        with pytest.raises(osu_orz.OrzError):
            osu_orz.Device.from_bytes(bad)
        with pytest.raises(osu_orz.OrzError):
            osu_orz.compress(data, mode=Mode.OSU, device_hints=[bad])
