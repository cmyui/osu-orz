# osu-orz

Python bindings for [ORZ](https://github.com/rumoi/osu_replay_zip), a lossless compression format for osu! replays.

```python
import osu_orz

orz = osu_orz.compress(osr_bytes).compressed_bytes  # an .osr file
assert osu_orz.decompress(orz) == osr_bytes

# bare replay data (the LZMA stream osu! stores for a score) has no header, so say what it is
orz = osu_orz.compress(replay_data, mode=osu_orz.Mode.OSU_RELAX).compressed_bytes
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
`mode` that is not a `Mode` raises `ValueError`. The functions release the GIL, so threads compress in parallel.

`decompress(orz, skip_crc=True)` gives back what a file decodes to even when it fails its CRC check (damaged, or
written by an incompatible build), to recover what is left of it.

## Devices

osu!standard's coder (osu!, and osu!catch with Relax) codes cursor positions on a model of the device that made them,
which the encoder finds by searching the frames. `compress` returns it as `result.device`, and `osu_orz.device(orz)`
reads it back from an `.orz` without decoding the frames:

```python
result = osu_orz.compress(osr_bytes, device_hints=[earlier.device])
result.device.data  # bytes to store, and to pass back as a hint
result.hint_used    # 0: the encoder took the first hint and skipped its device search

match result.device.x[0].model:
    case osu_orz.Mouse(sensitivity=sensitivity, poll_rate=poll_rate):
        ...
    case osu_orz.Absolute(mapping=osu_orz.Mapping.WINDOW, span=span, speed=speed):
        ...
```

`result.device` is None when the frames are not coded on a device model; `result.coding` says how they are coded
(stored as given, the osu!taiko, osu!catch and osu!mania coder, decimal text, or osu!'s autopilot path).

Each axis has one `AxisSegment`, or more when the setup changed during the replay (window moved, device swapped). Its
`model` is the model that reproduces the positions, which only partly says what hardware made them, and holds only that
model's parameters:

| `model` | Positions |
|---|---|
| `Rational(a, b, d)` | on the OS cursor's lattice, `(a * k + b) / d` for whole `k`: mostly raw input off, from a mouse or a tablet |
| `Mouse(sensitivity, poll_rate, playfield)` | from a device that reports movement |
| `Absolute(mapping, span, speed, window_half, origin, x87, playfield)` | from a device that reports where it points (a tablet or touch screen), mapped onto the window or the desktop |
| `Text()` | not on a model: coded as their decimal text |

`playfield` is where the playfield sits in osu!'s window, as `Playfield(scale, offset, unrounded_sub)`: a position of
window pixels is `(pixels - offset) / scale` on the playfield. The floats are the codec's float32s, each as the
shortest decimal that reads back as it; `data` holds them exactly. These types compare, hash and print by their fields.

`device_hints` takes the devices of the player's earlier replays, most likely first. The first that still fits the
replay is used and the device search is skipped (`hint_used` says which). The search can find a hint's device too, so
compare devices to tell whether a replay's device is a hint's. Hints never change what `decompress` gives back. A hint
that is not a device raises `OrzError`. `data` is the device as `.orz` files store it, so hint only with devices from
the same `FORMAT_VERSION`.

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
