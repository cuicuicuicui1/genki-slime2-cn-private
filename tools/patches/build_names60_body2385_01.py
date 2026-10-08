from pathlib import Path
import os
import hashlib,json,struct,sys
ROOT=Path(os.environ.get('GENKI_SLIME_ROOT', Path(__file__).resolve().parents[2]));W=ROOT/'work/nds-full';P=ROOT/'reports'
sys.path.insert(0,str(ROOT/'tools'))
from ndspy.rom import NintendoDSRom
from nds_item_assets import replace_name_text,parse_frames,render_frame
from rs_format import unpack,replace_bounded
def sha(b):return hashlib.sha256(b).hexdigest()
base=ROOT/'work/builds/slime2_body2385_crisp14_candidate01_ownerguard.nds';raw=base.read_bytes()
br=json.loads((P/(base.stem+'.json')).read_text('utf8'));assert br['candidate_sha256']==sha(raw) and br['mapped_record_count']==2385
source=(ROOT/'inputs/genki_slime2_jp.nds').read_bytes();assert sha(source)=='53a90729e750bf7288b41d205072138c14941e8810af70f4dc71a5dca6b5ba7b'
rd=NintendoDSRom(raw);jp=NintendoDSRom(source);fid=rd.filenames.idOf('hangar_data.bin');original=rd.files[fid]
assert original==jp.files[jp.filenames.idOf('hangar_data.bin')]
manifest=json.loads((W/'item_names60_static01/manifest.json').read_text('utf8'));assert manifest['successful_names']==60 and not manifest['failures'] and manifest['source_archive_sha256']==sha(original)
members=unpack(original);replacements={};proofs=[]
for entry in manifest['proofs']:
    art=entry['art_member'];oam=entry['oam_member'];tiles=members[art].data
    assert sha(tiles)==entry['source_asset_sha256']
    patched,proof=replace_name_text(tiles,members[oam].data,entry['CN'])
    assert sha(patched)==entry['patched_asset_sha256'] and proof==entry['proof']
    frames=parse_frames(members[oam].data,len(tiles)//32)
    assert all(render_frame(tiles,f).tobytes()==render_frame(patched,f).tobytes() for f in frames[1:])
    replacements[art]=patched;proofs.append(dict(item_index=entry['item_index'],JP=entry['JP'],CN=entry['CN'],art_member=art,oam_member=oam,proof=proof))
assert len(replacements)==60
packed=replace_bounded(original,replacements);assert sha(packed)==manifest['candidate_archive_sha256']
fat=struct.unpack_from('<I',raw,0x48)[0];start,end=struct.unpack_from('<II',raw,fat+fid*8)
assert raw[start:end]==original and len(packed)==end-start
newraw=raw[:start]+packed+raw[end:];assert len(newraw)==len(raw)
assert newraw[:start]==raw[:start] and newraw[end:]==raw[end:]
newrd=NintendoDSRom(newraw);after=unpack(newrd.files[fid]);intervals=[]
assert all(a.data==b.data for i,(a,b) in enumerate(zip(members,after)) if i not in replacements)
for art,patched in replacements.items():
    assert after[art].data==patched;intervals.append([start+members[art].offset,start+members[art].offset+members[art].size])
assert newrd.arm9==rd.arm9 and newrd.arm7==rd.arm7 and all(a==b for i,(a,b) in enumerate(zip(rd.files,newrd.files)) if i!=fid)
out=ROOT/'work/builds/slime2_body2385_names60_crisp14_candidate02_dataonly.nds';assert not out.exists()
with out.open('xb') as f:f.write(newraw)
report=dict(candidate_path=str(out),candidate_sha256=sha(newraw),base_path=str(base),base_sha256=sha(raw),source_sha256=sha(source),
    body_records=2385,large_names_localized=60,changed_archive='hangar_data.bin',changed_members=sorted(replacements),proofs=proofs,
    name_graphic_only=True,all_non_name_frames_exact=True,all_OAM_palettes_unmodified=True,all_name_alpha_silhouettes_exact=True,
    no_new_code_or_runtime_allocation=True,sameROM_length=True,sameFAT_header=True,allowed_ROM_intervals=intervals,
    changed_graphic_bytes=sum(a!=b for a,b in zip(original,packed)),actual_chinese_runtime_tested=False,all60_actual_scenes_verified=False,complete_game=False)
with (P/(out.stem+'.json')).open('x',encoding='utf8') as f:json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
print('BUILT2385+60names',out,report['candidate_sha256'],'graphics changedbytes',report['changed_graphic_bytes'])
