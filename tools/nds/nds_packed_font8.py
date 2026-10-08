'''NDS body-font glyph packing: 8 bytes per glyph, external global ids kept.

Each glyph owns one 8-byte record at offset id*8: one byte per ink row, one bit
per pixel, MSB = leftmost column. Slot 0 and every unassigned numbered slot
(low-byte F8 slots and the private fixed-caption namespace from 0xE00 up
included) stay an all-zero record, so a zero record unambiguously means "no
glyph here" and a glyph may never be empty. No subset renumbering happens
anywhere: ids are the external atlas ids already used by the current
consumers, and expanding is by global id only.

Glyph pixels are read from the existing native 8px asset through
nds_small_speaker.native8_pixels (BDF sha guarded); this module never resamples,
restyles, adds shadow or changes the pixel container. The pack is data only:
no ARM code, no allocator, no VRAM model and no ROM write. expand_glyph returns
the same 8x16 pixels plus the exact two 8x8 4bpp tiles (32 ink bytes, 32
transparent bytes) that native8_atlas stores for that global id, so a future
loader can expand full coverage on demand instead of keeping the 64-byte-per-
glyph atlas in RAM.

API: pack_glyphs(mapping, slot_limit) -> (pack, proof); expand_glyph(pack, id)
returns pixels plus both 4bpp tiles; expand_atlas(pack, slot_limit) rebuilds the
native8_atlas byte layout; extend_mapping/free_slots append new ids in the next
free slots without ever moving the existing ones.
'''
from pathlib import Path
import sys, hashlib
from typing import NamedTuple
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'tools') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tools'))
from rs_format import FormatError
from nds_small_speaker import (FONT as NATIVE8_FONT, FONT_SHA as NATIVE8_FONT_SHA,
    native8_pixels as _native8_pixels)

ROWS = 8
COLS = 8
CONTAINER_PIXELS = 128
GLYPH_RECORD_BYTES = ROWS
TRANSPARENT = 1
FACE = 4
CLEAR_BYTE = TRANSPARENT | TRANSPARENT << 4
CLEAR_TILE = bytes([CLEAR_BYTE]) * 32
INK_TILE_BYTES = 32
GLYPHS_PER_BLOCK = 32
BLOCK_BYTES = GLYPHS_PER_BLOCK * 2 * INK_TILE_BYTES
BLOCK_CLEAR_OFFSET = GLYPHS_PER_BLOCK * INK_TILE_BYTES
GLYPHS_PER_PAGE = 512
PAGE_BYTES = GLYPHS_PER_PAGE * 2 * INK_TILE_BYTES
RESERVED_LOW_BYTE = 0xF8
RESERVED_NAMESPACE = 0xE00
MAX_SLOT_LIMIT = 4096
CONTRACT = (('container', [8, 16]), ('ink_height', 8), ('advance', 8), ('font_design_size', 8),
            ('source_bitmap_native', True), ('no_resampling', True), ('no_shadow', True),
            ('face_palette_index', FACE))
PACK_FORMAT = dict(row_bits='1 bit per pixel, MSB is the leftmost column', glyph_bytes=GLYPH_RECORD_BYTES,
    id_stride_bytes=GLYPH_RECORD_BYTES, slot0_reserved_blank=True, hole_records_zero=True,
    ink_palette_index=FACE, transparent_palette_index=TRANSPARENT, ink_rows=8,
    transparent_rows_below_ink=8, numbered_slots='1..slot_limit-1, low byte F8 and 0xE00+ excluded',
    external_global_ids=True, subset_reindexing=False)


class ExpandedGlyph(NamedTuple):
    '''8x16 pixels plus the two 4bpp tiles native8_atlas stores for the same id.'''
    pixels: bytes
    ink_tile: bytes
    clear_tile: bytes

    @property
    def tiles(self):
        return self.ink_tile + self.clear_tile


def _require(condition, message):
    if not condition:
        raise FormatError(message)


def _normalise_pixels(pixels):
    _require(isinstance(pixels, (bytes, bytearray, list, tuple)), 'pixels must be a sequence')
    _require(len(pixels) == CONTAINER_PIXELS, 'pixel container must be 8x16')
    return pixels


def validate_slot_limit(slot_limit):
    _require(isinstance(slot_limit, int) and not isinstance(slot_limit, bool), 'slot_limit must be an int')
    _require(2 <= slot_limit <= MAX_SLOT_LIMIT, f'slot_limit outside 2..{MAX_SLOT_LIMIT}')
    return slot_limit


def validate_glyph_id(index, slot_limit):
    validate_slot_limit(slot_limit)
    _require(isinstance(index, int) and not isinstance(index, bool), 'glyph id must be an int')
    _require(index > 0, 'glyph id 0 is the blank fallback slot and cannot hold a glyph')
    _require(index < slot_limit, f'glyph id {index} outside slot_limit {slot_limit}')
    _require(index < RESERVED_NAMESPACE, f'glyph id {index:#x} is inside the private fixed-caption namespace 0xE00+')
    _require(index & 255 != RESERVED_LOW_BYTE, 'glyph id payload collides with raw F8 terminator')
    return index


def validate_render_id(index, slot_limit):
    '''Reads accept 0 (the consumer substitutes 0 for out-of-range ids) but never 0xE00+.'''
    validate_slot_limit(slot_limit)
    _require(isinstance(index, int) and not isinstance(index, bool), 'glyph id must be an int')
    _require(index >= 0, 'glyph id must not be negative')
    _require(index < slot_limit, f'glyph id {index} outside slot_limit {slot_limit}')
    _require(index < RESERVED_NAMESPACE, f'glyph id {index:#x} is inside the private fixed-caption namespace 0xE00+')
    return index


def validate_mapping(mapping, slot_limit):
    '''Return the mapping ordered by id; rejects duplicates, 0, out-of-range and 0xE00+.'''
    validate_slot_limit(slot_limit)
    _require(isinstance(mapping, dict), 'mapping must be a dict')
    _require(mapping, 'empty glyph mapping')
    by_id = {}
    for ch, index in mapping.items():
        _require(isinstance(ch, str) and len(ch) == 1, 'mapping key must be a single character')
        validate_glyph_id(index, slot_limit)
        _require(index not in by_id, f'duplicate glyph id {index} for {by_id.get(index)!r} and {ch!r}')
        by_id[index] = ch
    return {by_id[index]: index for index in sorted(by_id)}


def validate_pixels(pixels, label='glyph', require_ink=True):
    _normalise_pixels(pixels)
    _require(set(pixels) <= {TRANSPARENT, FACE},
        f'{label}: pixels must be face {FACE}/transparent {TRANSPARENT} only')
    _require(not any(v == FACE for v in pixels[ROWS * COLS:]),
        f'{label}: ink must stay inside the upper eight rows')
    if require_ink:
        _require(any(v == FACE for v in pixels), f'{label}: empty glyph (a zero record means no glyph)')
    return pixels


def validate_info(info, label='glyph'):
    '''Enforce every native8 contract key the pixel source reports.'''
    if not info:
        return info
    for key, expected in CONTRACT:
        if key in info:
            actual = info[key]
            same = list(actual) == list(expected) if key == 'container' else actual == expected
            _require(same, f'{label}: {key} contract drift {actual!r}')
    return info


def encode_pixels(pixels, label='glyph'):
    '''8x16 pixels -> 8 packed bytes, MSB first.'''
    validate_pixels(pixels, label)
    return bytes(sum(1 << (COLS - 1 - x) for x in range(COLS) if pixels[y * COLS + x] == FACE) for y in range(ROWS))


def decode_record(record):
    '''8 packed bytes -> 8x16 pixels; below the ink rows everything is transparent.'''
    _require(isinstance(record, (bytes, bytearray)) and len(record) == GLYPH_RECORD_BYTES,
        'packed glyph record must be exactly 8 bytes')
    out = bytearray([TRANSPARENT] * CONTAINER_PIXELS)
    for y in range(ROWS):
        row = record[y]
        for x in range(COLS):
            if row & 1 << (COLS - 1 - x):
                out[y * COLS + x] = FACE
    return bytes(out)


def ink_tile(pixels, require_ink=False):
    '''8 ink rows -> one 8x8 4bpp tile, low nibble is the left pixel.'''
    validate_pixels(pixels, 'glyph', require_ink=require_ink)
    return bytes(pixels[y * COLS + x] | pixels[y * COLS + x + 1] << 4 for y in range(ROWS) for x in range(0, COLS, 2))


def atlas_pages(slot_limit):
    return max(1, (validate_slot_limit(slot_limit) + GLYPHS_PER_PAGE - 1) // GLYPHS_PER_PAGE)


def required_slot_limit(mapping):
    '''max used id + 1: the smallest explicit slot_limit that still fits this mapping.'''
    ordered = validate_mapping(mapping, MAX_SLOT_LIMIT)
    return max(ordered.values()) + 1


def free_slots(mapping, slot_limit):
    '''Assignable ids in external order: 1..0xDFF below slot_limit without used ids and low-byte F8.'''
    validate_slot_limit(slot_limit)
    if mapping:
        validate_mapping(mapping, slot_limit)
    used = set(mapping.values())
    return [i for i in range(1, min(slot_limit, RESERVED_NAMESPACE))
            if i & 255 != RESERVED_LOW_BYTE and i not in used]


def extend_mapping(mapping, new_chars, slot_limit):
    '''Append new chars into free ids; existing ids never move and nothing is compacted.'''
    ordered = validate_mapping(mapping, slot_limit)
    chars = sorted(set(new_chars))
    _require(all(isinstance(c, str) and len(c) == 1 for c in chars), 'new chars must be single characters')
    already = sorted(set(chars) & set(ordered))
    _require(not already, 'new chars already mapped: ' + ''.join(already))
    slots = free_slots(ordered, slot_limit)
    _require(len(slots) >= len(chars), f'only {len(slots)} free ids for {len(chars)} new chars')
    added = {ch: slots[i] for i, ch in enumerate(chars)}
    result = dict(ordered)
    result.update(added)
    _require(all(result[ch] == ordered[ch] for ch in ordered), 'existing glyph ids moved')
    return result, added


def pack_glyphs(mapping, slot_limit, pixel_source=None):
    '''Pack a char->global id mapping. Return (pack, proof); pack holds slot_limit*8 bytes.'''
    ordered = validate_mapping(mapping, slot_limit)
    source = pixel_source or _native8_pixels
    pack = bytearray(slot_limit * GLYPH_RECORD_BYTES)
    glyphs = []
    for ch, index in sorted(ordered.items(), key=lambda kv: kv[1]):
        produced = source(ch)
        pixels, info = produced if isinstance(produced, tuple) and len(produced) == 2 else (produced, {})
        validate_info(info, repr(ch))
        record = encode_pixels(pixels, repr(ch))
        _require(any(record), f'{ch!r}: zero record would be read as an empty slot')
        pack[index * GLYPH_RECORD_BYTES:(index + 1) * GLYPH_RECORD_BYTES] = record
        glyphs.append(dict(char=ch, index=index, record_hex=record.hex(),
            rows=[f'{byte:08b}' for byte in record], ink_pixels=sum(1 for v in pixels if v == FACE),
            pixels_sha256=hashlib.sha256(bytes(pixels)).hexdigest(),
            source_font_DWIDTH=info.get('source_font_DWIDTH')))
    pages = atlas_pages(slot_limit)
    proof = dict(slot_limit=slot_limit, glyph_count=len(glyphs), packed_bytes=len(pack),
        bytes_per_glyph=GLYPH_RECORD_BYTES, atlas_pages=pages, legacy_native8_atlas_bytes=pages * PAGE_BYTES,
        legacy_native8_atlas_bytes_definition='pages*32768 as native8_atlas allocates for the same max id',
        slot0_zero=not any(pack[:GLYPH_RECORD_BYTES]),
        holes=[i for i in range(slot_limit) if not any(pack[i * GLYPH_RECORD_BYTES:(i + 1) * GLYPH_RECORD_BYTES])],
        defined_ids=sorted(g['index'] for g in glyphs), reserved_namespace_start=RESERVED_NAMESPACE,
        glyph_table_sha256=hashlib.sha256(b''.join(bytes.fromhex(g['record_hex']) for g in glyphs)).hexdigest(),
        glyph_index_sha256=hashlib.sha256(''.join(
            f'{g["char"]}\t{g["index"]}\t{g["record_hex"]}\n' for g in glyphs).encode('utf8')).hexdigest(),
        font=dict(path=str(NATIVE8_FONT), sha256=NATIVE8_FONT_SHA), format=dict(PACK_FORMAT), glyphs=glyphs)
    return bytes(pack), proof


def slot_limit_of(pack):
    _require(isinstance(pack, (bytes, bytearray)), 'pack must be bytes')
    _require(len(pack) % GLYPH_RECORD_BYTES == 0, 'pack length must be a whole number of 8-byte records')
    return validate_slot_limit(len(pack) // GLYPH_RECORD_BYTES)


def _limit_for(pack, slot_limit):
    derived = slot_limit_of(pack)
    if slot_limit is None:
        return derived
    validate_slot_limit(slot_limit)
    _require(slot_limit == derived, f'slot_limit {slot_limit} does not match pack length {len(pack)}')
    return derived


def glyph_record(pack, index, slot_limit=None):
    limit = _limit_for(pack, slot_limit)
    validate_render_id(index, limit)
    return bytes(pack[index * GLYPH_RECORD_BYTES:(index + 1) * GLYPH_RECORD_BYTES])


def glyph_defined(pack, index, slot_limit=None):
    return any(glyph_record(pack, index, slot_limit))


def defined_ids(pack, slot_limit=None):
    limit = _limit_for(pack, slot_limit)
    return [i for i in range(limit) if any(pack[i * GLYPH_RECORD_BYTES:(i + 1) * GLYPH_RECORD_BYTES])]


def hole_ids(pack, slot_limit=None):
    limit = _limit_for(pack, slot_limit)
    return [i for i in range(limit) if not any(pack[i * GLYPH_RECORD_BYTES:(i + 1) * GLYPH_RECORD_BYTES])]


def expand_glyph(pack, index, slot_limit=None):
    '''Global id -> 8x16 pixels and the two 4bpp tiles native8_atlas stores for it.'''
    pixels = decode_record(glyph_record(pack, index, slot_limit))
    return ExpandedGlyph(pixels=pixels, ink_tile=ink_tile(pixels), clear_tile=CLEAR_TILE)


def expand_atlas(pack, slot_limit=None):
    '''Rebuild the native8_atlas layout (pages*32768, 32 ids per 2048-byte block) from the pack.'''
    limit = _limit_for(pack, slot_limit)
    atlas = bytearray([CLEAR_BYTE] * (atlas_pages(limit) * PAGE_BYTES))
    for index in defined_ids(pack, limit):
        if index >= RESERVED_NAMESPACE:
            raise FormatError(f'pack defines glyph id {index:#x} inside the private namespace 0xE00+')
        pixels = decode_record(glyph_record(pack, index, limit))
        base = index // GLYPHS_PER_BLOCK * BLOCK_BYTES + index % GLYPHS_PER_BLOCK * INK_TILE_BYTES
        atlas[base:base + INK_TILE_BYTES] = ink_tile(pixels)
        atlas[base + BLOCK_CLEAR_OFFSET:base + BLOCK_CLEAR_OFFSET + len(CLEAR_TILE)] = CLEAR_TILE
    return bytes(atlas)
