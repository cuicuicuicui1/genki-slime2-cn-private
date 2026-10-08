"""Build a source-locked, expanded NDS CJK/relocation experiment.
Original message offsets retain their bytes. A sorted resource-owned remap
redirects selected member/offset lookups to newly appended complete strings.
Rebuild NitroFS because font and message allocations grow. No equal-length
translation requirement, truncation, arbitrary free-space write or ARM9 growth.
"""
from pathlib import Path
import sys, json, struct, hashlib, re, unicodedata
from ndspy.rom import NintendoDSRom
from ndspy import fnt
from rs_format import unpack, FormatError
from text_codec import source_charset
from font_renderer import draw_glyph, profile_manifest
from nds_extended_codec import cjk, extended_slots, encode, decode, controls, tokenize
from nds_extended_engine import apply_engine, ATLAS_BEGIN

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'work/builds/slime2_opening_candidate03_fontcrisp.nds'
BASE_HASH='d0a8db606f20bdd1ce112287d3fca48b47fb9b8f2ea2ef52d973b1488b9e6ccb'
SOURCE_HASH='53a90729e750bf7288b41d205072138c14941e8810af70f4dc71a5dca6b5ba7b'


def sha(raw):return hashlib.sha256(raw).hexdigest()


def pack(members):
    payload=bytearray();header=bytearray(struct.pack('<I',len(members)))
    for data in members:
        header+=struct.pack('<II',len(payload),len(data));payload+=data
    return bytes(header+payload)


def body_chars(text, source_encoder):
    from build_alpha import markup_parts
    speaker=False;out=set()
    for p in markup_parts(text):
        if p=='<SPEAKER>':speaker=not speaker
        elif p.startswith('<') or p=='\n':continue
        elif not speaker:out.update(ch for ch in p if cjk(ch) or ch not in source_encoder)
    return out


def build(translations, outpath):
    outpath=Path(outpath).resolve()
    if outpath.exists():raise FormatError('Never overwrite existing candidate')
    source=(ROOT/'inputs/genki_slime2_jp.nds').read_bytes()
    if sha(source)!=SOURCE_HASH:raise FormatError('Unexpected original source')
    baseraw=BASE.read_bytes()
    if sha(baseraw)!=BASE_HASH:raise FormatError('Unexpected selected clear-font base')
    base=NintendoDSRom(baseraw);rom=NintendoDSRom(baseraw);arm=bytearray(rom.arm9)
    refs={r['id']:r for r in json.loads((ROOT/'work/messages_jp.json').read_text('utf8'))}
    if not translations or len({r['id'] for r in translations})!=len(translations):
        raise FormatError('Empty or duplicate translation set')
    cs=source_charset(arm)
    # Existing common source slots already use the declared simplified glyphs.
    base_report=json.loads((ROOT/'reports/slime2_opening_candidate03_fontcrisp.json').read_text('utf8'))
    for info in base_report['han_variant_glyphs']:cs[info['codepoint']]=info['target']
    from build_alpha import base_encoder
    source_encoder=base_encoder(source_charset(arm))
    chars=sorted(set().union(*(body_chars(r['translation'],source_encoder) for r in translations)))
    slots=extended_slots()
    if len(chars)>len(slots):raise FormatError('Expanded glyph budget exceeded')
    extra=dict(zip(chars,slots));maxcode=max(extra.values())
    pages=(maxcode+256)//256;atlas=bytearray(b'\x11'*(pages*32768));glyphs=[]
    for ch,index in extra.items():
        bank=index//256;data=bytearray(atlas[bank*32768:(bank+1)*32768])
        info=draw_glyph(data,index%256,ch,'crisp14',14)
        atlas[bank*32768:(bank+1)*32768]=data
        glyphs.append(dict(info,extended_index=index,texture_page=bank))
    font_id=rom.filenames.idOf('font_data.bin');msg_id=rom.filenames.idOf('msgdata.bin')
    oldmsg=unpack(rom.files[msg_id]);members=[bytearray(m.data) for m in oldmsg];remaps=[];records=[]
    for row in sorted(translations,key=lambda r:(refs[r['id']]['member'],refs[r['id']]['offset'])):
        ref=refs[row['id']]
        if row['source']!=ref['text']:raise FormatError('Source drift '+row['id'])
        source_speaker=re.search(r'<SPEAKER>(.*?)<SPEAKER>',ref['text'],re.S)
        target_speaker=re.search(r'<SPEAKER>(.*?)<SPEAKER>',row['translation'],re.S)
        if source_speaker and (not target_speaker or source_speaker.group(1)!=target_speaker.group(1)):
            raise FormatError('Small speaker consumer not yet extended '+row['id'])
        # Source-side simplified table affects glyph pixels only; use original
        # CP932 charset for preserved small labels, normalized variants in body
        # all use the new atlas. Source source_char keys remain encodable.
        source_cs=source_charset(arm)
        body=encode(row['translation'],source_cs,extra)
        if controls(body)!=controls(bytes.fromhex(ref['raw_hex'])):
            raise FormatError('Control skeleton changed '+row['id'])
        if ref['offset']>=65536 or ref['member']>=65536:
            raise FormatError('Original remap key exceeds 16-bit fields')
        offset=len(members[ref['member']]);members[ref['member']]+=body
        remaps.append((ref['member']<<16|ref['offset'],offset))
        records.append({'id':row['id'],'member':ref['member'],'original_offset':ref['offset'],
                        'relocated_offset':offset,'original_slot_bytes':ref['size'],
                        'translated_bytes':len(body),'text':row['translation']})
    for m in members:struct.pack_into('>I',m,0,len(m)-4)
    fonts=[m.data for m in unpack(rom.files[font_id])]
    if len(fonts)!=4 or len(fonts[3])!=32768:raise FormatError('Unexpected base font lifecycle')
    code,engine=apply_engine(arm,rom.arm9[0x9b478:0x9b568],maxcode+1,remaps,len(atlas))
    mapraw=b''.join(struct.pack('<II',*r) for r in remaps)
    fonts[3]=fonts[3]+code+atlas+mapraw
    if len(fonts[3])!=engine['maps_begin']+len(mapraw):raise FormatError('Resource-owned map boundary mismatch')
    rom.arm9=bytes(arm);rom.files[font_id]=pack(fonts);rom.files[msg_id]=pack(members)
    raw=rom.save(updateDeviceCapacity=True);final=NintendoDSRom(raw)
    if final.arm9!=rom.arm9 or final.arm7!=base.arm7:raise FormatError('ARM component readback drift')
    if final.files[font_id]!=rom.files[font_id] or final.files[msg_id]!=rom.files[msg_id]:raise FormatError('NitroFS expanded readback drift')
    if any(final.files[i]!=base.files[i] for i in range(len(base.files)) if i not in [font_id,msg_id]):raise FormatError('Nontarget file content changed')
    if fnt.save(final.filenames)!=fnt.save(base.filenames):raise FormatError('FNT identity changed')
    finalmsg=unpack(final.files[msg_id]);extended_cs={v:k for k,v in extra.items()}
    for r in records:
        m=finalmsg[r['member']];body=m.data[r['relocated_offset']:r['relocated_offset']+r['translated_bytes']]
        visible=decode(body,source_charset(final.arm9),extended_cs)
        if unicodedata.normalize('NFKC',visible)!=unicodedata.normalize('NFKC',r['text']):raise FormatError('Final extended record Unicode drift')
    for i,(a,b) in enumerate(zip(oldmsg,finalmsg)):
        if a.data[4:]!=b.data[4:len(a.data)]:raise FormatError('Original message bytes relocated or changed')
    if len(final.arm9)!=len(base.arm9):raise FormatError('ARM9 grew into BSS')
    outpath.parent.mkdir(parents=True,exist_ok=True);outpath.write_bytes(raw)
    report={'original_source_sha256':sha(source),'clear_font_base_sha256':sha(baseraw),
            'candidate_sha256':sha(raw),'candidate_path':str(outpath),'bytes':len(raw),
            'engine':engine,'glyphs':glyphs,'glyph_count':len(glyphs),
            'glyph_address_budget':len(slots),'atlas_page_count':pages,
            'atlas_bytes':len(atlas),'font_member3_bytes':len(fonts[3]),
            'extra_runtime_bytes_relative_to_candidate03':len(fonts[3])-32768,
            'old_record_offsets_and_bytes_preserved':True,'records':records,
            'mapped_record_count':len(records),'remaps':remaps,
            'nontarget_file_content_unchanged':True,'ARM7_unchanged':True,
            'ARM9_allocation_unchanged':True,'ARM9_BSS_and_heap_address_limits_unchanged':True,
            'font_profile':profile_manifest('crisp14'),'raw_terminator_holes_enforced':True,
            'NitroFS_rebuilt_for_growing_files':True,'runtime_status':'not_run',
            'complete_localization':False,'small_speaker_CJK':False,
            'artifact_kind':'extended_engine_experiment_not_final_release'}
    (ROOT/'reports'/(outpath.stem+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print('BUILT',outpath,'SHA',sha(raw),'RECORDS',len(records),'GLYPHS',len(chars),'HEAP_EXTRA',len(fonts[3])-32768)
    return report


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('translations',type=Path);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();build(json.loads(args.translations.read_text('utf8')),args.out)
