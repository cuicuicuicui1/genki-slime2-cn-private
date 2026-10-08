"""Reduce resident body font RAM, preserve every existing glyph pixel design.
Binary row pack14/13 + native8, real original callbacks consume sparse CPU-stack
source via CPU decode -> mainRAM scratch -> DMA (never DMA from stack).
Experimental; must reverify finalSHA natural routes before any promotion.
"""
from pathlib import Path
import json,sys,struct,hashlib,argparse
R=Path('<LOCAL_PROJECT_ROOT>');D=R/'work/nds-full/insertion10';sys.path[:0]=[str(R/'tools'),str(R/'tools/deps/nds-engine')]
from ndspy.rom import NintendoDSRom
from rs_format import unpack
from nds_build_extended import pack
from nds_extended_engine import asm,ORIGINAL_DRAW,CODE_END
from nds_audit_extended import tile_pixels
ap=argparse.ArgumentParser();ap.add_argument('source',type=Path);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();raw=a.source.read_bytes();meta=json.loads(a.source.with_suffix('.json').read_text('utf8'));assert hashlib.sha256(raw).hexdigest()==meta['candidate_SHA256']
r=NintendoDSRom(raw);fid=r.filenames.idOf('font_data.bin');fonts=[bytes(x.data) for x in unpack(r.files[fid])];old=fonts[3];limit=meta['mode2_pack_slot_limit'];entries=meta['remaps'];body14=bytearray(limit*32)
used=set(meta['body_mapping'].values())|{1739,1740}
for i in used:
 pix=tile_pixels(old[0x9000+(i//256)*32768:0x9000+(i//256+1)*32768],i%256);assert len(pix)==256 and set(pix)<={1,4}
 for y in range(16):struct.pack_into('<H',body14,i*32+y*2,sum(1<<x for x in range(16) if pix[y*16+x]==4))
mapbegin=0x9000;table=b''.join(struct.pack('<II',*x) for x in entries);cap=(mapbegin+len(table)+31)//32*32;caption=old[meta['caption_atlas_start']:meta['caption_atlas_start']+32768]
b14start=cap+32768;b13start=b14start+len(body14);b13=old[meta['mode2_pack_start']:meta['mode2_pack_start']+meta['mode2_pack_bytes']];b8start=b13start+len(b13);old8=meta['native8_helper']['packed_start'];b8=old[old8:old8+meta['native8_helper']['packed_bytes']];clear=b8start+len(b8)
font=bytearray(old[:0x9000]);font+=table+b'\x11'*(cap-mapbegin-len(table))+caption+body14+b13+b8+b'\x11'*32
for at,value in [(0x88D4,mapbegin),(0x88D8,len(entries)),(0x8E40,cap)]:struct.pack_into('<I',font,at,value)
helpers=[]
def put(off,src,end):
 code=asm(src,off);assert len(code)<=end-off,(off,len(code),end-off);font[off:end]=code+b'\x00'*(end-off-len(code));helpers.append(dict(offset=off,bytes=len(code),sha256=hashlib.sha256(code).hexdigest()))
put(0x8000,f'''
 pop {{ip}}
 cmp r1,#0xfd
 bne {ORIGINAL_DRAW}
 cmp r3,#0
 beq 0x80c0
 cmp r3,#1
 bne body
 push {{r4}}
 sub r4,r2,#0xe00
 cmp r4,#26
 pop {{r4}}
 blo 0x8e00
body:
 push {{r4,r5,lr}}
 mov r5,r3
 ldr r4, ={limit}
 cmp r2,r4
 movhs r2,#0
 ldr r4,[r0]
 ldr r4,[r4,#12]
 cmp r5,#2
 ldrne ip, ={b14start}
 ldreq ip, ={b13start}
 add r4,r4,ip
 add r1,r4,r2,lsl #5
 mov r2,#0x100
 ldr r4, =0x02137648
 ldr r3,[r4,r5,lsl #2]
 bl 0x8f00
 mov r0,#1
 pop {{r4,r5,lr}}
 bx lr
''',0x80C0)
# native0 helper original code identical except one packed-data base literal.
oldblock=old[0x80C0:0x8200];pat=struct.pack('<I',old8);assert oldblock.count(pat)==1
newblock=oldblock.replace(pat,struct.pack('<I',b8start));font[0x80C0:0x8200]=newblock
helpers.append(dict(offset=0x80C0,bytes=len(newblock),only_data_literal_changed=True,sha256=hashlib.sha256(newblock).hexdigest()))
put(0x8F00,f'''
 push {{r4,r5,r6,r7,r8,r9,r10,lr}}
 sub sp,sp,#0x440
 mov r4,r0
 mov r5,r1
 mov r9,r3
 mov r10,r2
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
 mov r2,r10
 blx r9
 add sp,sp,#0x440
 pop {{r4,r5,r6,r7,r8,r9,r10,lr}}
 bx lr
''',CODE_END)
assert font[:0x8000]==old[:0x8000] and caption==old[meta['caption_atlas_start']:meta['caption_atlas_start']+32768]
# Other helper instruction regions identical; only the two table literals/captionbase moved.
allowed=set(range(0x8000,0x8200))|set(range(0x8F00,0x9000))|set(range(0x88D4,0x88DC))|set(range(0x8E40,0x8E44))
assert all(x==y or i in allowed for i,(x,y) in enumerate(zip(font[:0x9000],old[:0x9000])))
fonts[3]=bytes(font);r.files[fid]=pack(fonts);result=r.save(updateDeviceCapacity=True);f=NintendoDSRom(result);o=NintendoDSRom(raw);assert f.arm9==o.arm9 and f.arm7==o.arm7 and f.arm9OverlayTable==o.arm9OverlayTable and f.arm7OverlayTable==o.arm7OverlayTable;assert [i for i,(x,y) in enumerate(zip(f.files,o.files)) if x!=y]==[fid]
a.out.mkdir(parents=True,exist_ok=False);p=a.out/'slime2_cn_body3505_resident_compact_experimental10.nds';p.write_bytes(result);m=dict(meta);m.update(kind='body3505 compact resident fonts EXPERIMENT',candidate_path=str(p),candidate_SHA256=hashlib.sha256(result).hexdigest(),pre_compact_resident_candidate_SHA256=meta['candidate_SHA256'],font_member3_bytes=len(font),font_RAM_extra_vs09_bytes=len(font)-318112,body_atlas_replaced_binary_rowpack=True,body14_pack_start=b14start,body14_pack_bytes=len(body14),body13_pixels_frozen=True,body14_pixels_frozen=True,mode2_pack_start=b13start,caption_atlas_start=cap,ordinary_body14_original_callback_preserved=True,native8_helper=dict(packed_start=b8start,packed_bytes=len(b8),clear_tile_start=clear,helper_offset=0x80C0),all_DMA_sources_original_mainRAM_scratch_never_DTCM=True,resident_helpers=helpers,natural_newSHA_runtime_verified=False,fullgame_peak_RAM_verified=False,full_playthrough=False)
p.with_suffix('.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf8');assert a.source.read_bytes()==raw
print(json.dumps({k:m[k] for k in ['candidate_path','candidate_SHA256','font_member3_bytes','font_RAM_extra_vs09_bytes','body14_pack_start','mode2_pack_start','resident_helpers']},indent=2))
