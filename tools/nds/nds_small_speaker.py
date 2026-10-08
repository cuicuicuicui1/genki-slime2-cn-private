'''Source-specific experimental FD speaker parser and native8 atlas support.
Only FA speaker loops/resource-owned draw; not saved/player/tank consumers.
Existing8-pixel callback continues to copy8x16 tiles with fixed advance.
'''
from pathlib import Path
import hashlib,struct
from functools import lru_cache
from rs_format import FormatError
from nds_extended_engine import asm,FONT_PTRS,DRAW,ORIGINAL_DRAW,CODE_BEGIN,CODE_END
from build_alpha import branch,markup_parts
from nds_extended_codec import encode,glyph_code
from text_codec import source_charset

ROOT=Path(__file__).resolve().parents[1]
FONT=ROOT/'assets/fonts/fusion8/fusion-pixel-8px-monospaced-zh_hans.bdf'
FONT_SHA='3c00ccab762c0c75967eea724f5cd57feb544be7a0814d06233160ef9482a50b'
SPEAKER_HELPER=0x8C00
SMALL_DRAW=0x8E00
SPEAKER_GATE=0x0209B538
SPEAKER_FALLBACK=0x0209B558
SPEAKER_SITES=(0x9C650,0x9C6D4)
NEW_ROM_RANGES=((0x9B538,0x9B568),(0x9C650,0x9C654),(0x9C6D4,0x9C6D8))

@lru_cache(maxsize=1)
def native8_font():
    raw=FONT.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=FONT_SHA:raise FormatError('Native8 asset source drift')
    result={};block=None;ascent=None
    for line in raw.decode('utf8').splitlines():
        if line.startswith('FONT_ASCENT '):ascent=int(line.split()[1])
        if line.startswith('STARTCHAR '):block=[]
        elif block is not None:
            block.append(line)
            if line=='ENDCHAR':
                info={x.split(' ',1)[0]:x.split(' ',1)[1] for x in block if ' ' in x}
                cp=int(info['ENCODING']);box=tuple(map(int,info['BBX'].split()))
                dwidth=tuple(map(int,info['DWIDTH'].split()))
                begin=block.index('BITMAP')+1
                result[chr(cp)]=(box,dwidth,tuple(int(x,16) for x in block[begin:-1]))
                block=None
    if ascent!=7:raise FormatError('Native8 baseline contract drift')
    return result,ascent

def native8_pixels(ch):
    font,ascent=native8_font()
    if ch not in font:raise FormatError('Native8 missing glyph '+repr(ch))
    (w,h,xoff,yoff),advance,rows=font[ch]
    if advance not in ((4,0),(8,0)) or not 0<w<=8 or not 0<h<=8 or len(rows)!=h:
        raise FormatError('Unsupported native8 metrics '+repr(ch))
    ytop=ascent-h-yoff
    if xoff<0 or xoff+w>8 or ytop<0 or ytop+h>8:raise FormatError('Native8 escapes8x8 '+repr(ch))
    pixels=bytearray([1]*128);bits=(w+7)//8*8
    for y,row in enumerate(rows):
        if row>=1<<bits:raise FormatError('Bad BDF row')
        for x in range(w):
            if row & 1<<(bits-1-x):pixels[(ytop+y)*8+xoff+x]=4
    if not any(x==4 for x in pixels):raise FormatError('Empty native8 glyph '+repr(ch))
    return pixels,dict(char=ch,container=[8,16],ink_height=8,advance=8,
        font_design_size=8,source_bitmap_native=True,no_resampling=True,no_shadow=True,
        face_palette_index=4,source_font_DWIDTH=list(advance),ink_pixels=sum(x==4 for x in pixels))

def native8_atlas(mapping):
    if not mapping or len(set(mapping.values()))!=len(mapping):raise FormatError('Bad atlas mapping')
    maxindex=max(mapping.values());pages=maxindex//512+1
    atlas=bytearray(b'\x11'*(pages*32768));proof=[]
    for ch,index in sorted(mapping.items(),key=lambda x:x[1]):
        pix,info=native8_pixels(ch)
        base=(index//32)*2048+(index%32)*32
        for y in range(16):
            off=base+(y//8)*1024+(y%8)*4
            for x in range(0,8,2):atlas[off+x//2]=pix[y*8+x] | pix[y*8+x+1]<<4
        proof.append(dict(info,index=index,base=base,pixels_sha256=hashlib.sha256(pix).hexdigest()))
    return bytes(atlas),proof

def encode_speaker_names(text,arm,mapping):
    '''Explicit fixed FA labels may contain FD; dynamic/playername unchanged.'''
    from build_alpha import base_encoder
    old=base_encoder(source_charset(arm));out=bytearray();speaker=False
    for part in markup_parts(text):
        if part=='<SPEAKER>':speaker=not speaker;out+=b'\xfa'
        elif speaker:
            if part.startswith('<') or part=='\n':raise FormatError('Control inside fixed speaker name')
            for ch in part:
                if ch in mapping:
                    encoded=glyph_code(mapping[ch])
                    # The source width scanner skips FA bytes until FA. Reject
                    # embedded FA rather than prematurely ending a label.
                    if 0xFA in encoded[1:]:raise FormatError('FA payload unsafe in current fixed speaker mapping '+repr(ch))
                    out+=encoded
                elif ch in old:out+=old[ch]
                else:raise FormatError('Unknown speaker glyph '+repr(ch))
        elif part=='<END>':out+=b'\xf8'
        else:out+=encode(part+'<END>',source_charset(arm),mapping)[:-1]
    if speaker or not out or out[-1]!=0xF8:raise FormatError('Bad complete speaker record')
    return bytes(out)

def apply_small_speaker(arm,font_member,glyph_limit,small_atlas_start):
    '''Patch known expanded candidate; its existing map/atlas do not move.'''
    arm=bytearray(arm);font=bytearray(font_member);before_arm=bytes(arm);before_font=bytes(font)
    if not 1<=glyph_limit<=4096 or small_atlas_start%32 or small_atlas_start<len(font):
        raise FormatError('Bad appended small-atlas allocation')
    if any(font[SPEAKER_HELPER:CODE_END]):raise FormatError('New helper region not reserved zero bytes')
    if any(arm[0x9B538:0x9B568][i:i+4]!=struct.pack('<I',0xE1A00000) for i in range(0,0x30,4)):
        raise FormatError('New ROM gate region is not base-engine NOP reservation')
    for site in SPEAKER_SITES:
        if struct.unpack_from('<I',arm,site)[0]!=0xE5D03000:raise FormatError('Speaker loop source opcode drift')
    def helper(off,source,end):
        raw=asm(source,off)
        if len(raw)>end-off:raise FormatError('New helper out of reserved region')
        font[off:end]=raw+b'\0'*(end-off-len(raw))
        return dict(offset=off,size=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    draw=helper(DRAW,f'''
        pop {{ip}}
        cmp r1,#0xfd
        bne {ORIGINAL_DRAW}
        cmp r3,#0
        beq {SMALL_DRAW}
        push {{r4,lr}}
        ldr r4, ={glyph_limit}
        cmp r2,r4
        movhs r2,#0
        ldr r4,[r0]
        ldr r4,[r4,#12]
        add r4,r4,#0x9000
        mov ip,r2,lsr #4
        and r1,r2,#15
        add r1,r4,r1,lsl #6
        add r1,r1,ip,lsl #11
        mov r2,#0x100
        ldr r4, =0x02137648
        ldr r3,[r4,r3,lsl #2]
        blx r3
        mov r0,#1
        pop {{r4,lr}}
        bx lr
    ''',ORIGINAL_DRAW)
    speaker=helper(SPEAKER_HELPER,'''
        pop {ip}
        ldrb r3,[r0]
        cmp r3,#0xfd
        bne original
        ldrb r2,[r0,#1]
        ldrb r3,[r0,#2]
        orr r2,r3,r2,lsl #8
        add r0,r0,#3
        str r0,[sb,#12]
        str r2,[sp]
        str r6,[sp,#4]
        str r8,[sp,#8]
        mov r0,sb
        mov r1,r5
        mov r2,sl
        mov r3,#0xfd
        ldr ip, =0x0209D1C0
        blx ip
        ldr pc, =0x0209C6D0
      original:
        ldr pc, =0x0209C654
    ''',SMALL_DRAW)
    small=helper(SMALL_DRAW,f'''
        push {{r4,lr}}
        ldr r4, ={glyph_limit}
        cmp r2,r4
        movhs r2,#0
        ldr r4,[r0]
        ldr r4,[r4,#12]
        ldr ip, ={small_atlas_start}
        add r4,r4,ip
        mov ip,r2,lsr #5
        and r1,r2,#31
        add r1,r4,r1,lsl #5
        add r1,r1,ip,lsl #11
        mov r2,#0x100
        ldr r4, =0x0209B408
        blx r4
        mov r0,#1
        pop {{r4,lr}}
        bx lr
    ''',CODE_END)
    gate=asm(f'''push {{ip}}; ldr ip, ={FONT_PTRS}; ldr ip,[ip,#12]; cmp ip,#0;
        beq {SPEAKER_FALLBACK}; add ip,ip,#{SPEAKER_HELPER}; bx ip''',SPEAKER_GATE)
    if len(gate)!=32:raise FormatError('Speaker gate must fit32bytes')
    fallback=asm('pop {ip}; ldrb r3,[r0]; ldr pc, =0x0209C654',SPEAKER_FALLBACK)
    if len(fallback)!=16:raise FormatError('Speaker owner-null fallback must fit16bytes')
    arm[0x9B538:0x9B558]=gate;arm[0x9B558:0x9B568]=fallback
    for site in SPEAKER_SITES:struct.pack_into('<I',arm,site,branch(0x02000000+site,SPEAKER_GATE))
    changed=[i for i,(a,b) in enumerate(zip(arm,before_arm)) if a!=b]
    if not all(any(a<=i<b for a,b in NEW_ROM_RANGES) for i in changed):raise FormatError('Small ARM patch outside declared ranges')
    if font[:CODE_BEGIN]!=before_font[:CODE_BEGIN] or font[ORIGINAL_DRAW:SPEAKER_HELPER]!=before_font[ORIGINAL_DRAW:SPEAKER_HELPER]:
        raise FormatError('Original dispatcher/helper bytes drift')
    if font[CODE_END:]!=before_font[CODE_END:]:raise FormatError('Existing atlas/map modified by small engine')
    return bytes(arm),bytes(font),dict(draw_helper=draw,speaker_helper=speaker,small_draw=small,
        new_ROM_ranges=[list(x) for x in NEW_ROM_RANGES],new_ARM_changed_bytes=len(changed),
        source_sites=[hex(0x02000000+x) for x in SPEAKER_SITES],ROM_owner_null_fallback=True,
        native8_atlas_relative_start=small_atlas_start,existing_map_location_unchanged=True,
        code_cache_region_unchanged=[CODE_BEGIN,CODE_END],allocator_owner_unchanged=True,
        small_speaker_experiment=True,dynamic_saved_names_supported=False)
