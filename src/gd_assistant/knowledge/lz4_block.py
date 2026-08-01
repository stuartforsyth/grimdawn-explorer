"""Pure-Python LZ4 *block* decompressor.

Grim Dawn compresses `.arz` record payloads and `.arc` file parts with raw LZ4
block compression (no frame header). We implement decompression ourselves so the
app has **zero third-party runtime dependencies** for reading game data — it must
keep working even if external LZ4 bindings or GD-specific tools are unmaintained
(SPEC §6.2).

Reference: the LZ4 block format — a stream of sequences, each `[token]
[literals...] [2-byte little-endian match offset] [match copy]`. The token's high
nibble is the literal length, low nibble is `match_length - 4`; a nibble value of
15 means "read extra length bytes (0..255 each) until a byte < 255". The final
sequence is literals-only with no match. See https://github.com/lz4/lz4 (block
format doc).
"""

from __future__ import annotations


def decompress(src: bytes, expected_size: int) -> bytes:
    """Decompress an LZ4 block into exactly `expected_size` bytes.

    `expected_size` is known from the container (record/part decompressed length),
    which also gives us a clean, unambiguous termination condition.
    """
    out = bytearray()
    src_len = len(src)
    i = 0

    while i < src_len:
        token = src[i]
        i += 1

        # --- literals ---
        lit_len = token >> 4
        if lit_len == 15:
            while True:
                b = src[i]
                i += 1
                lit_len += b
                if b != 0xFF:
                    break
        out += src[i:i + lit_len]
        i += lit_len

        # The last sequence is literals-only; end there.
        if len(out) >= expected_size or i >= src_len:
            break

        # --- match ---
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        if offset == 0:
            raise ValueError("invalid LZ4 stream: zero match offset")

        match_len = (token & 0x0F) + 4
        if (token & 0x0F) == 15:
            while True:
                b = src[i]
                i += 1
                match_len += b
                if b != 0xFF:
                    break

        start = len(out) - offset
        if start < 0:
            raise ValueError("invalid LZ4 stream: match offset before output start")

        if offset >= match_len:
            # Non-overlapping: a single slice copy (fast path).
            out += out[start:start + match_len]
        else:
            # Overlapping copy must proceed byte-by-byte.
            for k in range(match_len):
                out.append(out[start + k])

    if len(out) != expected_size:
        raise ValueError(
            f"LZ4 decompress size mismatch: got {len(out)}, expected {expected_size}"
        )
    return bytes(out)
