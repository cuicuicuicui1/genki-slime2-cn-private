"""Position-independent ARM helpers owned by font_data member3's lifecycle.
No ARM9 growth, BSS shift, arbitrary free-space assumption or writable globals.
The original glyph dispatcher is copied together with its literal pool. Its
source allocation becomes bounded trampolines into the loaded fourth member.
Experimental until final ROM cold scenarios are verified, not a full release.
"""
from pathlib import Path
import struct, sys, hashlib
from rs_format import FormatError
sys.path.insert(0, str(Path(__file__).resolve().parent / 'deps/nds-engine'))
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM
from build_alpha import branch

FONT_PTRS = 0x021453F0
CODE_BEGIN = 0x8000
CODE_END = 0x9000
ATLAS_BEGIN = 0x9000
DRAW = 0x8000
ORIGINAL_DRAW = 0x8200
FETCH = 0x8400
MEASURE = 0x8600
MESSAGE = 0x8800
ARGUMENT = 0x8A00
SOURCE_DRAW_START = 0x9B478
SOURCE_DRAW_END = 0x9B568
THUNKS = {'draw': 0x0209B478, 'fetch': 0x0209B498,
          'measure': 0x0209B4B8, 'message': 0x0209B4D8,
          'argument': 0x0209B4F8, 'message_fallback':0x0209B518}
PATCH_RANGES = [(0x9A918,0x9A978),(0x9B478,0x9B568),
                (0x9BA50,0x9BA54),(0x9BB6C,0x9BC30),
                (0x9C560,0x9C564),(0x9B92C,0x9B930),(0x9D1FC,0x9D200)]


def asm(source, address=0):
    try: encoding, _ = Ks(KS_ARCH_ARM, KS_MODE_ARM).asm(source, addr=address)
    except Exception as ex: raise FormatError('ARM assembly failed: '+str(ex)) from ex
    return bytes(encoding)


def _thunk(code_offset, address):
    if code_offset == MESSAGE:
        # The owner check MUST be in ROM, before attempting to execute any
        # heap-owned helper. A guard inside that helper is too late for NULL.
        raw = asm(f"push {{ip}}; ldr ip, ={FONT_PTRS}; ldr ip, [ip,#12]; cmp ip,#0; beq {THUNKS['message_fallback']}; add ip,ip,#{code_offset}; bx ip",address)
    else:
        raw = asm(f"push {{ip}}; ldr ip, ={FONT_PTRS}; ldr ip, [ip,#12]; add ip,ip,#{code_offset}; bx ip", address)
    if len(raw) > 0x20: raise FormatError('Thunk exceeds reserved allocation')
    return raw + struct.pack('<I',0xE1A00000) * ((0x20 - len(raw))//4)


def make_helpers(old_dispatch, glyph_limit, remaps, atlas_bytes):
    if len(old_dispatch) != SOURCE_DRAW_END-SOURCE_DRAW_START:
        raise FormatError('Unexpected original dispatcher allocation')
    if not 1 <= glyph_limit <= 4096 or len(remaps) > 4096:
        raise FormatError('Extended glyph/map budget exceeded')
    if atlas_bytes % 32768: raise FormatError('Atlas must contain complete texture pages')
    maps_begin = ATLAS_BEGIN + atlas_bytes
    blob = bytearray(CODE_END-CODE_BEGIN)
    descriptions = []
    def put(offset, name, source, end):
        raw = asm(source,offset)
        if offset+len(raw)>end: raise FormatError(name+' exceeds reserved helper allocation')
        blob[offset-CODE_BEGIN:offset-CODE_BEGIN+len(raw)]=raw
        descriptions.append({'name':name,'offset':offset,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
    put(DRAW,'draw',f"""
        pop {{ip}}
        cmp r1,#0xfd
        bne {ORIGINAL_DRAW}
        push {{r4,lr}}
        ldr r4, ={glyph_limit}
        cmp r2,r4
        movhs r2,#0
        ldr r4,[r0]
        ldr r4,[r4,#12]
        add r4,r4,#{ATLAS_BEGIN}
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
    """,ORIGINAL_DRAW)
    # Branches and PC-relative literal positions all move together. No direct
    # external branch is present; blx r3 uses the original callback table.
    blob[ORIGINAL_DRAW-CODE_BEGIN:ORIGINAL_DRAW-CODE_BEGIN+len(old_dispatch)]=old_dispatch
    descriptions.append({'name':'original_dispatch_including_literal_pool',
                         'offset':ORIGINAL_DRAW,'bytes':len(old_dispatch),
                         'sha256':hashlib.sha256(old_dispatch).hexdigest()})
    put(FETCH,'fetch',"""
        pop {ip}
        ldrb r3,[r0],#1
        cmp r3,#0xfd
        bne original
        push {ip}
        ldrb r2,[r0],#1
        ldrb ip,[r0],#1
        orr r2,ip,r2,lsl #8
        pop {ip}
        str r0,[sb,#12]
        str r2,[sp]
        mov r0,sb
        ldr pc, =0x0209C5D4
      original:
        str r0,[sb,#12]
        ldr pc, =0x0209C568
    """,MEASURE)
    put(MEASURE,'measure',"""
        pop {ip}
        add r0,r0,#2
        cmp r3,#0
        addeq r4,r4,#8
        beq finish
        cmp r3,#1
        addeq r4,r4,#16
        addne r4,r4,#14
      finish:
        mov r4,r4,lsl #16
        mov r4,r4,asr #16
        ldr pc, =0x0209BB40
    """,MESSAGE)
    put(MESSAGE,'message',f"""
        pop {{ip}}
        push {{r4,r5,r6,r7,r8,lr}}
        mov r4,r0
        mov r5,r1
        orr r8,r5,r4,lsl #16
        ldr r6, ={FONT_PTRS}
        ldr r6,[r6,#12]
        cmp r6,#0
        beq load
        ldr r7, ={maps_begin}
        add r6,r6,r7
        mov r0,#0
        ldr r1, ={len(remaps)}
      search:
        cmp r0,r1
        bhs load
        add r2,r0,r1
        mov r2,r2,lsr #1
        add r7,r6,r2,lsl #3
        ldr r3,[r7]
        cmp r8,r3
        ldreq r5,[r7,#4]
        beq load
        addhi r0,r2,#1
        movlo r1,r2
        b search
      load:
        ldr r0, =0x02138038
        mov r1,r4
        ldr ip, =0x020DC900
        blx ip
        mov r6,r0
        add r4,r6,r5
        mov r1,r4
        mov r5,#0
      scan:
        ldrb r0,[r1],#1
        add r5,r5,#1
        cmp r0,#0xf8
        bne scan
        mov r0,r5
        ldr ip, =0x020DCB48
        blx ip
        mov r7,r0
        mov r1,r7
      copy:
        ldrb r0,[r4],#1
        strb r0,[r1],#1
        subs r5,r5,#1
        bne copy
        mov r0,r6
        ldr ip, =0x020DCAC8
        blx ip
        mov r0,r7
        pop {{r4,r5,r6,r7,r8,lr}}
        bx lr
    """,ARGUMENT)
    put(ARGUMENT,'argument',"""
        pop {ip}
        cmp r5,#0xfd
        ldrheq r1,[sp,#24]
        ldrbne r1,[sp,#24]
        ldr pc, =0x0209D200
    """,CODE_END)
    return bytes(blob),descriptions,maps_begin


def apply_engine(arm, original_dispatch, glyph_limit, remaps, atlas_bytes):
    before=bytes(arm)
    code,helpers,maps_begin=make_helpers(original_dispatch,glyph_limit,remaps,atlas_bytes)
    arm[SOURCE_DRAW_START:SOURCE_DRAW_END]=struct.pack('<I',0xE1A00000)*((SOURCE_DRAW_END-SOURCE_DRAW_START)//4)
    for name,off in [('draw',DRAW),('fetch',FETCH),('measure',MEASURE),('message',MESSAGE),('argument',ARGUMENT)]:
        address=THUNKS[name];start=address-0x02000000
        arm[start:start+0x20]=_thunk(off,address)
    address=THUNKS['message_fallback'];start=address-0x02000000
    fallback=asm('pop {ip}; push {r4,r5,r6,r7,lr}; ldr pc, =0x0209B930',address)
    if len(fallback)>SOURCE_DRAW_END-start:raise FormatError('Owner fallback escaped old dispatcher allocation')
    arm[start:start+len(fallback)]=fallback
    for src,target in [(0x9C560,THUNKS['fetch']),(0x9BA50,THUNKS['measure']),(0x9B92C,THUNKS['message']),(0x9D1FC,THUNKS['argument'])]:
        struct.pack_into('<I',arm,src,branch(0x02000000+src,target))
    # Glyph count used for per-character metadata allocation. Count every
    # source/extended glyph and skip control payloads (not glyphs). Preserve
    # the old 0x20 allowance for dynamic name substitutions, plus outer +0x60.
    counter=asm("""
        cmp r0,#0
        mvneq r0,#0
        bxeq lr
        mov r3,#0
      next:
        ldrb r2,[r0],#1
        cmp r2,#0xf8
        beq done
        cmp r2,#0xef
        addls r3,r3,#1
        bls next
        cmp r2,#0xfd
        addeq r0,r0,#2
        addeq r3,r3,#1
        beq next
        cmp r2,#0xfe
        cmpne r2,#0xff
        addeq r0,r0,#1
        addeq r3,r3,#1
        beq next
        cmp r2,#0xf0
        bne params
        ldrb r1,[r0],#1
        cmp r1,#4
        addlo r0,r0,#1
        addlo r3,r3,#0x20
        b next
      params:
        cmp r2,#0xf4
        addls r0,r0,#1
        b next
      done:
        mov r0,r3
        bx lr
    """,0x0209BB6C)
    s,e=0x9BB6C,0x9BC30
    if len(counter)>e-s:raise FormatError('Counter escaped original allocation')
    arm[s:e]=counter+struct.pack('<I',0xE1A00000)*((e-s-len(counter))//4)
    # Keep all four current font members and their release loop. Explicitly
    # clean D-cache / invalidate I-cache over appended executable bytes only.
    loader=asm(f"""
        push {{r4,r5,r6,lr}}
        ldr r4, ={FONT_PTRS}
        ldr r5, =0x02137658
        mov r6,#0
      again:
        mov r0,r5
        mov r1,r6
        bl 0x020DC900
        str r0,[r4,r6,lsl #2]
        add r6,r6,#1
        cmp r6,#4
        blo again
        add r0,r0,#{CODE_BEGIN}
        add r1,r0,#{CODE_END-CODE_BEGIN}
      cache:
        mcr p15,0,r0,c7,c10,1
        mcr p15,0,r0,c7,c5,1
        add r0,r0,#32
        cmp r0,r1
        blo cache
        mov r2,#0
        mcr p15,0,r2,c7,c10,4
        pop {{r4,r5,r6,pc}}
    """,0x0209A918)
    s,e=0x9A918,0x9A978
    if len(loader)>e-s:raise FormatError('Cache-aware loader escaped allocation')
    arm[s:e]=loader+struct.pack('<I',0xE1A00000)*((e-s-len(loader))//4)
    changed={i for i,(a,b) in enumerate(zip(before,arm)) if a!=b}
    if not all(any(s<=i<e for s,e in PATCH_RANGES) for i in changed):
        raise FormatError('Engine write escaped declared allocations')
    return code,{'helpers':helpers,'maps_begin':maps_begin,'ranges':PATCH_RANGES,
                 'arm9_size_unchanged':len(before)==len(arm),'arm9_changed_bytes':len(changed),
                 'cache_maintenance_range':[CODE_BEGIN,CODE_END],
                 'globals_added':False,'font_owner':'existing fourth bank load/free',
                 'small_speaker_FD_ready':False,
                 'map_uses_font_owner_null_guard':True,'helper_regions_nonoverlapping':True}
