from __future__ import annotations

import struct
import sys

HEADER = struct.Struct("!Q")


def encode_frame(data: bytes) -> bytes:
    return HEADER.pack(len(data)) + data


def main() -> int:
    data = sys.stdin.buffer.read()
    sys.stdout.buffer.write(encode_frame(data))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
