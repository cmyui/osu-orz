import concurrent.futures
import lzma
import random
import struct

import pytest

import osu_orz
from osu_orz import HeaderInfo
from osu_orz import Mode


def number(v: float) -> str:
    # as osu!stable prints floats: 7 significant digits, no trailing zeros
    return format(v, ".7g")


def replay_text(mode: Mode, frames: int = 2000, seed: int = 1) -> bytes:
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


def osr(mode: Mode, data: bytes, mods: int = 0, life: str = "") -> bytes:
    return b"".join([
        struct.pack("<Bi", mode, 20240101),
        osu_string("d41d8cd98f00b204e9800998ecf8427e"),
        osu_string("player"),
        osu_string("0123456789abcdef0123456789abcdef"),
        struct.pack("<6hiHBi", 300, 20, 3, 40, 10, 2, 1234567, 512, 0, mods),
        osu_string(life) if life else b"\x00",
        struct.pack("<qi", 638000000000000000, len(data)),
        data,
        struct.pack("<q", 4242424242),
    ])


@pytest.mark.parametrize("mode", list(Mode))
def test_bare_replay_data_round_trips(mode: Mode) -> None:
    text = replay_text(mode)
    data = replay_data(text)

    info = HeaderInfo(mode, relax=False)

    first = osu_orz.decompress(osu_orz.compress(data, header_info=info))

    # the frames come back exactly, recompressed the way osu! compresses them
    assert text_of(first) == text
    # data osu!'s encoder wrote comes back byte for byte
    assert osu_orz.decompress(osu_orz.compress(first, header_info=info)) == first


@pytest.mark.parametrize("mode", list(Mode))
def test_osr_round_trips(mode: Mode) -> None:
    life = "0|1,4000|0.95,8000|0.8,12000|1," if mode != Mode.MANIA else ""
    original = osr(mode, replay_data(replay_text(mode)), life=life)

    first = osu_orz.decompress(osu_orz.compress(original))

    assert osu_orz.decompress(osu_orz.compress(first)) == first
    assert len(first) < len(original) * 2


def test_relax() -> None:
    info = HeaderInfo(Mode.OSU, relax=True)
    first = osu_orz.decompress(osu_orz.compress(replay_data(replay_text(Mode.OSU)), header_info=info))

    assert osu_orz.decompress(osu_orz.compress(first, header_info=info)) == first


def test_header_info_only_stands_in_for_a_header() -> None:
    data = replay_data(replay_text(Mode.OSU))

    # an .osr says what it is itself
    with pytest.raises(osu_orz.OrzError):
        osu_orz.compress(osr(Mode.OSU, data), header_info=HeaderInfo(Mode.OSU, relax=False))
    # bare replay data does not
    with pytest.raises(osu_orz.OrzError):
        osu_orz.compress(data)
    with pytest.raises(osu_orz.OrzError):
        osu_orz.compress(replay_data(replay_text(Mode.MANIA)), header_info=HeaderInfo(Mode.MANIA, relax=True))
    with pytest.raises(ValueError):
        osu_orz.compress(data, header_info=HeaderInfo(7, relax=False))


def test_compresses() -> None:
    data = replay_data(replay_text(Mode.OSU, frames=20000))

    assert len(osu_orz.compress(data, header_info=HeaderInfo(Mode.OSU, relax=False))) < len(data) / 2


def test_bad_input() -> None:
    with pytest.raises(osu_orz.OrzError):
        osu_orz.compress(b"not a replay" * 20)
    with pytest.raises(osu_orz.OrzError):
        osu_orz.decompress(b"not an orz file")

    orz = osu_orz.compress(replay_data(replay_text(Mode.OSU)), header_info=HeaderInfo(Mode.OSU, relax=False))
    with pytest.raises(osu_orz.OrzError):
        osu_orz.compress(orz)
    for cut in (1, 2, 8, len(orz) // 2):
        with pytest.raises(osu_orz.OrzError):
            osu_orz.decompress(orz[:cut])


def test_threads() -> None:
    data = [replay_data(replay_text(m, seed=s)) for m in Mode for s in range(3)]
    infos = [HeaderInfo(m, relax=False) for m in Mode for _ in range(3)]
    expected = [osu_orz.compress(d, header_info=i) for d, i in zip(data, infos)]

    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        got = list(pool.map(lambda d, i: osu_orz.compress(d, header_info=i), data, infos))
        back = list(pool.map(osu_orz.decompress, got))

    assert got == expected
    assert back == [osu_orz.decompress(o) for o in expected]
