'''NDS fixed-caption experiment: native10 ink in original mode1 16x16 tiles.
No resize/resampling. Only explicit fixed FA names use a private FD namespace.
Body IDs, original Japanese, dynamic player names and save data stay unchanged.
Not release-approved without cold scene and resource-lifecycle verification.
'''
from pathlib import Path
import hashlib, struct
from functools import lru_cache
from rs_format import FormatError
from nds_small_speaker import (apply_small_speaker, SPEAKER_HELPER, SMALL_DRAW,
    SPEAKER_GATE, SPEAKER_SITES, ROOT)
from nds_extended_engine import asm, DRAW, ORIGINAL_DRAW, CODE_END
from build_alpha import markup_parts, base_encoder
from nds_extended_codec import encode, glyph_code
from text_codec import source_charset

FONT=ROOT/'work/nds-full/fonts10/fusion-pixel-10px-monospaced-zh_hans.bdf'
FONT_SHA='fb35066c7ade4b9674abb3e528d9adc82f6a2c359902e567ef8bead3621c5d4e'
NAME_BASE=0xE00
NAME_PAIRS={'スラリン':'史拉林','スラみ':'史拉米','ミイホン':'米洪','ドラお':'多拉奥',
    'おうさま':'国王','おうひ':'王后','ぱぱ':'爸爸','まま':'妈妈','パパ':'爸爸','ママ':'妈妈'}

def name_mapping():
    return {ch:NAME_BASE+i for i,ch in enumerate(sorted(set(''.join(NAME_PAIRS.values()))),1)}

def validate_private_map(mapping):
    """One existing atlas page; frozen original IDs never shift or disappear."""
    if not isinstance(mapping,dict) or not mapping:raise FormatError('Private caption map required')
    frozen=name_mapping()
    if any(mapping.get(ch)!=index for ch,index in frozen.items()):
        raise FormatError('Frozen native10 caption IDs changed')
    seen=set()
    for ch,index in mapping.items():
        if not isinstance(ch,str) or len(ch)!=1 or type(index) is not int:
            raise FormatError('Single character and integer caption ID required')
        if not NAME_BASE<index<NAME_BASE+256 or index in seen or index&255 in (0xF8,0xFA):
            raise FormatError('Unsafe or duplicate private caption ID')
        seen.add(index)
    return dict(mapping)

def extend_name_mapping(additional_pairs):
    """Explicit parent-reviewed names only; append glyphs, never re-sort old IDs."""
    if not isinstance(additional_pairs,dict):raise FormatError('Explicit fixed name pairs required')
    for jp,cn in additional_pairs.items():
        if not isinstance(jp,str) or not isinstance(cn,str) or not jp or not cn:
            raise FormatError('Nonempty fixed name pair required')
        if any(c in jp+cn for c in '<>\r\n') or len(cn)>8:
            raise FormatError('Not a bounded fixed-name field')
        if jp in NAME_PAIRS and NAME_PAIRS[jp]!=cn:raise FormatError('Existing name alias changed')
    mapping=name_mapping();next_id=max(mapping.values())+1
    for ch in sorted(set(''.join(additional_pairs.values()))-set(mapping)):
        while next_id&255 in (0xF8,0xFA):next_id+=1
        mapping[ch]=next_id;next_id+=1
    return validate_private_map(mapping)

@lru_cache(maxsize=1)
def font10():
    raw=FONT.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=FONT_SHA:raise FormatError('Native10 source drift')
    result={};block=None;ascent=None
    for line in raw.decode('utf8').splitlines():
        if line.startswith('FONT_ASCENT '):ascent=int(line.split()[1])
        if line.startswith('STARTCHAR '):block=[]
        elif block is not None:
            block.append(line)
            if line=='ENDCHAR':
                info={x.split(' ',1)[0]:x.split(' ',1)[1] for x in block if ' ' in x}
                cp=int(info['ENCODING']);box=tuple(map(int,info['BBX'].split()))
                dw=tuple(map(int,info['DWIDTH'].split()));begin=block.index('BITMAP')+1
                if 0<=cp<=0x10FFFF:
                    result[chr(cp)]=(box,dw,tuple(int(x,16) for x in block[begin:-1]))
                block=None
    if ascent!=9:raise FormatError('Native10 baseline drift')
    return result,ascent

def pixels10(ch):
    font,ascent=font10()
    if ch not in font:raise FormatError('Missing native10 glyph '+repr(ch))
    (w,h,xoff,yoff),dw,rows=font[ch]
    if dw!=(10,0) or not 0<w<=10 or not 0<h<=10 or len(rows)!=h:
        raise FormatError('Native10 CJK metrics unsupported')
    ytop=ascent-h-yoff
    if xoff<0 or xoff+w>10 or ytop<0 or ytop+h>10:raise FormatError('Native10 ink escapes ten rows')
    out=bytearray([1]*256);bits=(w+7)//8*8
    for y,row in enumerate(rows):
        if row>=1<<bits:raise FormatError('Bad native10 BDF row')
        for x in range(w):
            if row & 1<<(bits-1-x):out[(ytop+y)*16+xoff+x]=4
    if not any(v==4 for v in out):raise FormatError('Empty native10 glyph')
    return out,dict(char=ch,ink_design_size=10,container=[16,16],advance=16,
        native_no_resampling=True,no_shadow=True,palette_index=4,
        transparent_rows_after_10=True,ink_pixels=sum(x==4 for x in out))

def atlas10(mapping):
    mapping=validate_private_map(mapping)
    atlas=bytearray(b'\x11'*32768);proof=[]
    for ch,index in sorted(mapping.items(),key=lambda x:x[1]):
        local=index-NAME_BASE;pix,info=pixels10(ch);base=local//16*2048+local%16*64
        for y in range(16):
            for x in range(0,16,2):
                off=base+(y//8)*1024+(x//8)*32+(y%8)*4+(x%8)//2
                atlas[off]=pix[y*16+x]|pix[y*16+x+1]<<4
        proof.append(dict(info,index=index,local_index=local,base=base,
            pixels_sha256=hashlib.sha256(pix).hexdigest()))
    return bytes(atlas),proof

def encode_names10(text,arm,body_map,private_map=None):
    if any(not 1<=v<NAME_BASE for v in body_map.values()):
        raise FormatError('Body IDs overlap private fixed-caption namespace')
    old=base_encoder(source_charset(arm));nm=validate_private_map(name_mapping() if private_map is None else private_map);out=bytearray();speaker=False
    for part in markup_parts(text):
        if part=='<SPEAKER>':speaker=not speaker;out+=b'\xfa'
        elif speaker:
            if part.startswith('<') or part=='\n':raise FormatError('Control inside fixed speaker')
            for ch in part:
                if ch in nm:
                    code=glyph_code(nm[ch])
                    if any(v in (0xF8,0xFA) for v in code[1:]):raise FormatError('Unsafe FA/F8 payload')
                    out+=code
                elif ch in old:out+=old[ch]
                else:raise FormatError('Unknown fixed speaker '+repr(ch))
        elif part=='<END>':out+=b'\xf8'
        else:out+=encode(part+'<END>',source_charset(arm),body_map)[:-1]
    if speaker or not out or out[-1]!=0xF8:raise FormatError('Invalid fixed-name record')
    return bytes(out)

def apply_speaker10(arm,font,glyph_limit,atlas_start,private_map=None):
    if not 1<glyph_limit<=NAME_BASE:
        raise FormatError('Body glyph limit overlaps private fixed-caption namespace')
    nm=validate_private_map(name_mapping() if private_map is None else private_map)
    arm,ff,baseproof=apply_small_speaker(arm,font,glyph_limit,atlas_start)
    out=bytearray(ff);limit=max(nm.values())-NAME_BASE+1;helpers=[]
    def put(off,source,end):
        raw=asm(source,off)
        if len(raw)>end-off:raise FormatError('Native10 helper exceeds reservation')
        out[off:end]=raw+b'\0'*(end-off-len(raw))
        helpers.append(dict(offset=off,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
    put(DRAW,f'''
        pop {{ip}}
        cmp r1,#0xfd
        bne {ORIGINAL_DRAW}
        cmp r3,#1
        bne body
        push {{r4}}
        sub r4,r2,#{NAME_BASE}
        cmp r4,#{limit}
        pop {{r4}}
        blo {SMALL_DRAW}
      body:
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
    put(SPEAKER_HELPER,'''
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
        mov r3,#1
        str r3,[sp,#4]
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
    put(SMALL_DRAW,f'''
        push {{r4,lr}}
        sub r2,r2,#{NAME_BASE}
        ldr r4,[r0]
        ldr r4,[r4,#12]
        ldr ip, ={atlas_start}
        add r4,r4,ip
        mov ip,r2,lsr #4
        and r1,r2,#15
        add r1,r4,r1,lsl #6
        add r1,r1,ip,lsl #11
        mov r2,#0x100
        ldr r4, =0x0209B1A0
        blx r4
        mov r0,#1
        pop {{r4,lr}}
        bx lr
    ''',CODE_END)
    return arm,bytes(out),dict(base_gate_proof=baseproof,helpers=helpers,
        private_namespace_start=NAME_BASE,private_namespace_slots=limit,private_glyph_map=nm,
        speaker_font_mode=1,speaker_advance=16,body_glyph_limit=glyph_limit,
        font_allocation_extra=32768+(atlas_start-len(font)),
        dynamic_player_and_save_bytes_unchanged=True,experimental=True)
