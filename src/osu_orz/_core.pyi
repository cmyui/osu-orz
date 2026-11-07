class OrzError(ValueError):
    pass

FORMAT_VERSION: int = 0

def compress_osr(data: bytes, check_round_trip: bool) -> bytes: ...

def compress_replay_data(data: bytes, mode: int, check_round_trip: bool) -> bytes: ...

def decompress(data: bytes, skip_crc: bool) -> bytes: ...
