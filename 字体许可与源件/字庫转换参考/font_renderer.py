"""Native-grid CJK glyph profiles. No font/texture size or advance changes.

WQY's converted 13/14px TTFs use unitsPerEm=1500 and a 100-unit pixel
step. Rendering those at 15 (NOT 13/14) preserves their original bitmap
cells exactly. The requested profile refers to design size, not TTF em.
"""
from pathlib import Path
from functools import lru_cache
import hashlib
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont
from rs_format import FormatError

ROOT = Path(__file__).resolve().parents[1]
BANK_BYTES = 32768
TILE_BYTES = 32
# clear* profiles preserve the rejected light-foreground comparison.
# crisp* use index4, verified as the source font's dark face (index3 is shadow).
PROFILES = ('legacy12', 'clear12', 'clear14', 'crisp12', 'crisp14')
FONTS = {
    'fusion12': ('reference/fonts/fusion-pixel-12px-proportional-zh_hans.ttf', 12, None),
    'wqy14': ('reference/fonts/wqy-bitmap/WenQuanYi Bitmap Song 14px.ttf', 15, 1),
    'wqy13': ('reference/fonts/wqy-bitmap/WenQuanYi Bitmap Song 13px.ttf', 15, 1),
}

@lru_cache(maxsize=3)
def _asset(font_id):
    path, size, top = FONTS[font_id]
    path = ROOT / path
    with TTFont(path) as tt:
        cmap = frozenset((tt.getBestCmap() or {}).keys())
    return ImageFont.truetype(str(path), size), cmap, top


def profile_manifest(profile):
    if profile not in PROFILES:
        raise FormatError('Unknown font profile ' + str(profile))
    ids = ('fusion12',) if profile not in ('clear14', 'crisp14') else ('wqy14', 'wqy13', 'fusion12')
    assets = []
    for font_id in ids:
        rel, size, _ = FONTS[font_id]
        path = ROOT / rel
        raw = path.read_bytes()
        assets.append({'id': font_id, 'path': str(path), 'raster_em_size': size,
                       'sha256': hashlib.sha256(raw).hexdigest()})
    return {'id': profile, 'assets': assets, 'glyph_container': [16, 16],
            'shadow': 'right_and_down' if profile == 'legacy12' else 'none',
            'face_palette_index': 4 if profile.startswith('crisp') else 3,
            'selection_status': 'light_trial_do_not_publish' if profile.startswith('clear') else 'eligible_for_native_QA',
            'advance_policy': 'preserve_candidate02_all_widths',
            'antialias_policy': 'native_grid_only_no_scaling'}


def glyph_offsets(index):
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < 256:
        raise FormatError('Glyph index outside texture')
    return [((index // 16 * 2 + ty) * 32 + index % 16 * 2 + tx) * TILE_BYTES
            for ty in range(2) for tx in range(2)]


def _mask(ch, font_id):
    font, cmap, top = _asset(font_id)
    if len(ch) != 1 or ord(ch) not in cmap:
        raise FormatError('Font cmap missing character ' + repr(ch))
    bb = font.getbbox(ch)
    if not 0 < bb[2] - bb[0] <= 14 or not 0 < bb[3] - bb[1] <= 14:
        raise FormatError(f'Unsupported glyph dimensions {ch} {bb}')
    y = top if top is not None else 1 - font.getbbox('国')[1]
    # Render a larger canvas first: overflow must fail, not silently crop.
    canvas = Image.new('L', (32, 32))
    ImageDraw.Draw(canvas).text((1, y), ch, font=font, fill=255)
    bb = canvas.getbbox()
    if bb is None:
        raise FormatError('Empty glyph ' + repr(ch))
    if bb[0] < 0 or bb[1] < 0 or bb[2] > 15 or bb[3] > 15:
        raise FormatError(f'Glyph escapes 16x16 padded container {ch} {bb}')
    if not set(canvas.tobytes()) <= {0, 255}:
        raise FormatError('Non-native-grid antialiased glyph ' + repr(ch))
    return canvas.crop((0, 0, 16, 16))


def render_glyph(ch, profile='legacy12', advance=None):
    if profile not in PROFILES:
        raise FormatError('Unknown font profile ' + str(profile))
    if advance is not None and (not isinstance(advance, int) or not 1 <= advance <= 16):
        raise FormatError('Invalid declared glyph advance')
    selected = 'fusion12'
    mask = None
    if profile in ('clear14', 'crisp14'):
        if advance is None:
            raise FormatError('native14 requires preserved consumer advance')
        # Keep at least a blank column before the next left-padded glyph.
        # Narrow existing slots use a smaller *native* design, not resampling.
        for font_id in ('wqy14', 'wqy13', 'fusion12'):
            candidate = _mask(ch, font_id)
            if candidate.getbbox()[2] <= advance:
                mask, selected = candidate, font_id
                break
        if mask is None:
            raise FormatError('No native glyph fits preserved advance ' + repr(ch))
    else:
        mask = _mask(ch, selected)
    face = {i for i, val in enumerate(mask.tobytes()) if val == 255}
    pix = bytearray([1] * 256)
    offsets = ((1, 0), (0, 1)) if profile == 'legacy12' else ()
    for i in face:
        x, y = i % 16, i // 16
        for dx, dy in offsets:
            if x + dx >= 16 or y + dy >= 16:
                raise FormatError('Shadow would be clipped')
            pix[(y + dy) * 16 + x + dx] = 4
    face_index = 4 if profile.startswith('crisp') else 3
    for i in face:
        pix[i] = face_index
    return pix, {'char': ch, 'bbox': list(mask.getbbox()), 'ink_pixels': len(face),
                 'shadow_pixels': len({i for i, v in enumerate(pix) if v == 4} - face),
                 'face_palette_index': face_index, 'font_id': selected,
                 'profile': profile, 'preserved_advance': advance,
                 'native_grid_binary': True, 'cmap_present': True}


def draw_glyph(raw, index, ch, profile='legacy12', advance=None):
    offsets = glyph_offsets(index)
    if len(raw) != BANK_BYTES:
        raise FormatError('Unexpected 4bpp font bank capacity')
    pix, info = render_glyph(ch, profile, advance)
    # All validation completes before mutating the caller's bank.
    for ti, off in enumerate(offsets):
        tx, ty = ti % 2 * 8, ti // 2 * 8
        for y in range(8):
            for x in range(0, 8, 2):
                raw[off + y * 4 + x // 2] = (pix[(ty + y) * 16 + tx + x]
                                              | pix[(ty + y) * 16 + tx + x + 1] << 4)
    return dict(info, index=index)
