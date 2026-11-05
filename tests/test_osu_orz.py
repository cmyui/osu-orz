import concurrent.futures
import lzma
import random
import struct

import pytest

import osu_orz
from osu_orz import Mode


def number(v: float) -> str:
    # as osu!stable prints floats: 7 significant digits, no trailing zeros
    return format(v, ".7g")


def replay_text(mode: Mode, frames: int = 2000, seed: int = 1) -> bytes:
    # frames of the mode's game mode
    mode = mode % 4
    rng = random.Random(seed)
    out = ["0|256|-500|0", "-1|256|-500|0"]
    x, y = 256.0, 192.0
    for _ in range(frames):
        delta = rng.choice([16, 17, 17])
        if mode == Mode.MANIA:
            out.append(f"{delta}|{rng.randrange(16)}|{number(rng.choice([1.0, 1.5]))}|0")
        elif mode == Mode.TAIKO:
            keys = rng.choice([0, 0, 1, 2, 4, 8])
            out.append(f"{delta}|320|9999|{keys}")
        elif mode == Mode.CATCH:
            x = min(max(x + rng.uniform(-8, 8), 0), 512)
            out.append(f"{delta}|{number(round(x * 4) / 4)}|9999|{rng.choice([0, 1])}")
        else:
            x = min(max(x + rng.uniform(-6, 6), 0), 512)
            y = min(max(y + rng.uniform(-6, 6), 0), 384)
            out.append(f"{delta}|{number(round(x * 4) / 4)}|{number(round(y * 4) / 4)}|{rng.choice([0, 1, 5, 10])}")
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

    first = osu_orz.decompress(osu_orz.compress(replay_data(text), mode=mode))

    # the frames come back exactly, recompressed the way osu! compresses them
    assert text_of(first) == text
    # data osu!'s encoder wrote comes back byte for byte
    assert osu_orz.decompress(osu_orz.compress(first, mode=mode)) == first


@pytest.mark.parametrize("game_mode, mods", [(0, 0), (1, 0), (2, 0), (3, 0), (0, RELAX), (1, RELAX), (2, RELAX)])
def test_osr_round_trips(game_mode: int, mods: int) -> None:
    life = "0|1,4000|0.95,8000|0.8,12000|1," if game_mode != Mode.MANIA else ""
    original = osr(game_mode, replay_data(replay_text(Mode(game_mode))), mods=mods, life=life)

    first = osu_orz.decompress(osu_orz.compress(original))

    assert osu_orz.decompress(osu_orz.compress(first)) == first
    assert len(first) < len(original) * 2


@pytest.mark.parametrize("frames_of", [Mode.OSU, Mode.TAIKO, Mode.CATCH, Mode.MANIA])
def test_a_wrong_mode_only_costs_size(frames_of: Mode) -> None:
    data = osu_orz.decompress(osu_orz.compress(replay_data(replay_text(frames_of)), mode=frames_of))

    for mode in Mode:
        assert osu_orz.decompress(osu_orz.compress(data, mode=mode)) == data


def test_data_that_is_not_replay_data_comes_back_as_it_is() -> None:
    data = bytes([0x5D]) + random.Random(2).randbytes(3000)

    assert osu_orz.decompress(osu_orz.compress(data, mode=Mode.OSU)) == data


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


def test_compresses() -> None:
    data = replay_data(replay_text(Mode.OSU, frames=20000))

    assert len(osu_orz.compress(data, mode=Mode.OSU)) < len(data) / 2


def test_bad_input() -> None:
    with pytest.raises(osu_orz.OrzError):
        osu_orz.compress(b"not a replay" * 20)
    with pytest.raises(osu_orz.OrzError):
        osu_orz.decompress(b"not an orz file")

    orz = osu_orz.compress(replay_data(replay_text(Mode.OSU)), mode=Mode.OSU)
    with pytest.raises(osu_orz.OrzError):
        osu_orz.compress(orz)
    with pytest.raises(osu_orz.OrzError):
        osu_orz.compress(orz, mode=Mode.OSU)
    for cut in (1, 2, 8, len(orz) // 2):
        with pytest.raises(osu_orz.OrzError):
            osu_orz.decompress(orz[:cut])


def test_threads() -> None:
    modes = [m for m in Mode for _ in range(3)]
    data = [replay_data(replay_text(m, seed=s)) for s, m in enumerate(modes)]
    expected = [osu_orz.compress(d, mode=m) for d, m in zip(data, modes)]

    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        got = list(pool.map(lambda d, m: osu_orz.compress(d, mode=m), data, modes))
        back = list(pool.map(osu_orz.decompress, got))

    assert got == expected
    assert back == [osu_orz.decompress(o) for o in expected]
