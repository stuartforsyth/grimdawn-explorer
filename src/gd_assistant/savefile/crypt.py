"""Seed-XOR obfuscation used by Grim Dawn `.gdc` save files.

The scheme (verified against retail saves, SPEC §5.1):

    seed  = u32_at(0) ^ 0x55555555     # the key state *starts* at the seed
    table = 256 entries, k = rotate_right_1(k) then k *= 39916801 (mod 2**32)

Every read XORs the raw little-endian value with the current key, then advances the
key using the **raw (still-encrypted)** bytes just consumed: `key ^= table[b]`.

Two consequences drive the whole save-writing design:

* Key evolution depends only on *which* ciphertext bytes were consumed, never on how
  they were grouped into reads. Skipping an unknown block by its length prefix keeps
  the key in sync, so reading tolerates incomplete format coverage (`skip()`).
* Reads are wordwise, not bytewise: a `u32` XORs all four bytes against the key
  *before* advancing it. Decoding therefore depends on knowing each read's width, so
  there is no shortcut for re-encrypting regions we cannot parse (SPEC §5.3).
"""

from __future__ import annotations

import struct

SEED_MASK = 0x55555555
KEY_MULTIPLIER = 39916801  # 11! + 1
UINT32 = 0xFFFFFFFF
MAGIC = 0x58434447  # 'GDCX'


def build_table(seed: int) -> tuple[int, ...]:
    """Build the 256-entry key table derived from `seed`."""
    table = []
    k = seed
    for _ in range(256):
        k = ((k >> 1) | (k << 31)) & UINT32  # rotate right 1
        k = (k * KEY_MULTIPLIER) & UINT32
        table.append(k)
    return tuple(table)


class GdcReader:
    """Sequential reader over an obfuscated `.gdc` byte stream.

    Construction consumes the 4-byte seed header, leaving the cursor at the magic.
    """

    def __init__(self, data: bytes) -> None:
        if len(data) < 4:
            raise ValueError("gdc stream too short to contain a seed")
        self._data = data
        self.seed = struct.unpack_from("<I", data, 0)[0] ^ SEED_MASK
        self._table = build_table(self.seed)
        self.key = self.seed
        self.pos = 4

    def __len__(self) -> int:
        return len(self._data)

    @property
    def remaining(self) -> int:
        return len(self._data) - self.pos

    def _take(self, n: int) -> bytes:
        """Consume `n` raw bytes, advancing the key by each of them."""
        if self.pos + n > len(self._data):
            raise ValueError(
                f"gdc stream truncated: wanted {n} bytes at {self.pos}, "
                f"only {self.remaining} left"
            )
        raw = self._data[self.pos : self.pos + n]
        self.pos += n
        for b in raw:
            self.key ^= self._table[b]
        return raw

    def skip(self, n: int) -> None:
        """Advance `n` bytes without decoding.

        Safe at any read width because key evolution is granularity-independent —
        this is what lets the parser step over blocks it doesn't model.
        """
        self._take(n)

    def u8(self) -> int:
        key = self.key
        return self._take(1)[0] ^ (key & 0xFF)

    def u16(self) -> int:
        key = self.key
        return struct.unpack("<H", self._take(2))[0] ^ (key & 0xFFFF)

    def u32(self) -> int:
        key = self.key
        return struct.unpack("<I", self._take(4))[0] ^ key

    def i32(self) -> int:
        value = self.u32()
        return value - (1 << 32) if value & 0x80000000 else value

    def f32(self) -> float:
        return struct.unpack("<f", struct.pack("<I", self.u32()))[0]

    def bool8(self) -> bool:
        return self.u8() != 0

    def ascii_str(self) -> str:
        """Length-prefixed single-byte string (record paths, text tags)."""
        n = self.u32()
        self._guard_len(n)
        return bytes(self.u8() for _ in range(n)).decode("latin1")

    def wide_str(self) -> str:
        """Length-prefixed UTF-16LE string (the character name)."""
        n = self.u32()
        self._guard_len(n * 2)
        return "".join(chr(self.u8() | (self.u8() << 8)) for _ in range(n))

    def _guard_len(self, n: int) -> None:
        """Reject absurd lengths early — they mean we've lost stream alignment."""
        if n < 0 or n > self.remaining:
            raise ValueError(
                f"implausible string length {n} at offset {self.pos} "
                f"({self.remaining} bytes remain) — stream misaligned"
            )

    def next_u32(self) -> int:
        """Read a `u32` that is consumed but does **not** advance the key.

        Grim Dawn uses this for block lengths and end-of-block markers. It is the
        reason a naive linear pass desyncs: four bytes go by without feeding the key,
        so any region containing one cannot be skipped blindly (see `skip`).
        """
        if self.pos + 4 > len(self._data):
            raise ValueError(f"gdc stream truncated reading length at {self.pos}")
        value = struct.unpack_from("<I", self._data, self.pos)[0] ^ self.key
        self.pos += 4
        return value

    def skip_to(self, end: int) -> None:
        """Advance to `end`, feeding the intervening bytes through the key."""
        if end < self.pos:
            raise ValueError(f"cannot skip backwards from {self.pos} to {end}")
        self._take(end - self.pos)

    def block_start(self) -> tuple[int, int]:
        """Read a block header, returning `(block_id, end_offset)`.

        The id advances the key; the length does not (`next_u32`).
        """
        block_id = self.u32()
        length = self.next_u32()
        if length < 0 or self.pos + length > len(self._data):
            raise ValueError(
                f"block {block_id} at {self.pos - 8} claims {length} bytes, "
                f"only {self.remaining} remain"
            )
        return block_id, self.pos + length

    def block_end(self, end: int) -> None:
        """Validate a block's terminator, confirming the key stayed in sync."""
        if self.pos != end:
            raise ValueError(f"block ended at {self.pos}, expected {end}")
        marker = self.next_u32()
        if marker != 0:
            raise ValueError(f"block end marker was {marker}, expected 0 (key desync)")

    def try_skip_block(self, end: int) -> bool:
        """Skip a block wholesale, returning False if it turns out to nest.

        A nested block contains its own `next_u32` fields, which a bulk skip would
        wrongly feed to the key — that shows up immediately as a non-zero terminator,
        so this is self-checking rather than silently corrupting the parse.
        """
        self.skip_to(end)
        return self.next_u32() == 0

    def read_magic(self) -> int:
        """Read and validate the `GDCX` magic, returning the format version."""
        magic = self.u32()
        if magic != MAGIC:
            raise ValueError(
                f"not a Grim Dawn save: magic {magic:#010x} != {MAGIC:#010x} ('GDCX')"
            )
        return self.u32()


class GdcWriter:
    """Builds an obfuscated `.gdc` stream — the exact inverse of `GdcReader`.

    Block lengths are back-filled once a block's body is written. That is safe
    precisely because length fields do not advance the key (`next_u32`): rewriting
    those four bytes later cannot disturb the keystream for anything after them.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._table = build_table(seed)
        self.key = seed
        self.out = bytearray(struct.pack("<I", seed ^ SEED_MASK))
        self._pending: list[tuple[int, int, int]] = []  # (length_slot, body_start, key)

    def _emit(self, raw: bytes) -> None:
        self.out.extend(raw)
        for b in raw:
            self.key ^= self._table[b]

    def u8(self, value: int) -> None:
        self._emit(bytes([(value ^ self.key) & 0xFF]))

    def u16(self, value: int) -> None:
        self._emit(struct.pack("<H", (value ^ self.key) & 0xFFFF))

    def u32(self, value: int) -> None:
        self._emit(struct.pack("<I", (value ^ self.key) & 0xFFFFFFFF))

    def i32(self, value: int) -> None:
        self.u32(value & 0xFFFFFFFF)

    def f32(self, value: float) -> None:
        self.u32(struct.unpack("<I", struct.pack("<f", value))[0])

    def bool8(self, value: bool) -> None:
        self.u8(1 if value else 0)

    def next_u32(self, value: int) -> None:
        """Write a `u32` that is emitted but does **not** advance the key."""
        self.out.extend(struct.pack("<I", (value ^ self.key) & 0xFFFFFFFF))

    def ascii_str(self, text: str) -> None:
        self.u32(len(text))
        for ch in text.encode("latin1"):
            self.u8(ch)

    def wide_str(self, text: str) -> None:
        self.u32(len(text))
        for ch in text:
            code = ord(ch)
            self.u8(code & 0xFF)
            self.u8((code >> 8) & 0xFF)

    def raw_bytes(self, data: bytes) -> None:
        """Write already-plaintext bytes as a run of `u8` values."""
        for b in data:
            self.u8(b)

    def block_start(self, block_id: int) -> None:
        self.u32(block_id)
        # The length is written against the key live *now*; record it so the
        # back-fill re-encodes against the same value.
        self._pending.append((len(self.out), len(self.out) + 4, self.key))
        self.out.extend(b"\0\0\0\0")

    def block_end(self) -> None:
        if not self._pending:
            raise ValueError("block_end without a matching block_start")
        slot, body_start, key_at_slot = self._pending.pop()
        length = len(self.out) - body_start
        self.out[slot : slot + 4] = struct.pack(
            "<I", (length ^ key_at_slot) & 0xFFFFFFFF
        )
        self.next_u32(0)

    def getvalue(self) -> bytes:
        if self._pending:
            raise ValueError(f"{len(self._pending)} block(s) left unclosed")
        return bytes(self.out)
