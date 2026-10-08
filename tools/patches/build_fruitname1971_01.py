'Bounded data-only proof: replace fruit title, not the sprite/icon/OAM/code.'
from pathlib import Path
import os
import hashlib,json,struct,sys
ROOT=Path(os.environ.get('GENKI_SLIME_ROOT', Path(__file__).resolve().parents[2]));W=ROOT/'work/nds-full';P=ROOT/'reports'
sys.path.insert(0,str(ROOT/'tools'))
from ndspy.rom import NintendoDSRom
from nds_item_assets import replace_name_text,parse_frames,render_frame
from rs_format import unpack,replace_bounded
def sha(b):return hashlib.sha256(b).hexdigest()
import argparse
ap=argparse.ArgumentParser();ap.add_argument('--body2363',action='store_true');args=ap.parse_args()
version='2363' if args.body2363 else '1971'
base=ROOT/('work/builds/slime2_body'+version+'_crisp14_candidate01_ownerguard.nds')
out=ROOT/('work/builds/slime2_body'+version+'_fruitname_crisp14_candidate02_dataonly.nds')
assert not out.exists()
raw=base.read_bytes();expected=('4bada7d85dc8ba2199574079bc36d65d729ca3da93c8a16dbbfc24042e7d1fad' if args.body2363 else '59a94114b41f2d31e279922a287969f2cd3795f111e2251b43bb13bae9c39597');assert sha(raw)==expected
source=(ROOT/'inputs/genki_slime2_jp.nds').read_bytes()
assert sha(source)=='53a90729e750bf7288b41d205072138c14941e8810af70f4dc71a5dca6b5ba7b'
rd=NintendoDSRom(raw);jp=NintendoDSRom(source);fid=rd.filenames.idOf('hangar_data.bin')
original=rd.files[fid];assert original==jp.files[jp.filenames.idOf('hangar_data.bin')]
members=unpack(original);tiles=members[339].data;oam=members[341].data
assert len(tiles)==640 and len(oam)==90
patched,proof=replace_name_text(tiles,oam,'木之实')
frames=parse_frames(oam,len(tiles)//32)
assert all(render_frame(tiles,f).tobytes()==render_frame(patched,f).tobytes() for f in frames[1:])
packed=replace_bounded(original,{339:patched})
fat=struct.unpack_from('<I',raw,0x48)[0];start,end=struct.unpack_from('<II',raw,fat+fid*8)
assert raw[start:end]==original and len(packed)==end-start
newraw=raw[:start]+packed+raw[end:]
art_start=start+members[339].offset;art_end=art_start+members[339].size
assert newraw[:art_start]==raw[:art_start] and newraw[art_end:]==raw[art_end:]
fresh=NintendoDSRom(newraw)
assert fresh.arm9==rd.arm9 and fresh.arm7==rd.arm7 and fresh.files[fid]==packed
assert all(a==b for i,(a,b) in enumerate(zip(rd.files,fresh.files)) if i!=fid)
newmembers=unpack(fresh.files[fid]);assert all(a.data==b.data for i,(a,b) in enumerate(zip(members,newmembers)) if i!=339)
assert len(newraw)==len(raw) and newraw[fat:fat+8*len(rd.files)]==raw[fat:fat+8*len(rd.files)]
with out.open('xb') as f:f.write(newraw)
report=dict(scope='one inventory large-name graphic, not all names',candidate_path=str(out),candidate_sha256=sha(newraw),base_path=str(base),base_sha256=sha(raw),source_sha256=sha(source),
    source_name='木の実',translation='木之实',item_index=0,changed_archive='hangar_data.bin',changed_member=339,oam_member=341,proof=proof,
    original_asset_sha256=sha(tiles),patched_asset_sha256=sha(patched),same_ROM_length=True,same_NitroFS_FAT=True,only_name_graphic_member_changed=True,
    icons_all_frames_pixel_identical=True,palette_OAM_ARM9_ARM7_unchanged=True,no_new_runtime_allocation=True,
    changed_byte_count=sum(a!=b for a,b in zip(tiles,patched)),allowed_ROM_interval=[art_start,art_end],
    actual_RAM_and_screen_verified=False,complete_localization=False)
with (P/(out.stem+'.json')).open('x',encoding='utf8') as f:json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
sites=json.loads((W/'passive_item_sites04.json').read_text('utf8'))+json.loads((W/'passive_hangar_name_sites08.json').read_text('utf8'))
assert len({int(s['address'],16) for s in sites})==len(sites)
sitepath=W/'passive_item_and_graphic_sites09.json'
if sitepath.exists():assert json.loads(sitepath.read_text('utf8'))==sites
else:
    with sitepath.open('x',encoding='utf8') as f:json.dump(sites,f,indent=2)
print('BUILT',out,report['candidate_sha256'],'changed_bytes',report['changed_byte_count'])
