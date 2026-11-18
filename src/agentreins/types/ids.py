"""Identifiers: UUIDv7 strings (RFC 9562), unique and sortable by creation time.

Python 3.14+ provides ``uuid.uuid7()``; older versions use the small fallback below.
"""

import os
import sys
import time
import uuid

_MS_MASK = (1 << 48) - 1
_RAND_B_MASK = (1 << 62) - 1


def _uuid7_fallback(now_ns: int | None = None) -> uuid.UUID:
    """Build a UUIDv7: 48-bit Unix milliseconds, version 7, RFC 4122 variant, 74 random bits."""
    ms = (time.time_ns() if now_ns is None else now_ns) // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")  # 80 random bits; 74 are used
    rand_a = rand >> 68  # 12 bits
    rand_b = rand & _RAND_B_MASK  # 62 bits
    value = (ms & _MS_MASK) << 80 | 0x7 << 76 | rand_a << 64 | 0b10 << 62 | rand_b
    return uuid.UUID(int=value)


if sys.version_info >= (3, 14):

    def new_id() -> str:
        """Return a new UUIDv7 as a string."""
        return str(uuid.uuid7())

else:

    def new_id() -> str:
        """Return a new UUIDv7 as a string."""
        return str(_uuid7_fallback())
