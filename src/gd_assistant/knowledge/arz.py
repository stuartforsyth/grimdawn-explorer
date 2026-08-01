"""Native reader for Grim Dawn `.arz` database files (SPEC §6.1/§6.2).

An `.arz` packs every game record (items, skills, constellations, ...) that the
modding tools otherwise export as individual `.dbr` text files. Reading it
directly — with no external extractor — is the app's primary data source, so it
keeps working across patches and outlives any third-party tool.

Format (verified against retail `database/database.arz`, magic=2 version=3):

    Header (24 bytes, little-endian):
        u16 magic (== 2)          u16 version (== 3)
        u32 record_table_start    u32 record_table_size
        u32 record_table_entries  u32 string_table_start
        u32 string_table_size
      (record_table_start + record_table_size == string_table_start, confirmed.)

    Record-data region: bytes [24 .. record_table_start); record offsets below
      are relative to the end of the 24-byte header.

    String table @ string_table_start:  u32 count, then count × (u32 len, bytes)

    Record table @ record_table_start: `record_table_entries` variable-length rows
        u32 name_id (-> string table: the record path, e.g. records/items/.../x.dbr)
        u32 type_len, bytes[type_len]  (record class, e.g. "ArmorProtective")
        u32 offset (into record-data region), u32 compressed_len, u32 decompressed_len
        u64 filetime

    Record payload (LZ4-block compressed -> decompressed_len bytes): a stream of
        u16 value_type, u16 value_count, u32 key_id (-> string table: field name),
        then value_count × u32 raw values, decoded per value_type:
            0 int32   1 float32(bit-reinterpret)   2 string(-> string table)   3 bool
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from gd_assistant.knowledge import lz4_block

HEADER_SIZE = 24
_ARZ_MAGIC = 2
_ARZ_VERSION = 3


@dataclass
class ArzRecord:
    """One decoded record: its `.dbr` path, class name, and fields."""

    path: str                       # e.g. "records/items/.../foo.dbr"
    record_class: str               # e.g. "ArmorProtective"
    fields: dict[str, object]       # field name -> value (scalar) or list of values


class ArzDatabase:
    """Read-only, lazily-iterable view over an `.arz` file."""

    def __init__(self, raw: bytes) -> None:
        self._raw = raw
        magic, version = struct.unpack_from("<HH", raw, 0)
        if magic != _ARZ_MAGIC or version != _ARZ_VERSION:
            raise ValueError(f"unrecognised .arz header: magic={magic} version={version}")
        (
            self._rec_start,
            self._rec_size,
            self._rec_count,
            self._str_start,
            self._str_size,
        ) = struct.unpack_from("<5I", raw, 4)
        self._strings: list[str] = self._read_string_table()

    @classmethod
    def open(cls, path: str | Path) -> ArzDatabase:
        return cls(Path(path).read_bytes())

    # -- public API -------------------------------------------------------
    @property
    def record_count(self) -> int:
        return self._rec_count

    def records(self, path_prefix: str | None = None) -> Iterator[ArzRecord]:
        """Yield decoded records, optionally filtered by `.dbr` path prefix.

        Filtering by prefix (e.g. "records/items/") lets the KB builder skip the
        ~34k full decode and only decompress records it cares about.
        """
        raw = self._raw
        pos = self._rec_start
        end = self._rec_start + self._rec_size
        for _ in range(self._rec_count):
            name_id, type_len = struct.unpack_from("<II", raw, pos)
            pos += 8
            record_class = raw[pos:pos + type_len].decode("latin-1")
            pos += type_len
            offset, comp_len, decomp_len = struct.unpack_from("<III", raw, pos)
            pos += 12
            pos += 8  # u64 filetime (unused)

            name = self._strings[name_id]
            if path_prefix is not None and not name.startswith(path_prefix):
                continue

            data_start = HEADER_SIZE + offset
            comp = raw[data_start:data_start + comp_len]
            payload = lz4_block.decompress(comp, decomp_len)
            yield ArzRecord(name, record_class, self._decode_fields(payload))
        # sanity: consumed exactly the record table
        assert pos == end, f"record table under/over-read: pos={pos} end={end}"

    # -- internals --------------------------------------------------------
    def _read_string_table(self) -> list[str]:
        raw = self._raw
        pos = self._str_start
        (count,) = struct.unpack_from("<I", raw, pos)
        pos += 4
        strings: list[str] = []
        for _ in range(count):
            (slen,) = struct.unpack_from("<I", raw, pos)
            pos += 4
            strings.append(raw[pos:pos + slen].decode("latin-1"))
            pos += slen
        return strings

    def _decode_fields(self, payload: bytes) -> dict[str, object]:
        fields: dict[str, object] = {}
        pos = 0
        n = len(payload)
        while pos < n:
            vtype, vcount = struct.unpack_from("<HH", payload, pos)
            (key_id,) = struct.unpack_from("<I", payload, pos + 4)
            pos += 8
            raw_values = struct.unpack_from(f"<{vcount}I", payload, pos)
            pos += 4 * vcount

            key = self._strings[key_id]
            values = [self._decode_value(vtype, v) for v in raw_values]
            fields[key] = values[0] if vcount == 1 else values
        return fields

    def _decode_value(self, vtype: int, raw: int) -> object:
        if vtype == 0:      # int32
            return raw if raw < 0x8000_0000 else raw - 0x1_0000_0000
        if vtype == 1:      # float32 (reinterpret the 32 bits)
            return struct.unpack("<f", struct.pack("<I", raw))[0]
        if vtype == 2:      # string (index into the shared string table)
            return self._strings[raw]
        if vtype == 3:      # bool
            return bool(raw)
        raise ValueError(f"unknown .arz value type {vtype}")
