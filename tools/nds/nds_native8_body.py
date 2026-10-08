'''Experimental packed native8 body glyph draw; no new messages or saves.
Source specific current speaker10 engine only. Mode1 private captions and
mode1/2/3 body atlas stay original. Each native0 glyph is unpacked on stack,
then copied with CPU word stores to original texture-allocator destinations.
The original DMA-copy wrapper must NOT read the DTCM stack: rejected ROM01
showed blank glyphs despite controlled tests mocking that DMA as memcpy.
This is NOT proof that every independent small-menu parser handles FD.
'''
import struct,hashlib
from nds_extended_engine import asm,DRAW,ORIGINAL_DRAW,CODE_END
from nds_speaker10 import NAME_BASE,name_mapping
from rs_format import FormatError

PACKED_DRAW=0x8F00

def apply_native8_body(arm,font,glyph_limit,packed_start,clear_start):
    if not 1<glyph_limit<=NAME_BASE:raise FormatError('Body namespace overlaps captions')
    if packed_start%32 or packed_start!=len(font):raise FormatError('Must append pack at aligned original font end')
    if clear_start!=packed_start+glyph_limit*8:raise FormatError('Bad packed bounds/clear tile start')
    if any(font[PACKED_DRAW:CODE_END]):raise FormatError('Packed helper reservation no longer empty')
    out=bytearray(font);helpers=[]
    def put(off,source,end):
        code=asm(source,off)
        if len(code)>end-off:raise FormatError('Native8 helper exceeds cache-owned allocation')
        out[off:end]=code+b'\0'*(end-off-len(code))
        helpers.append(dict(offset=off,bytes=len(code),sha256=hashlib.sha256(code).hexdigest()))
    limit=len(name_mapping())+1
    put(DRAW,f'''
        pop {{ip}}
        cmp r1,#0xfd
        bne {ORIGINAL_DRAW}
        cmp r3,#0
        beq {PACKED_DRAW}
        cmp r3,#1
        bne body
        push {{r4}}
        sub r4,r2,#{NAME_BASE}
        cmp r4,#{limit}
        pop {{r4}}
        blo 0x8e00
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
    put(PACKED_DRAW,f'''
        push {{r4,r5,r6,r7,r8,lr}}
        sub sp,sp,#32
        mov r4,r0
        ldr r5,[r0]
        ldr r5,[r5,#12]
        ldr ip, ={packed_start}
        add r5,r5,ip
        ldr r7, ={glyph_limit}
        cmp r2,r7
        movhs r2,#0
        add r5,r5,r2,lsl #3
        mov r6,sp
        mov r8,#8
      row:
        ldrb r7,[r5],#1
        mov r0,#0
        mov r1,#0
      pixel:
        tst r7,#0x80
        mov r2,#1
        movne r2,#4
        orr r0,r0,r2,lsl r1
        mov r7,r7,lsl #1
        add r1,r1,#4
        cmp r1,#32
        bne pixel
        str r0,[r6],#4
        subs r8,r8,#1
        bne row
        mov r0,r4
        add r1,r4,#0x2c
        ldr ip, =0x0209ABD0
        blx ip
        mov r5,r0
        mov r0,r4
        add r1,r4,#0x2e
        ldr ip, =0x0209ABD0
        blx ip
        mov r6,r0
        mov r0,sp
        mov r1,r5
        mov r2,#8
      upper_cpu_copy:
        ldr r3,[r0],#4
        str r3,[r1],#4
        subs r2,r2,#1
        bne upper_cpu_copy
        ldr r0, =0x11111111
        mov r1,r6
        mov r2,#8
      lower_cpu_clear:
        str r0,[r1],#4
        subs r2,r2,#1
        bne lower_cpu_clear
        mov r0,#1
        add sp,sp,#32
        pop {{r4,r5,r6,r7,r8,lr}}
        bx lr
    ''',CODE_END)
    assert bytes(out[:DRAW])==font[:DRAW]
    assert bytes(out[ORIGINAL_DRAW:PACKED_DRAW])==font[ORIGINAL_DRAW:PACKED_DRAW]
    assert bytes(out[CODE_END:])==font[CODE_END:]
    return bytes(arm),bytes(out),dict(helpers=helpers,packed_start=packed_start,
        packed_bytes=glyph_limit*8,clear_tile_start=clear_start,clear_tile_bytes=32,
        temporary_stack_bytes=32,saved_register_stack_bytes=24,no_persistent_scratch=True,
        source_allocator_reused=True,CPU_word_copies_instead_of_DMA_from_DTCM=True,
        texture_destination_allocation_alignment_bytes=32,upper_lower_tile_words_each8=True,
        ARM9_byte_unchanged=True,
        cache_maintenance_region_unchanged=[0x8000,0x9000],
        all_independent_small_parsers_implemented=False,full_runtime_proof=False)
