"""Append reviewed NDS records onto frozen09 without reassigning any glyph IDs.
Creates isolated experiments ONLY. Consumer evidence/runtime QA is independent.
No ARM instruction changes, source edits, save edits or active-ROM promotion.
"""
from pathlib import Path
import os
import sys,json,re,struct,hashlib,unicodedata,argparse
R=Path(os.environ.get('GENKI_SLIME_ROOT', Path(__file__).resolve().parents[2]));W=R/'work/nds-full';HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(R/'tools'),str(W)]
from ndspy.rom import NintendoDSRom
from ndspy import fnt
from rs_format import unpack,FormatError
from nds_build_extended import pack,body_chars
from nds_audit_extended import inferred_charset,tile_pixels
from nds_extended_codec import extended_slots,controls,decode
from nds_speaker10 import encode_names10
from text_codec import source_charset
from font_renderer import draw_glyph
from nds_layout import line_layout
BASE=R/'work/builds/slime2_cn_clear_font_preview09.nds'
BASESHA='0bc058df09fd5830cdcde9940be008b9c6dc25afb0967b1f450c57fd1f01a200'
SOURCESHA='53a90729e750bf7288b41d205072138c14941e8810af70f4dc71a5dca6b5ba7b'
OLDMAPBEGIN=0x41000;OLDMAPCOUNT=2385;OLDCAP=285344;FONTLIMIT=1741
LITERALS={0x8070:FONTLIMIT,0x88d4:OLDMAPBEGIN,0x88d8:OLDMAPCOUNT,0x8e40:OLDCAP}
def sha(b):return hashlib.sha256(b).hexdigest()
def load(p):return json.loads(Path(p).read_text('utf-8-sig'))
def once(p,obj):
 with Path(p).open('x',encoding='utf8') as f:json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n')
def build(selected,outdir,preserve_new_source_speakers=True,overrides=None):
 raw=BASE.read_bytes();assert sha(raw)==BASESHA
 srcraw=(R/'inputs/genki_slime2_jp.nds').read_bytes();assert sha(srcraw)==SOURCESHA
 original=NintendoDSRom(srcraw);rd=NintendoDSRom(raw);old=NintendoDSRom(raw);cs=source_charset(original.arm9)
 refs={x['id']:x for x in load(R/'work/messages_jp.json')}
 reviewed={x['id']:x for x in load(W/'reviewed_text3550_including_holds06.json')}
 oldrows=load(R/'work/builds/translations_body2385_names7_experimental08.json');oldids={x['id'] for x in oldrows}
 assert selected and len(set(selected))==len(selected) and set(selected)<=set(reviewed) and not set(selected)&oldids
 blanks=set(load(R/'reports/nds_full_text_coverage3550_drafts0_census06.json')['blank_IDs']);assert not set(selected)&blanks
 rows=[dict(reviewed[i]) for i in sorted(selected)]
 overrides=[] if overrides is None else overrides
 assert len({x['id'] for x in overrides})==len(overrides)
 for edit in overrides:
  assert edit['id'] in selected
  row=next(x for x in rows if x['id']==edit['id'])
  assert row['source']==edit['source'] and row['translation']==edit['old_translation']
  row['translation']=edit['translation']
 # Reuse only source/target fixed-name identities already accepted in old rows.
 namepairs={}
 for row in oldrows:
  s=re.search(r'<SPEAKER>(.*?)<SPEAKER>',row['source'],re.S);t=re.search(r'<SPEAKER>(.*?)<SPEAKER>',row['translation'],re.S)
  if s and t and s[1]!=t[1]:
   if s[1] in namepairs:assert namepairs[s[1]]==t[1]
   namepairs[s[1]]=t[1]
 if preserve_new_source_speakers:namepairs={} # New caption headers not certified for forced16px private mode1
 names=load(R/'work/builds/slime2_cn_fixed_names7_experimental08.json')['private_map']
 mapping=inferred_charset(load(W/'translations_body2385_review01.json'),cs);frozenmap=dict(mapping)
 assert len(mapping)==1732 and max(mapping.values())==1738
 required=set().union(*(body_chars(row['translation'],__import__('build_alpha').base_encoder(cs)) for row in rows))
 newchars=sorted(required-set(mapping));available=[i for i in extended_slots() if FONTLIMIT<=i<0xE00]
 assert len(newchars)<=len(available)
 for c,i in zip(newchars,available):mapping[c]=i
 limit=max([1740,*mapping.values()])+1;pages=(limit+255)//256
 fid=rd.filenames.idOf('font_data.bin');mid=rd.filenames.idOf('msgdata.bin')
 fonts=[m.data for m in unpack(rd.files[fid])];oldfont=fonts[3];members=[bytearray(m.data) for m in unpack(rd.files[mid])]
 oldmembers=[bytes(m) for m in members];originalmembers=unpack(original.files[mid]);assert len(oldfont)==318112
 for off,val in LITERALS.items():assert struct.unpack_from('<I',oldfont,off)[0]==val
 assert oldfont[0x801c:0x8020]==bytes.fromhex('1a0054e3')
 oldmaps=[struct.unpack_from('<II',oldfont,OLDMAPBEGIN+i*8) for i in range(OLDMAPCOUNT)];remaps=dict(oldmaps)
 assert oldmaps==[tuple(t) for t in load(R/'work/builds/slime2_cn_fixed_names7_experimental08.json')['remaps']]
 changes=[];newnamecount=0
 for row in rows:
  ref=refs[row['id']];assert row['source']==ref['text']
  source=bytes.fromhex(ref['raw_hex']);assert originalmembers[ref['member']].data[ref['offset']:ref['offset']+len(source)]==source
  t=row['translation'];s=re.search(r'<SPEAKER>(.*?)<SPEAKER>',t,re.S)
  if s and s[1] in namepairs:
   t=t[:s.start(1)]+namepairs[s[1]]+t[s.end(1):];newnamecount+=1
  row['translation']=t;data=encode_names10(t,original.arm9,mapping,names)
  assert controls(data)==controls(source),row['id']
  key=ref['member']<<16|ref['offset'];assert key not in remaps
  off=len(members[ref['member']]);members[ref['member']]+=data;remaps[key]=off
  changes.append(dict(id=row['id'],key=key,offset=off,bytes=len(data),mode23_assumption_lines=line_layout(data,original.arm9),natural_scene_verified=False))
 for m in members:struct.pack_into('>I',m,0,len(m)-4)
 atlas=bytearray(oldfont[0x9000:OLDMAPBEGIN]);atlas.extend(b'\x11'*(pages*32768-len(atlas)));glyphs=[]
 for c in newchars:
  i=mapping[c];pg=i//256;page=bytearray(atlas[pg*32768:(pg+1)*32768]);info=draw_glyph(page,i%256,c,'crisp14',14)
  atlas[pg*32768:(pg+1)*32768]=page;glyphs.append(dict(info,index=i))
 # New IDs may legally occupy previously blank slots of old last page.
 # Freeze every used old glyph/system slot; authorize only new empty slots.
 from font_renderer import glyph_offsets
 slotbytes=set()
 for ch in newchars:
  i=mapping[ch];pg=i//256
  if pg>=7:continue
  oldpage=oldfont[0x9000+pg*32768:0x9000+(pg+1)*32768]
  assert tile_pixels(oldpage,i%256)==bytearray([1]*256)
  for off in glyph_offsets(i%256):slotbytes.update(range(pg*32768+off,pg*32768+off+32))
 assert all(a==b or i in slotbytes for i,(a,b) in enumerate(zip(oldfont[0x9000:OLDMAPBEGIN],atlas)))
 for i in [*frozenmap.values(),1739,1740]:
  pg=i//256
  assert tile_pixels(atlas[pg*32768:(pg+1)*32768],i%256)==tile_pixels(oldfont[0x9000+pg*32768:0x9000+(pg+1)*32768],i%256)
 maps=sorted(remaps.items());newmapbegin=0x9000+len(atlas);table=b''.join(struct.pack('<II',*e) for e in maps)
 cap=(newmapbegin+len(table)+31)//32*32
 ff=bytearray(oldfont[:0x9000]);values={0x8070:limit,0x88d4:newmapbegin,0x88d8:len(maps),0x8e40:cap}
 for off,v in values.items():struct.pack_into('<I',ff,off,v)
 allowed={i for off in values for i in range(off,off+4)}
 assert all(a==b or i in allowed for i,(a,b) in enumerate(zip(oldfont[:0x9000],ff)))
 ff+=atlas;ff+=table;ff+=b'\x11'*(cap-len(ff));ff+=oldfont[OLDCAP:]
 assert len(ff)==cap+32768 and ff[cap:]==oldfont[OLDCAP:]
 fonts[3]=bytes(ff);rd.files[fid]=pack(fonts);rd.files[mid]=pack(members)
 result=rd.save(updateDeviceCapacity=True);final=NintendoDSRom(result)
 assert final.arm9==old.arm9 and final.arm7==old.arm7 and final.arm9OverlayTable==old.arm9OverlayTable and final.arm7OverlayTable==old.arm7OverlayTable
 assert fnt.save(final.filenames)==fnt.save(old.filenames)
 assert [i for i,(a,b) in enumerate(zip(final.files,old.files)) if a!=b]==sorted([fid,mid])
 ffinal=[m.data for m in unpack(final.files[fid])];mfinal=[m.data for m in unpack(final.files[mid])];assert ffinal==fonts and mfinal==[bytes(m) for m in members]
 assert ffinal[:3]==[m.data for m in unpack(old.files[fid])][:3]
 for a,b in zip(oldmembers,mfinal):assert a[4:]==b[4:len(a)]
 reverse={v:k for k,v in list(mapping.items())+list(names.items())}
 for row in rows:
  ref=refs[row['id']];off=remaps[ref['member']<<16|ref['offset']];m=mfinal[ref['member']];b=m[off:m.index(0xF8,off)+1]
  assert controls(b)==controls(bytes.fromhex(ref['raw_hex']))
  assert unicodedata.normalize('NFKC',decode(b,cs,reverse))==unicodedata.normalize('NFKC',row['translation'])
 for key,off in oldmaps:assert remaps[key]==off
 assert all(mapping[c]==i for c,i in frozenmap.items()) and set(mapping.values()).isdisjoint({1739,1740,*names.values()})
 report=dict(kind='NDS reviewed-record append EXPERIMENT;not promoted or complete',candidate_SHA256=sha(result),baseline_SHA256=BASESHA,source_SHA256=SOURCESHA,new_records=len(rows),body_records=2385+len(rows),old_body2385_unicode_bytes_offsets_frozen=True,new_known_fixed_name_occurrences=newnamecount,new_source_speaker_headers_preserved=preserve_new_source_speakers,old_private_names25_IDs_pixels_frozen=True,old_system_yesno2_IDs_pixels_frozen=True,old_pause4_and_graphicnames60_frozen=True,old_body1732_IDs_pixels_frozen=True,new_glyphs=glyphs,body_pages=pages,font_member3_bytes=len(ff),font_RAM_extra_vs09_bytes=len(ff)-len(oldfont),fullgame_peak_RAM_verified=False,ARM9_ARM7_overlays_BSS_and_instructions_unchanged=True,only_msgdata_font_data_changed=True,helper_changed_data_literals=[dict(offset=hex(off),old=LITERALS[off],new=v) for off,v in values.items()],remaps=maps,body_mapping=mapping,private_mapping=names,caption_atlas_start=cap,changes=changes,consumer_proof_NOT_implied_by_build=True,parent_layout_overrides=overrides,source_controls_dynamic_parameters_roundtrip_all_pass=True,natural_newSHA_runtime_verified=False,all_story_translated=False,full_playthrough=False)
 outdir.mkdir(parents=True,exist_ok=False);out=outdir/'slime2_cn_reviewed_append_experimental10.nds'
 with out.open('xb') as f:f.write(result)
 report['candidate_path']=str(out);once(out.with_suffix('.json'),report);once(outdir/'translations_appended10.json',oldrows+rows)
 assert BASE.read_bytes()==raw and (R/'inputs/genki_slime2_jp.nds').read_bytes()==srcraw
 return report
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--ids',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--overrides',type=Path);args=ap.parse_args()
 rr=build(load(args.ids),args.out,overrides=load(args.overrides) if args.overrides else None);print(json.dumps({k:rr[k] for k in ['candidate_path','candidate_SHA256','new_records','body_records','new_known_fixed_name_occurrences','body_pages','font_member3_bytes','font_RAM_extra_vs09_bytes']},ensure_ascii=False,indent=2))
