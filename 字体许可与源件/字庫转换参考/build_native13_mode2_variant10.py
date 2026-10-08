"""Native13 ONLY for real font-mode2; keep14px measure and ordinary crisp14.
Font-resident cache-owned spare0x8F00 helper expands bit rows to a sparse source
quad on the current CPU stack. Original mode2 callback uses CPU pixel decode
into ORIGINAL main-RAM scratch, THEN original DMA, never DMA from DTCM stack.
No ARM9/overlay changes. All new glyphs are native designs, not resampling.
EXPERIMENT until sameSHA runtime/consumer QA, not full-game certification.
"""
from pathlib import Path
import sys,json,struct,hashlib,argparse
R=Path('<LOCAL_PROJECT_ROOT>');HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(R/'tools'),str(R/'tools/deps/nds-engine')]
from ndspy.rom import NintendoDSRom
from rs_format import unpack,FormatError
from nds_build_extended import pack
from nds_extended_engine import asm,DRAW,ORIGINAL_DRAW,CODE_END
from nds_audit_extended import tile_pixels
from font_renderer import _mask,profile_manifest
from nds_packed_font8 import pack_glyphs
from build_alpha import branch
HELPER=0x8F00
NATIVE8=0x80C0
ap=argparse.ArgumentParser();ap.add_argument('source',type=Path);ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
raw=args.source.read_bytes();meta=json.loads(args.source.with_suffix('.json').read_text('utf8'));assert hashlib.sha256(raw).hexdigest()==meta['candidate_SHA256']
assert not meta.get('native8_body_mode0_only'), 'No mode0 experimental code should be inherited'
rd=NintendoDSRom(raw);old=NintendoDSRom(raw);fid=rd.filenames.idOf('font_data.bin');fonts=[bytes(m.data) for m in unpack(rd.files[fid])];oldfont=fonts[3]
assert not any(oldfont[HELPER:CODE_END])
assert not any(oldfont[NATIVE8:ORIGINAL_DRAW])
cap=meta['caption_atlas_start'];mapping=meta['body_mapping'];private=meta['private_mapping'];assert max(private.values())-0xE00+1==26
limit=max([1740,*mapping.values()])+1;packedstart=(len(oldfont)+31)//32*32;packed=bytearray(limit*32);glyphs=[]
def store(index,pix):
 assert len(pix)==256 and all(v in [1,4] for v in pix)
 assert all(pix[y*16+x]==1 for y in range(16) for x in range(13,16))
 for y in range(16):
  word=sum(1<<x for x in range(13) if pix[y*16+x]==4)
  struct.pack_into('<H',packed,index*32+y*2,word)
for ch,i in sorted(mapping.items(),key=lambda x:x[1]):
 chosen=None
 for fontid in ['wqy13','fusion12']:
  try:mask=_mask(ch,fontid)
  except FormatError:continue
  a=mask.tobytes()
  if any(a[y*16] for y in range(16)):continue
  if any(a[y*16+x] for y in range(16) for x in [14,15]):continue
  pix=bytearray([1]*256)
  for y in range(16):
   for x in range(13):
    if a[y*16+x+1]:pix[y*16+x]=4
  if sum(v==4 for v in pix)!=sum(v==255 for v in a):continue
  chosen=fontid;break
 if chosen is None:raise FormatError('No native13 design fits existing mode2 crop '+repr(ch))
 store(i,pix);glyphs.append(dict(char=ch,index=i,font_id=chosen,design='native13 or native12 fallback,no resampling/no shadow',source_translation_pixels=[-1,0],ink_pixels=sum(v==4 for v in pix),ink_sha256=hashlib.sha256(pix).hexdigest()))
for ch,i in [('是',1739),('否',1740)]:
 pg=i//256;pix=tile_pixels(oldfont[0x9000+pg*32768:0x9000+(pg+1)*32768],i%256);store(i,pix)
 glyphs.append(dict(char=ch,index=i,design='exact frozen09 dedicated native14 design,already fits13 columns',ink_pixels=sum(v==4 for v in pix),ink_sha256=hashlib.sha256(pix).hexdigest()))
packed8start=packedstart+len(packed)
packed8,packed8proof=pack_glyphs(mapping,limit);packed8=bytearray(packed8)
for ch,i in [('是',1739),('否',1740)]:packed8[i*8:(i+1)*8]=packed8[mapping[ch]*8:(mapping[ch]+1)*8]
font=bytearray(oldfont);helpers=[]
def put(off,source,end):
 b=asm(source,off);assert len(b)<=end-off,(hex(off),len(b))
 font[off:end]=b+b'\0'*(end-off-len(b));helpers.append(dict(offset=off,bytes=len(b),sha256=hashlib.sha256(b).hexdigest()))
put(DRAW,f'''
 pop {{ip}}
 cmp r1,#0xfd
 bne {ORIGINAL_DRAW}
 cmp r3,#2
 beq {HELPER}
 cmp r3,#0
 beq {NATIVE8}
 cmp r3,#1
 bne body
 push {{r4}}
 sub r4,r2,#0xe00
 cmp r4,#26
 pop {{r4}}
 blo 0x8e00
body:
 push {{r4,lr}}
 ldr r4, ={limit}
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
''',NATIVE8)
put(NATIVE8,f'''
 push {{r4,r5,r6,r7,r8,lr}}
 sub sp,sp,#32
 mov r4,r0
 ldr r5,[r0]
 ldr r5,[r5,#12]
 ldr ip, ={packed8start}
 add r5,r5,ip
 ldr r7, ={limit}
 cmp r2,r7
 movhs r2,#0
 add r5,r5,r2,lsl #3
 mov r6,sp
 mov r8,#8
row8:
 ldrb r7,[r5],#1
 mov r0,#0
 mov r1,#0
pixel8:
 tst r7,#0x80
 mov r2,#1
 movne r2,#4
 orr r0,r0,r2,lsl r1
 mov r7,r7,lsl #1
 add r1,r1,#4
 cmp r1,#32
 bne pixel8
 str r0,[r6],#4
 subs r8,r8,#1
 bne row8
 mov r0,r4
 add r1,r4,#0x2c
 ldr ip, =0x0209abd0
 blx ip
 mov r5,r0
 mov r0,r4
 add r1,r4,#0x2e
 ldr ip, =0x0209abd0
 blx ip
 mov r6,r0
 mov r0,sp
 mov r1,r5
 mov r2,#8
copy8:
 ldr r3,[r0],#4
 str r3,[r1],#4
 subs r2,r2,#1
 bne copy8
 ldr r0, =0x11111111
 mov r1,r6
 mov r2,#8
clear8:
 str r0,[r1],#4
 subs r2,r2,#1
 bne clear8
 mov r0,#1
 add sp,sp,#32
 pop {{r4,r5,r6,r7,r8,lr}}
 bx lr
''',ORIGINAL_DRAW)
put(HELPER,f'''
 push {{r4,r5,r6,r7,r8,lr}}
 sub sp,sp,#0x440
 mov r4,r0
 ldr r5,[r0]
 ldr r5,[r5,#12]
 ldr ip, ={packedstart}
 add r5,r5,ip
 ldr ip, ={limit}
 cmp r2,ip
 movhs r2,#0
 add r5,r5,r2,lsl #5
 mov r6,#16
 mov r8,sp
row:
 ldrh r7,[r5],#2
 mov r0,#0
 mov r1,#0
left:
 tst r7,#1
 mov r2,#1
 movne r2,#4
 orr r0,r0,r2,lsl r1
 mov r7,r7,lsr #1
 add r1,r1,#4
 cmp r1,#32
 bne left
 str r0,[r8]
 mov r0,#0
 mov r1,#0
right:
 tst r7,#1
 mov r2,#1
 movne r2,#4
 orr r0,r0,r2,lsl r1
 mov r7,r7,lsr #1
 add r1,r1,#4
 cmp r1,#32
 bne right
 str r0,[r8,#32]
 add r8,r8,#4
 subs r6,r6,#1
 cmp r6,#8
 addeq r8,r8,#0x3e0
 cmp r6,#0
 bne row
 mov r0,r4
 mov r1,sp
 mov r2,#0x100
 ldr ip, =0x0209b124
 blx ip
 mov r0,#1
 add sp,sp,#0x440
 pop {{r4,r5,r6,r7,r8,lr}}
 bx lr
''',CODE_END)
assert font[:0x8000]==oldfont[:0x8000] and font[0x8200:HELPER]==oldfont[0x8200:HELPER] and font[0x9000:]==oldfont[0x9000:]
font+=b'\x11'*(packedstart-len(font))+packed+packed8+b'\x11'*32;fonts[3]=bytes(font);rd.files[fid]=pack(fonts);result=rd.save(updateDeviceCapacity=True);final=NintendoDSRom(result)
assert final.arm9==old.arm9 and final.arm7==old.arm7 and final.arm9OverlayTable==old.arm9OverlayTable and final.arm7OverlayTable==old.arm7OverlayTable
assert [i for i,(a,b) in enumerate(zip(final.files,old.files)) if a!=b]==[fid]
assert [bytes(m.data) for m in unpack(final.files[fid])]==fonts
out=args.out;out.mkdir(parents=True,exist_ok=False);p=out/f"slime2_cn_body{meta['body_records']}_native13_mode2_experimental10.nds"
with p.open('xb') as f:f.write(result)
m=dict(meta);m.update(candidate_path=str(p),candidate_SHA256=hashlib.sha256(result).hexdigest(),kind=f"body{meta['body_records']} native13 mode2 EXPERIMENT;not promoted",pre_mode2_candidate_SHA256=meta['candidate_SHA256'],mode2_native13_only=True,native8_body_mode0_only=True,native8_helper={'packed_start':packed8start,'packed_bytes':len(packed8),'clear_tile_start':packed8start+len(packed8),'helper_offset':NATIVE8},native8_packed_font=packed8proof,native0_stack_bytes32=True,native0_CPU_word_VRAM_copy=True,mode2_pack_start=packedstart,mode2_pack_bytes=len(packed),mode2_pack_stride_bytes=32,mode2_pack_slot_limit=limit,mode2_packed_glyphs=glyphs,font_member3_bytes=len(font),font_RAM_extra_vs09_bytes=len(font)-318112,native_mode2_stack_source_bytes1088=True,mode2_saved_register_stack_bytes24=True,no_new_persistent_scratch=True,original_mode2_CPU_to_original_main_RAM_scratch_then_original_DMA=True,ordinary_mode3_body14_pixels_and_mode1_name10_pixels_frozen=True,all_other_source_JP_glyph_paths_unchanged=True,dedicated_yesno112_mode2_ink_exact=True,helper_instruction_ranges=[[0x8000,0x8200],[0x8f00,0x9000]],helpers=helpers,font_resident_instructions_changed=True,ARM9_ARM7_overlays_BSS_unchanged=True,ARM9_instructions_unchanged=True,cache_maintenance_range_still_0x8000_0x9000=True,natural_newSHA_runtime_verified=False,fullgame_peak_RAM_verified=False,all_story_translated=False,full_playthrough=False,font_assets=profile_manifest('crisp14')['assets'])
m.pop('ARM9_ARM7_overlays_BSS_and_instructions_unchanged',None)
with p.with_suffix('.json').open('x',encoding='utf8') as f:json.dump(m,f,ensure_ascii=False,indent=2)
assert args.source.read_bytes()==raw
print(json.dumps({k:m[k] for k in ['candidate_path','candidate_SHA256','body_records','mode2_pack_slot_limit','mode2_pack_bytes','font_member3_bytes','font_RAM_extra_vs09_bytes','helpers']},ensure_ascii=False,indent=2))
