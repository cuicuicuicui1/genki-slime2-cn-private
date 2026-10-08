"""Mode2-literal candidate02: preserve all14px ink in existing13px crop.
System-only appended slots1739/1740 inside existing last atlas page. No scaling,
new instructions, font bytes/heap growth or existing body/name glyph changes.
"""
from pathlib import Path
import sys,json,struct,hashlib,argparse
R=Path(__file__).resolve().parents[2];W=R/'work/nds-full';sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(W))
from build_yesno_literal09 import BASE,BASESHA,OLD,LITERAL,SIZE,POINTER_REFERENCES,data_map
from ndspy.rom import NintendoDSRom
from nds_build_extended import pack
from nds_extended_codec import glyph_code,controls,decode
from text_codec import source_charset
from rs_format import unpack,FormatError
LIMIT_OFF=0x8070;OLD_LIMIT=1739;NEW_LIMIT=1741
LABEL_IDS={'是':1739,'否':1740}
def sha(b):return hashlib.sha256(b).hexdigest()
def record(mapping):
 if mapping.get('是')!=0x360 or mapping.get('否')!=0x139:raise FormatError('Frozen body IDs changed')
 value=b'\xf9\x3f\x3f'+glyph_code(LABEL_IDS['是'])+b'\xf7\x3f\x3f'+glyph_code(LABEL_IDS['否'])+b'\xf7\xf8'
 if len(value)!=14 or controls(value)!=controls(OLD[:13]):raise FormatError('Choice skeleton changed')
 return value+b'\0\0'
def native_pixels(font,index):
 base=0x9000+index//16*2048+index%16*64;p=[]
 for y in range(16):
  for x in range(16):p.append((font[base+y//8*1024+x//8*32+y%8*4+x%8//2]>>(4*(x%2)))&15)
 return p
def put_pixels(font,index,p):
 base=0x9000+index//16*2048+index%16*64;offsets=[]
 for y in range(16):
  for x in range(0,16,2):
   off=base+y//8*1024+x//8*32+y%8*4+x%8//2
   if not 0x9000<=off<0x41000:raise FormatError('System slot escapes existing atlas')
   font[off]=p[y*16+x]|p[y*16+x+1]<<4;offsets.append(off)
 return offsets
def build_bytes(raw):
 if sha(raw)!=BASESHA:raise FormatError('Frozen08source only')
 old=NintendoDSRom(raw);rd=NintendoDSRom(raw);bm=data_map(rd)
 if rd.arm9[LITERAL:LITERAL+SIZE]!=OLD:raise FormatError('Choice literal source drift')
 rawfont=unpack(rd.files[rd.filenames.idOf('font_data.bin')]);fonts=[m.data for m in rawfont];original=bytes(fonts[3]);ff=bytearray(original)
 if len(ff)!=318112 or struct.unpack_from('<I',ff,LIMIT_OFF)[0]!=OLD_LIMIT:raise FormatError('Frozen helper/size changed')
 if ff[0x802c:0x8038]!=bytes.fromhex('3c409fe5040052e10020a023'):raise FormatError('Bodylimit literal consumer changed')
 proof=[];allowed=set(range(LIMIT_OFF,LIMIT_OFF+4))
 for ch,index in LABEL_IDS.items():
  if not all(n==1 for n in native_pixels(original,index)):raise FormatError('System slot is not blank')
  src=native_pixels(original,bm[ch]);dst=[1]*256
  if any(src[y*16]!=1 for y in range(16)):raise FormatError('Left-shift would drop source ink')
  for y in range(16):
   for x in range(15):dst[y*16+x]=src[y*16+x+1]
  if sum(n==4 for n in dst)!=sum(n==4 for n in src) or any(dst[y*16+x]!=1 for y in range(16) for x in range(13,16)):raise FormatError('Not safe13column ink')
  allowed.update(put_pixels(ff,index,dst));proof.append({'char':ch,'frozen_body_ID':bm[ch],'system_only_append_ID':index,'ink_pixels_retained':sum(n==4 for n in dst),'translation_offset_pixels':[-1,0],'native14_design_no_resampling':True,'new_full_pixels_sha256':sha(bytes(dst))})
 struct.pack_into('<I',ff,LIMIT_OFF,NEW_LIMIT)
 changed=[i for i,(a,b) in enumerate(zip(ff,original)) if a!=b]
 if not set(changed)<=allowed:raise FormatError('Font write escaped systemslots/limitdata')
 assert ff[0x801c:0x8020]==original[0x801c:0x8020] # retain25name IDs bound26
 fonts[3]=bytes(ff);fid=rd.filenames.idOf('font_data.bin');rd.files[fid]=pack(fonts)
 new=b'\xf9\x3f\x3f'+glyph_code(LABEL_IDS['是'])+b'\xf7\x3f\x3f'+glyph_code(LABEL_IDS['否'])+b'\xf7\xf8'
 if len(new)!=14 or controls(new)!=controls(OLD[:13]):raise FormatError('Choice skeleton changed')
 rd.arm9[LITERAL:LITERAL+SIZE]=new+b'\0\0'
 result=rd.save(updateDeviceCapacity=True);final=NintendoDSRom(result)
 assert len(result)==len(raw) and final.arm9[:LITERAL]==old.arm9[:LITERAL] and final.arm9[LITERAL+SIZE:]==old.arm9[LITERAL+SIZE:]
 assert final.arm7==old.arm7 and final.arm9OverlayTable==old.arm9OverlayTable and final.arm7OverlayTable==old.arm7OverlayTable
 assert [i for i,(a,b) in enumerate(zip(final.files,old.files)) if a!=b]==[fid]
 assert [m.data for m in unpack(final.files[fid])]==fonts and len(final.arm9)==len(old.arm9)
 for off in POINTER_REFERENCES:assert struct.unpack_from('<I',final.arm9,off)[0]==0x02138048
 for ch,index in LABEL_IDS.items():
  assert native_pixels(fonts[3],bm[ch])==native_pixels(original,bm[ch])
  pix=native_pixels(fonts[3],index);assert sum(n==4 for n in pix)==sum(n==4 for n in native_pixels(original,bm[ch]))
 # Existing entirebody atlas untouched excluding two source-proven unused tiles; existing25names unchanged.
 report={'baseline':str(BASE),'baseline_SHA256':BASESHA,'candidate_SHA256':sha(result),'candidate02_fixes_initial09_3clipped_inkpixels':True,
 'initial_clipped_candidate_NOT_promoted':True,'new_system_labels':{'はい':'是','いいえ':'否'},'system_labels2_NOT_story_records':True,'system_append_only_IDs':LABEL_IDS,
 'source_native_mode2_consumers':'0209B124/0209AC90; actual initial09 grid showed rightmostcol13 clipped, candidate02 moves system-only ink1pxleft into0..12',
 'native14_ink_proofs':proof,'ARM9_only_changed_data_range':[hex(LITERAL),hex(LITERAL+SIZE)],'new_literal16_hex':(new+b'\0\0').hex(),'source_literal16_hex':OLD.hex(),
 'font_resident_limit_data_only_range':[hex(LIMIT_OFF),hex(LIMIT_OFF+4)],'font_resident_limit_old_new':[OLD_LIMIT,NEW_LIMIT],'font_changed_offsets':changed,
 'all_helper_instruction_bytes_unchanged':True,'old1732_body_and25_private_name_IDs_pixels_unchanged':True,'original_JP_glyphs_unchanged':True,
 'fixed_caption_helper_bound26_unchanged':True,'font_member3_bytes':318112,'font_RAM_extra0':True,'same7body_atlas_pages_no_growth':True,
 'only_font_data_NitroFS_changed_other256files_exact':True,'ARM7_overlay_BSS_filename_unchanged':True,'two_pointer_refs_unchanged':[hex(x) for x in POINTER_REFERENCES],
 'body2385_names60_fixed369_pause4_unchanged':True,'choice_selection_savedata_event_logic_unchanged':True,'independent_runtime_acceptance':False,'fullgame':False,
 'artifact_kind':'data-only13column-safe native14 label EXPERIMENT;freshSHA QA required'}
 return result,report
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out-dir',type=Path,default=R/'work/builds');args=ap.parse_args();d=args.out_dir.resolve();d.mkdir(parents=True,exist_ok=True);out=d/'slime2_cn_yesno_native14_candidate02_experimental09.nds';raw=BASE.read_bytes();result,report=build_bytes(raw)
 with out.open('xb') as f:f.write(result)
 report['candidate_path']=str(out)
 with out.with_suffix('.json').open('x',encoding='utf8') as f:json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
 assert BASE.read_bytes()==raw
 print('BUILT SAFE13COL native14candidate02',sha(result),'fontRAMextra0; all112inkpixels retained;systemIDs',LABEL_IDS)
if __name__=='__main__':main()
