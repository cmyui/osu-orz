# osu-orz

Python bindings for [ORZ](https://github.com/rumoi/osu_replay_zip), a lossless compression format for osu! replays.

```python
import osu_orz

orz = osu_orz.compress(osr_bytes)          # an .osr file
assert osu_orz.decompress(orz) == osr_bytes

# bare replay data (the LZMA stream osu! stores for a score) has no header, so say what it is
orz = osu_orz.compress(replay_data, osu_orz.Mode.OSU, relax=True)
assert osu_orz.decompress(orz) == replay_data
```

## What comes back

`decompress` rebuilds the input `compress` was given:

- the replay frames exactly;
- the `.osr` fields around them exactly (header, life bar, timestamp, score id);
- the replay data's LZMA bytes, compressed again the way osu! compresses them. Replay data osu! wrote comes back byte
  for byte. Data written by other software comes back with the same frames, compressed like osu! would.

Errors raise `osu_orz.OrzError` (a `ValueError`): input that is not a replay, or an `.orz` that is damaged, cut short or
made by a newer format version. Both functions release the GIL, so threads compress in parallel.

## Format stability

ORZ is format version 0 (`osu_orz.FORMAT_VERSION`) and can still change incompatibly between releases. Until the format
is versioned, decode an `.orz` with the osu-orz version that wrote it.

## Platform

Linux on x86-64 (SSE 4.2) with CPython 3.12 or newer. The codec uses x86 CRC instructions, so other architectures do
not build yet.

## Building from source

```sh
git clone --recursive https://github.com/cmyui/osu-orz
pip install './osu-orz[test]'
pytest osu-orz/tests
```

This needs a C++20 compiler (GCC 11 or newer, or Clang). The build compiles the codec with `-ffp-contract=off`:
`.orz` files only decode when every build does its float maths exactly as written, so do not build it with
`-ffast-math`.

## License

The bindings are MIT licensed. The ORZ codec in `extern/osu_replay_zip` is rumoi's.
