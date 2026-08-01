"""Tests for the native .arz/.arc readers and the pure-Python LZ4 decompressor.

The LZ4 and synthetic-.arz tests are self-contained. `test_real_*` run only when a
real Grim Dawn install is discoverable (or GD_INSTALL_DIR is set), so they exercise
retail data locally but skip cleanly in CI.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from gd_assistant.knowledge import lz4_block
from gd_assistant.knowledge.arz import ArzDatabase


# --------------------------------------------------------------------------- #
# LZ4 block decompression
# --------------------------------------------------------------------------- #
def test_lz4_literals_only_short():
    # token high nibble = literal length, no match.
    block = bytes([0x30]) + b"abc"
    assert lz4_block.decompress(block, 3) == b"abc"


def test_lz4_literals_only_long_length_extension():
    # literal length 20 needs the 15 + extension-byte encoding.
    payload = bytes(range(20))
    block = bytes([0xF0, 20 - 15]) + payload
    assert lz4_block.decompress(block, 20) == payload


def test_lz4_non_overlapping_match():
    # "abcd" literals, then a 4-byte match at offset 4 -> "abcdabcd".
    block = bytes([0x40]) + b"abcd" + bytes([0x04, 0x00])
    assert lz4_block.decompress(block, 8) == b"abcdabcd"


def test_lz4_overlapping_match():
    # "a" literal, then match offset 1 length 4 (offset < length -> byte-by-byte).
    block = bytes([0x10]) + b"a" + bytes([0x01, 0x00])
    assert lz4_block.decompress(block, 5) == b"aaaaa"


def test_lz4_size_mismatch_raises():
    with pytest.raises(ValueError):
        lz4_block.decompress(bytes([0x30]) + b"abc", 99)


# --------------------------------------------------------------------------- #
# Synthetic .arz round-trip (container + field decode), no compressor needed:
# an LZ4 "literals-only" block is trivial to author by hand.
# --------------------------------------------------------------------------- #
def _lz4_store(payload: bytes) -> bytes:
    """Encode `payload` as a single literals-only LZ4 block."""
    n = len(payload)
    if n < 15:
        return bytes([n << 4]) + payload
    remaining = n - 15
    ext = bytearray()
    while remaining >= 255:
        ext.append(255)
        remaining -= 255
    ext.append(remaining)
    return bytes([0xF0]) + bytes(ext) + payload


def _build_arz() -> bytes:
    strings = ["records/test/foo.dbr", "Class", "TestItem", "levelRequirement"]

    # payload: Class(string idx2), levelRequirement(int 70)
    payload = b""
    payload += struct.pack("<HHII", 2, 1, 1, 2)   # string field -> strings[2]
    payload += struct.pack("<HHIi", 0, 1, 3, 70)  # int field    -> 70
    block = _lz4_store(payload)

    record_region = block
    rec_type = b"TestClass"
    entry = struct.pack("<II", 0, len(rec_type)) + rec_type
    entry += struct.pack("<III", 0, len(block), len(payload))  # offset, comp, decomp
    entry += struct.pack("<Q", 0)                               # filetime

    rec_start = 24 + len(record_region)
    rec_size = len(entry)
    str_start = rec_start + rec_size

    str_table = struct.pack("<I", len(strings))
    for s in strings:
        b = s.encode("latin-1")
        str_table += struct.pack("<I", len(b)) + b

    header = struct.pack("<HH", 2, 3) + struct.pack(
        "<5I", rec_start, rec_size, 1, str_start, len(str_table)
    )
    return header + record_region + entry + str_table


def test_synthetic_arz_roundtrip():
    db = ArzDatabase(_build_arz())
    assert db.record_count == 1
    (rec,) = list(db.records())
    assert rec.path == "records/test/foo.dbr"
    assert rec.record_class == "TestClass"
    assert rec.fields == {"Class": "TestItem", "levelRequirement": 70}


def test_synthetic_arz_prefix_filter():
    db = ArzDatabase(_build_arz())
    assert list(db.records(path_prefix="records/other/")) == []
    assert len(list(db.records(path_prefix="records/test/"))) == 1


# --------------------------------------------------------------------------- #
# Real retail data (skipped when no install is found)
# --------------------------------------------------------------------------- #
def _find_install() -> Path | None:
    env = os.environ.get("GD_INSTALL_DIR")
    if env and (Path(env) / "database" / "database.arz").exists():
        return Path(env)
    default = Path.home() / ".steam/steam/steamapps/common/Grim Dawn"
    return default if (default / "database" / "database.arz").exists() else None


@pytest.mark.skipif(_find_install() is None, reason="no Grim Dawn install found")
def test_real_database_decodes_all():
    install = _find_install()
    db = ArzDatabase.open(install / "database" / "database.arz")
    assert db.record_count > 10_000
    count = sum(1 for _ in db.records(path_prefix="records/items/"))
    assert count > 100


@pytest.mark.skipif(_find_install() is None, reason="no Grim Dawn install found")
def test_real_text_tags_resolve():
    from gd_assistant.knowledge.arc import load_text_tags

    install = _find_install()
    tags = load_text_tags(install / "resources" / "Text_EN.arc")
    assert len(tags) > 1000
    # a stable base-game tag
    assert tags.get("tagBoosterBL_B01") == "Mandate of the Black Legion"
