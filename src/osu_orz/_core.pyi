from collections.abc import Sequence


class OrzError(ValueError):
    pass

FORMAT_VERSION: int = 0

def compress_osr(data: bytes, check_round_trip: bool, device_hints: Sequence[bytes]) -> tuple[bytes, bytes | None, int | None, int]: ...

def compress_replay_data(data: bytes, mode: int, check_round_trip: bool, device_hints: Sequence[bytes]) -> tuple[bytes, bytes | None, int | None, int]: ...

def decompress(data: bytes, skip_crc: bool) -> bytes: ...

def device_segments(data: bytes) -> tuple[list[dict[str, object]], list[dict[str, object]]]: ...

def orz_device(data: bytes) -> bytes | None: ...
