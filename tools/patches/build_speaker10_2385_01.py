'''Experimental native10 fixed speaker captions; baseline2385 bodies/names60 remain.
No crossROM states. This script creates a fresh candidate and a static report.
'''
from pathlib import Path
import os
import argparse,hashlib,json,re,struct,sys,shutil,unicodedata
ROOT=Path(os.environ.get('GENKI_SLIME_ROOT', Path(__file__).resolve().parents[2]));W=ROOT/'work/nds-full';P=ROOT/'reports'
sys.path.insert(0,str(ROOT/'tools'))
from ndspy.rom import NintendoDSRom
from ndspy import fnt
from rs_format import unpack
from nds_build_extended import pack
from nds_speaker10 import apply_speaker10,atlas10,encode_names10,name_mapping,FONT,FONT_SHA
from nds_extended_codec import encode
from nds_audit_extended import inferred_charset
from nds_extended_codec import controls,decode
from text_codec import source_charset

def load(p):return json.loads(p.read_text('utf8'))
def sha(b):return hashlib.sha256(b).hexdigest()
def new(p,x):
    with p.open('x',encoding='utf8') as f:json.dump(x,f,ensure_ascii=False,indent=2);f.write('\n')

ap=argparse.ArgumentParser()
ap.add_argument('--reproduce-to',type=Path)
args=ap.parse_args()
repro=args.reproduce_to.resolve() if args.reproduce_to else None
if repro:
    assert repro.is_relative_to((ROOT/'work').resolve()),'Reproduction must stay in NDS work area'
    repro.mkdir(exist_ok=False)

base=ROOT/'work/builds/slime2_body2385_names60_crisp14_candidate02_dataonly.nds';raw=base.read_bytes()
assert sha(raw)=='3a87385bbfe9a98e7cdbb9faa842957fe2b5dceeecb369f58df3861b2b0aa76b'
rd=NintendoDSRom(raw);br=load(P/'slime2_body2385_crisp14_candidate01_ownerguard.json')
rows=load(W/'translations_body2385_review01.json');refs={r['id']:r for r in load(ROOT/'work/messages_jp.json')}
mapping=inferred_charset(rows,source_charset(rd.arm9));assert len(mapping)==1732
name_pairs={'スラリン':'史拉林','スラみ':'史拉米','ミイホン':'米洪','ドラお':'多拉奥',
    'おうさま':'国王','おうひ':'王后','ぱぱ':'爸爸','まま':'妈妈','パパ':'爸爸','ママ':'妈妈'}
glossary=load(W/'glossary_review12.json')
for jp,cn in name_pairs.items():
    assert all(c in mapping for c in cn)
    if jp in glossary:assert glossary[jp]==cn
fid=rd.filenames.idOf('font_data.bin');mid=rd.filenames.idOf('msgdata.bin')
fonts=[m.data for m in unpack(rd.files[fid])];old_members=unpack(rd.files[mid]);members=[bytearray(m.data) for m in old_members]
old_arm=rd.arm9;oldf=fonts[3];mapstart=br['engine']['maps_begin'];remaps=list(tuple(x) for x in br['remaps']);assert len(remaps)==2385
lookup={k:i for i,(k,v) in enumerate(remaps)};changed=[];nextrows=[]
for row in rows:
    match=re.search('<SPEAKER>(.*?)<SPEAKER>',row['translation'],re.S)
    if match and match.group(1) in name_pairs:
        jp=match.group(1);cn=name_pairs[jp];target=row['translation'][:match.start(1)]+cn+row['translation'][match.end(1):]
        data=encode_names10(target,rd.arm9,mapping);ref=refs[row['id']]
        assert controls(data)==controls(bytes.fromhex(ref['raw_hex']))
        visible=decode(data,source_charset(rd.arm9),{v:k for k,v in (list(mapping.items())+list(name_mapping().items()))})
        assert unicodedata.normalize('NFKC',visible)==unicodedata.normalize('NFKC',target),row['id']
        key=ref['member']<<16|ref['offset'];new_offset=len(members[ref['member']]);members[ref['member']]+=data
        i=lookup[key];assert remaps[i][0]==key;remaps[i]=(key,new_offset)
        changed.append(dict(id=row['id'],JP_speaker=jp,CN_speaker=cn,original_record_offset=ref['offset'],
            previous_relocated_offset=br['remaps'][i][1],new_relocated_offset=new_offset,target_bytes=len(data)))
        nextrows.append(dict(row,translation=target))
    else:nextrows.append(row)
assert changed and len(nextrows)==2385
for member in members:struct.pack_into('>I',member,0,len(member)-4)
small_start=(len(oldf)+31)//32*32
arm,font,prom=apply_speaker10(rd.arm9,oldf,max(mapping.values())+1,small_start)
small,proof=atlas10(name_mapping());ff=bytearray(font)
mapraw=b''.join(struct.pack('<II',*v) for v in remaps);assert len(mapraw)==len(oldf)-mapstart
ff[mapstart:]=mapraw;ff+=b'\x11'*(small_start-len(ff));ff+=small
fonts[3]=bytes(ff);rd.arm9=arm;rd.files[fid]=pack(fonts);rd.files[mid]=pack(members)
result=rd.save(updateDeviceCapacity=True);after=NintendoDSRom(result);before=NintendoDSRom(raw)
assert len(after.arm9)==len(before.arm9) and after.arm7==before.arm7
assert fnt.save(after.filenames)==fnt.save(before.filenames)
assert all(a==b for i,(a,b) in enumerate(zip(after.files,before.files)) if i not in [fid,mid])
assert after.arm9OverlayTable==before.arm9OverlayTable and after.arm7OverlayTable==before.arm7OverlayTable
assert result[:0x20]==raw[:0x20]
for off in [0x24,0x28,0x2c,0x34,0x38,0x3c]:assert result[off:off+4]==raw[off:off+4]
newfont=[x.data for x in unpack(after.files[fid])]
assert newfont[:3]==fonts[:3] and newfont[3]==bytes(ff)
assert newfont[3][0x9000:mapstart]==oldf[0x9000:mapstart]
assert newfont[3][small_start:]==small
newmsg=unpack(after.files[mid]);byid={x['id']:x for x in changed}
for i,(old,newm) in enumerate(zip(old_members,newmsg)):assert old.data[4:]==newm.data[4:len(old.data)]
for row in nextrows:
    ref=refs[row['id']];key=ref['member']<<16|ref['offset'];off=dict(remaps)[key]
    data=(encode_names10(row['translation'],after.arm9,mapping) if row['id'] in byid
        else encode(row['translation'],source_charset(after.arm9),mapping))
    assert newmsg[ref['member']].data[off:off+len(data)]==data,row['id']
    assert controls(data)==controls(bytes.fromhex(ref['raw_hex']))
out=(repro if repro else ROOT/'work/builds')/'slime2_body2385_names60_speaker10_candidate01_experimental.nds';assert not out.exists()
with out.open('xb') as f:f.write(result)
new((repro if repro else W)/'translations_body2385_speaker10_experiment01.json',nextrows)
report=dict(candidate_path=str(out),candidate_sha256=sha(result),base_path=str(base),base_sha256=sha(raw),
    original_source_sha256=br['original_source_sha256'],body_records=2385,large_graphic_names=60,
    fixed_speaker_labels_changed_records=len(changed),speaker_name_pairs=name_pairs,
    changes=changed,engine_patch=prom,small_atlas_start=small_start,small_atlas_bytes=len(small),
    new_runtime_bytes_vs_base=len(ff)-len(oldf),font_member3_bytes=len(ff),font_glyph_count=1732,
    small_glyphs=proof,body_atlas_exact=True,original_text_bytes_and_offsets_preserved=True,
    original_four_font_members_preserved_except_declared_helpers_maps_append=True,
    all_target_controls_and_unicode_readback=True,ARM9_allocation_and_BSS_unchanged=True,
    ARM7_and_other255_NitroFS_files_unchanged=True,
    font_source=dict(path=str(FONT),sha256=FONT_SHA,license='OFL with inherited component notices;project existing local release asset,API archive SHA verified,not newly authored glyphs'),
    remaps=remaps,runtime_actualChinese_speaker_tested=False,dynamic_player_and_saved_names_translated=False,
    all_changed_speaker_scenes_tested=False,full_playthrough=False,complete_localization=False,
    fixed_FA_payload_guard=True,artifact_kind='EXPERIMENT_NOT_FINAL_OR_RECOMMENDED_UNTIL_NATIVE_QA')
new((repro if repro else P)/(out.stem+'.json'),report)
notices=(repro if repro else W)/'speaker10_font_notices01';notices.mkdir(exist_ok=False)
for fn in (W/'fonts10').rglob('*.txt'):
    rel=fn.relative_to(W/'fonts10');dst=notices/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(fn,dst)
new(notices/'source.json',report['font_source'])
if repro:
    expected=(ROOT/'work/builds'/out.name).read_bytes()
    assert result==expected,'Independent new-process reconstruction differs'
    new(repro/'byte_exact_reproduction01.json',dict(candidate_sha256=sha(result),same_bytes=True,
        new_Python_process=True,original_base_sha256=sha(raw),source_glyph_asset_sha256=FONT_SHA,
        font_license_notices_copied=True,scene_QA_not_implied=True))
print('BUILT speaker10 EXPERIMENT',out,'SHA',sha(result),'name_records',len(changed),'RAMextra',len(ff)-len(oldf))
