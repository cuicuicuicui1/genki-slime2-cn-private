"""NDS-only explicit FD hi lo CJK extension. Original text_codec stays unchanged.
No zero or raw F8 glyph payload: loaders scan the raw F8 byte for termination.
FD is unused as a top-level opcode in all 3,725 identified original records.
Small speaker consumers remain source encoded until separately implemented.
"""
from pathlib import Path
import re
from rs_format import FormatError
from build_alpha import markup_parts, base_encoder
from text_codec import tokenize as source_tokenize

PREFIX = 0xFD
MAX_GLYPH_INDEX = 4095


def cjk(ch):
    return '\u3400' <= ch <= '\u9fff'


def extended_slots(limit=MAX_GLYPH_INDEX):
    if not isinstance(limit, int) or not 1 <= limit <= MAX_GLYPH_INDEX:
        raise FormatError('Invalid extended atlas limit')
    return [i for i in range(1, limit + 1)
            if 0xF8 not in (i >> 8, i & 255)]


def glyph_code(index):
    if index not in extended_slots():
        raise FormatError('Invalid extended glyph slot')
    return bytes((PREFIX, index >> 8, index & 255))


def tokenize(data):
    result = []; pos = 0
    while pos < len(data):
        begin = pos; b = data[pos]
        if b == PREFIX:
            if pos + 3 > len(data):
                raise FormatError('Truncated extended glyph')
            hi, lo = data[pos + 1:pos + 3]
            index = hi * 256 + lo
            glyph_code(index)
            pos += 3
            token = {'kind': 'glyph', 'value': index, 'extended': True}
        else:
            if b in (0xFE, 0xFF, 0xF1, 0xF2, 0xF3, 0xF4): n = 2
            elif b == 0xF0:
                if pos + 2 > len(data): raise FormatError('Truncated substitution')
                n = 2 if data[pos + 1] == 4 else 3
            else: n = 1
            if pos + n > len(data): raise FormatError('Truncated source token')
            original = source_tokenize(data[pos:pos+n])
            if len(original) != 1: raise FormatError('Source token boundary drift')
            token = dict(original[0], extended=False); pos += n
        token.update(start=begin, end=pos, hex=data[begin:pos].hex())
        result.append(token)
    return result


def decode(data, source_charset, extended_charset):
    tags = {0xF5:'<WAIT>', 0xF6:'<PAGE>', 0xF7:'\n',
            0xF8:'<END>', 0xF9:'<BODY>', 0xFA:'<SPEAKER>'}
    out = []
    for t in tokenize(data):
        if t['kind'] == 'glyph':
            table = extended_charset if t['extended'] else source_charset
            if t['value'] not in table: raise FormatError('Unmapped encoded glyph')
            out.append(table[t['value']])
        else: out.append(tags.get(t['value'], '<'+t['hex'].upper()+'>'))
    return ''.join(out)


def encode(text, source_charset, extra_map):
    old = base_encoder(source_charset)
    tags={'<SPEAKER>':b'\xfa','<BODY>':b'\xf9','<PAGE>':b'\xf6',
          '<WAIT>':b'\xf5','<END>':b'\xf8','\n':b'\xf7'}
    out = bytearray(); speaker = False
    for part in markup_parts(text):
        if part in tags:
            out += tags[part]
            if part == '<SPEAKER>': speaker = not speaker
        elif part.startswith('<F') and part.endswith('>'):
            try: out += bytes.fromhex(part[1:-1])
            except ValueError as ex: raise FormatError('Invalid control tag') from ex
        elif part.startswith('<'): raise FormatError('Unknown markup')
        else:
            for ch in part:
                if not speaker and (cjk(ch) or ch not in old):
                    if ch not in extra_map: raise FormatError('Unmapped CJK ' + ch)
                    out += glyph_code(extra_map[ch])
                elif ch in old: out += old[ch]
                else: raise FormatError('Source encoding unavailable '+repr(ch))
    if speaker: raise FormatError('Unclosed small speaker boundary')
    if not out or out[-1] != 0xF8 or 0xF8 in out[:-1]:
        raise FormatError('Raw F8 terminator collision')
    tokenize(out)
    return bytes(out)


def controls(data):
    return [t['hex'] for t in tokenize(data) if t['kind'] == 'control']
