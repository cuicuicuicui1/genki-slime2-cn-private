'''New22 HP mode2 records plus packed native8 infrastructure. EXPERIMENT ONLY.
Keep the current recommended5D candidate untouched. QA flag makes fixed FA
names use8px solely to naturally exercise the same packed0 texture pipeline;
the normal experiment retains clearer native10 labels. No new translations
from unreviewed drafts or undocumented consumer assumptions are inserted.
'''
from pathlib import Path
import os
import argparse,json,hashlib,re,struct,sys,unicodedata
R=Path(os.environ.get('GENKI_SLIME_ROOT', Path(__file__).resolve().parents[2]));W=R/'work/nds-full';P=R/'reports'
sys.path.insert(0,str(R/'tools'))
from ndspy.rom import NintendoDSRom
from ndspy import fnt
from rs_format import unpack
from nds_build_extended import pack
from nds_extended_engine import make_helpers
from nds_extended_codec import encode,decode,controls
from nds_audit_extended import inferred_charset,check_atlas
from nds_speaker10 import apply_speaker10,atlas10,name_mapping
from nds_small_speaker import encode_speaker_names
from nds_native8_body import apply_native8_body
from nds_packed_font8 import pack_glyphs
from text_codec import source_charset
from font_renderer import draw_glyph

def load(p):return json.loads(p.read_text('utf8'))
def sha(b):return hashlib.sha256(b).hexdigest()
def new(p,x):
    with p.open('x',encoding='utf8') as f:json.dump(x,f,ensure_ascii=False,indent=2);f.write('\n')
ap=argparse.ArgumentParser();ap.add_argument('--qa-small-font',action='store_true')
ap.add_argument('--revision',choices=['01','02'],default='02');args=ap.parse_args()
kind='native8_FA_QA' if args.qa_small_font else 'native10'
out=R/f'work/builds/slime2_body2407_names60_{kind}_packed8_experimental{args.revision}.nds'
assert not out.exists()
source=R/'work/builds/slime2_body2385_names60_crisp14_speaker10_candidate01.nds';raw=source.read_bytes()
assert sha(raw)=='5d39c1e2aa878dd3fbdfd81e56e57f1aed421009258fabeae64f9015c9f18a7a'
rd=NintendoDSRom(raw);original=NintendoDSRom((R/'inputs/genki_slime2_jp.nds').read_bytes())
assert sha((R/'inputs/genki_slime2_jp.nds').read_bytes())=='53a90729e750bf7288b41d205072138c14941e8810af70f4dc71a5dca6b5ba7b'
proof=load(P/'nds_hp12_mode2_original_consumer_proof01.json')
assert proof['records']==22 and proof['safe_for_experimental_mode2_record_insertion']
ids={x['id'] for x in proof['checks']};hp=[x for x in load(W/'hp12_parent_review01.json') if x['id'] in ids]
assert len(hp)==22
oldrows=load(W/'translations_body2385_review01.json');current=load(W/'translations_body2385_speaker10_experiment01.json')
cs=source_charset(original.arm9);mapping=inferred_charset(oldrows,cs);base_mapping=dict(mapping)
required=inferred_charset(oldrows+hp,cs);newchars=sorted(set(required)-set(mapping))
nextid=max(mapping.values())+1
for ch in newchars:
    while nextid&255==0xF8:nextid+=1
    assert nextid<0xE00;mapping[ch]=nextid;nextid+=1
assert all(mapping[ch]==slot for ch,slot in base_mapping.items())
refs={x['id']:x for x in load(R/'work/messages_jp.json')}
fid=rd.filenames.idOf('font_data.bin');mid=rd.filenames.idOf('msgdata.bin')
fonts=[x.data for x in unpack(rd.files[fid])];oldfont=fonts[3]
members=[bytearray(x.data) for x in unpack(rd.files[mid])];oldmembers=[bytes(m) for m in members]
meta=load(P/'slime2_body2385_names60_speaker10_candidate01_experimental.json')
remaps=dict(meta['remaps']);changed=[];qaids=set()
if args.qa_small_font:
    qaids={x['id'] for x in meta['changes']};assert len(qaids)==243
    for row in current:
        if row['id'] not in qaids:continue
        ref=refs[row['id']];data=encode_speaker_names(row['translation'],original.arm9,mapping)
        assert controls(data)==controls(bytes.fromhex(ref['raw_hex']))
        key=ref['member']<<16|ref['offset'];off=len(members[ref['member']]);members[ref['member']]+=data
        remaps[key]=off;changed.append(dict(id=row['id'],kind='QA_ONLY_native8_fixed_FA_name',offset=off))
for row in hp:
    ref=refs[row['id']];key=ref['member']<<16|ref['offset'];assert key not in remaps
    data=encode(row['translation'],cs,mapping);assert controls(data)==controls(bytes.fromhex(ref['raw_hex']))
    off=len(members[ref['member']]);members[ref['member']]+=data;remaps[key]=off
    changed.append(dict(id=row['id'],kind='new_HP_mode2_description_or_denial',offset=off))
for m in members:struct.pack_into('>I',m,0,len(m)-4)
remaps=sorted(remaps.items());assert len(remaps)==2407
mapstart=266240;atlas=bytearray(oldfont[0x9000:mapstart]);assert len(atlas)==7*32768
newglyphs=[]
for ch in newchars:
    index=mapping[ch];pg=index//256;within=index%256;page=bytearray(atlas[pg*32768:(pg+1)*32768])
    newglyphs.append(dict(draw_glyph(page,within,ch,'crisp14',14),global_index=index))
    atlas[pg*32768:(pg+1)*32768]=page
assert check_atlas(bytes(atlas),mapping)==len(mapping)
code,helpers,maps=make_helpers(original.arm9[0x9B478:0x9B568],max(mapping.values())+1,remaps,len(atlas))
assert maps==mapstart
newbase=oldfont[:0x8000]+code+bytes(atlas)+b''.join(struct.pack('<II',*item) for item in remaps)
caption_start=(len(newbase)+31)//32*32
legacy=NintendoDSRom((R/'work/builds/slime2_body2385_names60_crisp14_candidate02_dataonly.nds').read_bytes())
assert sha((R/'work/builds/slime2_body2385_names60_crisp14_candidate02_dataonly.nds').read_bytes())=='3a87385bbfe9a98e7cdbb9faa842957fe2b5dceeecb369f58df3861b2b0aa76b'
arm,font,captionproof=apply_speaker10(legacy.arm9,newbase,max(mapping.values())+1,caption_start)
assert arm==rd.arm9,'No additional ARM/BSS changes should be needed'
cap,_=atlas10(name_mapping());font+=b'\x11'*(caption_start-len(font))+cap
packed_start=len(font);packed,packproof=pack_glyphs(mapping,max(mapping.values())+1)
arm,font,nativeproof=apply_native8_body(arm,font,max(mapping.values())+1,packed_start,packed_start+len(packed))
if args.qa_small_font:
    f=bytearray(font);assert struct.unpack_from('<I',f,0x8C28)[0]==0xE3A03001
    struct.pack_into('<I',f,0x8C28,0xE3A03000);font=bytes(f)
font+=packed+b'\x11'*32;fonts[3]=font;rd.arm9=arm;rd.files[fid]=pack(fonts);rd.files[mid]=pack(members)
result=rd.save(updateDeviceCapacity=True);final=NintendoDSRom(result);before=NintendoDSRom(raw)
assert final.arm9==before.arm9 and final.arm7==before.arm7
assert final.arm9OverlayTable==before.arm9OverlayTable and final.arm7OverlayTable==before.arm7OverlayTable
assert fnt.save(final.filenames)==fnt.save(before.filenames)
assert all(a==b for i,(a,b) in enumerate(zip(final.files,before.files)) if i not in [fid,mid])
ff=[x.data for x in unpack(final.files[fid])];fm=[x.data for x in unpack(final.files[mid])]
assert ff==fonts and all(m[4:len(o)]==o[4:] for m,o in zip(fm,oldmembers))
canonical=sorted(current+hp,key=lambda x:(int(x['id'].split(':')[0]),int(x['id'].split(':')[1],16)))
reverse={v:k for k,v in list(mapping.items())+list(name_mapping().items())};mapsdict=dict(remaps);checks=[]
for row in canonical:
    ref=refs[row['id']];key=ref['member']<<16|ref['offset'];off=mapsdict[key];m=fm[ref['member']]
    rawrecord=m[off:m.index(0xF8,off)+1]
    assert controls(rawrecord)==controls(bytes.fromhex(ref['raw_hex']))
    assert unicodedata.normalize('NFKC',decode(rawrecord,cs,reverse))==unicodedata.normalize('NFKC',row['translation']),row['id']
    checks.append(dict(id=row['id'],controls_exact=True,Unicode_roundtrip=True,
        newly_inserted_mode2=row['id'] in ids,QA_native8_name=row['id'] in qaids))
with out.open('xb') as f:f.write(result)
new(W/f'translations_body2407_{kind}_experimental{args.revision}.json',canonical)
report=dict(candidate_path=str(out),candidate_sha256=sha(result),previous_sha256=sha(raw),
    source_sha256=sha((R/'inputs/genki_slime2_jp.nds').read_bytes()),body_records=2407,new_HP_records22=sorted(ids),
    graphical_names60_unchanged=True,new_fixed_caption_records=0,QA_native8_name_occurrences=len(qaids),
    QA_flag=args.qa_small_font,new_native14_glyphs=newglyphs,body_glyph_count=len(mapping),mapping=mapping,
    existing1732_body_glyph_IDs_and_pixels_unchanged=True,caption_atlas_start=caption_start,
    captionproof=captionproof,packedproof=packproof,nativeproof=nativeproof,records=checks,remaps=remaps,
    maps_begin=maps,normal_helpers=helpers,font_member3_bytes=len(font),packed_start=packed_start,
    new_RAM_bytes_vs_current=len(font)-len(oldfont),ARM9_ARM7_and_BSS_unchanged=True,
    other255_NitroFS_files_vs_current_unchanged=True,source_message_bytes_preserved=True,
    static_HP_consumer_proof=str(P/'nds_hp12_mode2_original_consumer_proof01.json'),
    actual_HP_scene_verified=False,actual_packed8_font_draw_verified=False,
    runtime_status='not_run',artifact_kind='EXPERIMENT_ONLY_NOT_CURRENT_RECOMMENDED',
    all_story_translated=False,full_playthrough=False)
new(P/(out.stem+'.json'),report)
print('BUILT EXPERIMENT',out,'SHA',sha(result),'body2407;newHP22;newglyphs',newchars,
    'QA8names',len(qaids),'font RAM bytes',len(font),'delta',len(font)-len(oldfont))
