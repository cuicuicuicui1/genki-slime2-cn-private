from pathlib import Path
import sys,json,struct,hashlib,argparse
from PIL import Image
R=Path(__file__).resolve().parents[2];W=R/'work/nds-full';sys.path.insert(0,str(R/'tools'))
from ndspy.rom import NintendoDSRom
from rs_format import unpack
import nds_pause_graphics as p

def sha(b):return hashlib.sha256(b).hexdigest()
def new(path,obj):
 with path.open('x',encoding='utf8') as f:f.write(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out-dir',type=Path,default=R/'work/builds');args=ap.parse_args();args.out_dir.mkdir(parents=True,exist_ok=True)
 current=R/'work/builds/slime2_cn_clear_font_preview06.nds';before=current.read_bytes()
 assert sha(before)=='d94145b8a194e62759660b4ff40a724156d39c42d0cbaeb01aa136525862d8a3'
 original=(R/'inputs/genki_slime2_jp.nds').read_bytes();assert sha(original)=='53a90729e750bf7288b41d205072138c14941e8810af70f4dc71a5dca6b5ba7b'
 rd=NintendoDSRom(before);src=NintendoDSRom(original);fid=rd.filenames.idOf('pause_data.bin');assert fid==123
 pack=rd.files[fid];assert pack==src.files[src.filenames.idOf('pause_data.bin')]
 # Independent actual source frame0 evidence from existing sameSHA read-only run221.
 ms=unpack(pack);atlas=p.decode_tiles(pack[ms[0].offset:ms[0].offset+ms[0].size]);maps=p.indexed_maps(pack[ms[1].offset:ms[1].offset+ms[1].size]);sourcepic=p.render_map(atlas,maps[0])
 scene=R/'runs/nds_clear06_pause_actual_221/shots/pause_main.png';im=Image.open(scene).convert('RGB');n=0
 for y in range(sourcepic.height):
  for x in range(sourcepic.width):
   index=sourcepic.getpixel((x,y))
   if index:
    assert im.getpixel((x+40,y+248))==p.OBSERVED_COLORS[index],(x,y,index)
    n+=1
 assert n==4097
 ram=(R/'runs/nds_clear06_pause_actual_221/mainram.bin').read_bytes();m0=pack[ms[0].offset:ms[0].offset+ms[0].size];m1=pack[ms[1].offset:ms[1].offset+ms[1].size]
 at0=ram.find(m0);at1=ram.find(m1);assert at0>=0 and at1>=0
 edited,meta=p.replace_pause(pack)
 fat=struct.unpack_from('<I',before,0x48)[0];start,end=struct.unpack_from('<II',before,fat+fid*8)
 assert before[start:end]==pack and end-start==len(edited)
 out=bytearray(before);out[start:end]=edited;result=bytes(out)
 final=NintendoDSRom(result);assert final.arm9==rd.arm9 and final.arm7==rd.arm7
 assert result[:start]==before[:start] and result[end:]==before[end:]
 assert len(final.files)==len(rd.files)==257
 assert [i for i in range(257) if final.files[i]!=rd.files[i]]==[123]
 assert before==current.read_bytes()
 target=args.out_dir/'slime2_cn_clear_pause_experimental07.nds'
 with target.open('xb') as f:f.write(result)
 allowed=(start+ms[0].offset+32*32,start+ms[0].offset+186*32)
 changes=[i for i,(a,b) in enumerate(zip(before,result)) if a!=b];assert min(changes)>=allowed[0] and max(changes)<allowed[1]
 report=dict(ROM=str(target),ROM_SHA256=sha(result),baseline_ROM=str(current),baseline_SHA256=sha(before),
  user_original_SHA256=sha(original),ROM_size=len(result),body_records2385_unchanged=True,
  graphical_large_names60_unchanged=True,fixed_caption_occurrences275_unchanged=True,
  only_changed_NitroFS_file123_pause_data=True,changed_ROM_bytes=len(changes),
  allowed_absolute_byte_interval=list(allowed),all_maps_palettes_battle_other_UI_unchanged=True,
  executable_RAM_fonts_BSS_unchanged=True,no_added_font_or_resource_RAM=True,
  current_baseline_and_original_unchanged=True,source_frame0_observed_4097_pixels_exact=True,
  source_frame0_top_left=[40,248],source_frame0_scene=str(scene),source_scene_SHA256=sha(scene.read_bytes()),
  source_member0_main_RAM_address=hex(0x02000000+at0),source_member1_main_RAM_address=hex(0x02000000+at1),
  frame1_runtime_not_yet_proved=True,actual_new_ROM_cold_tested=False,full_playthrough=False,
  promoted=False,translation=meta)
 new(args.out_dir/'slime2_cn_clear_pause_experimental07.json',report)
 if args.out_dir==R/'work/builds':
  for i,f in enumerate(maps):
   tiles=p.decode_tiles(edited[ms[0].offset:ms[0].offset+ms[0].size]);p.color_view(p.render_map(tiles,f)).resize((504,264),Image.Resampling.NEAREST).save(W/f'pause_clear07_frame{i}_ASSET_NOT_RUNTIME.png')
 print('DATAONLY_BUILD',target,sha(result),'changed bytes',len(changes),'source scene exact',n)
if __name__=='__main__':main()
