# osu-orz

Python bindings for [ORZ](https://github.com/rumoi/osu_replay_zip), a lossless compression format for osu! replays.

```python
import osu_orz

orz = osu_orz.compress(osr_bytes)  # an .osr file
assert osu_orz.decompress(orz) == osr_bytes

# bare replay data (the LZMA stream osu! stores for a score) has no header, so say what it is
orz = osu_orz.compress(replay_data, mode=osu_orz.Mode.OSU_RELAX)
assert osu_orz.decompress(orz) == replay_data
```

## Modes

`compress` reads an `.osr`'s game mode and Relax from its header. Bare replay data needs `mode` in place of the header,
and an `.osr` must not be given one, so the two can never disagree.

| `Mode` | Replay |
|---|---|
| `OSU`, `TAIKO`, `CATCH`, `MANIA` | the game mode, without Relax |
| `OSU_RELAX`, `TAIKO_RELAX`, `CATCH_RELAX` | the game mode with Relax (osu!mania has none) |

The values are the mode numbers ORZ files store. Autopilot replays are `OSU`: the encoder recognises the autopilot
path from the frames itself. The mode picks the coder and its priors, so a wrong mode only makes the `.orz` bigger: the
frames come back the same under every mode, and replay data osu! wrote comes back byte for byte.

## What comes back

`decompress` rebuilds the input `compress` was given:

- the replay frames exactly;
- the `.osr` fields around them exactly (header, life bar, timestamp, score id);
- the replay data's LZMA bytes, compressed again the way osu! compresses them. Replay data osu! wrote comes back byte
  for byte. Data written by other software comes back with the same frames, compressed like osu! would.

Some replay data is stored as it is, and comes back byte for byte:

- data the codec can not code as frames (not LZMA, or text that is not osu!'s frames);
- data whose coded frames would be no smaller than its LZMA;
- with `check_round_trip=True`, data whose coded frames do not decode back to it. `compress` then decodes what it wrote
  before returning it, which is slower but keeps a coding bug from turning into a replay that decodes wrong.

Errors raise `osu_orz.OrzError` (a `ValueError`): an `.osr` given a `mode`, anything else without one that is not an
`.osr`, an `.orz` given to `compress`, or an `.orz` that is damaged, cut short or made by a newer format version. A
`mode` that is not a `Mode` raises `ValueError`. Both functions release the GIL, so threads compress in parallel.

`decompress(orz, skip_crc=True)` gives back what a file decodes to even when it fails its CRC check (damaged, or
written by an incompatible build), to recover what is left of it.

## Format stability

ORZ is format version 0 (`osu_orz.FORMAT_VERSION`) and can still change incompatibly between releases. Until the format
is versioned, decode an `.orz` with the osu-orz version that wrote it.

## Platform

CPython 3.12 or newer, on Linux on x86-64 (SSE 4.2) or arm64, or on macOS 26 or newer on arm64. The codec uses each
architecture's CRC instructions, and Apple's C++ library parses floats with `std::from_chars` only from macOS 26 on.

## Building from source

```sh
git clone --recursive https://github.com/cmyui/osu-orz
pip install './osu-orz[test]'
pytest osu-orz/tests
```

This needs a C++20 compiler (GCC 11 or newer, or Clang). The build compiles the codec with `-ffp-contract=off`:
`.orz` files only decode when every build does its float maths exactly as written, so do not build it with
`-ffast-math`.

## Releasing

Bump `version` in `pyproject.toml` and merge to `main`. CI then builds and tests the wheel, tags `v{version}`, makes a
GitHub release and publishes to PyPI.

## License

MIT. The ORZ codec in `extern/osu_replay_zip` is MIT licensed by rumoi; wheels include both licenses.
