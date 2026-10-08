"""Final-byte audit of the NDS extension; does not call the ROM builder.
Checks resource bounds, unchanged consumers, independent atlas readback and
same-ROM loaded RAM. Controlled ARM tests / runtime scene coverage are separate.
"""
from pathlib import Path
import hashlib, json, re, struct, unicodedata, sys
from ndspy.rom import NintendoDSRom
from ndspy import fnt
from rs_format import unpack, FormatError
from text_codec import source_charset, decode as decode_source
from build_alpha import base_encoder
from nds_extended_codec import decode, controls, tokenize
from font_renderer import render_glyph
from nds_extended_engine import apply_engine
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC

ROOT = Path(__file__).resolve().parents[1]
SOURCE_HASH = '53a90729e750bf7288b41d205072138c14941e8810af70f4dc71a5dca6b5ba7b'
BASE_HASH = 'd0a8db606f20bdd1ce112287d3fca48b47fb9b8f2ea2ef52d973b1488b9e6ccb'
# Independent allowlist, not imported from the emitter.
ALLOWED = [(0x9A918,0x9A978),(0x9B478,0x9B568),(0x9BA50,0x9BA54),
           (0x9BB6C,0x9BC30),(0x9C560,0x9C564),(0x9B92C,0x9B930),
           (0x9D1FC,0x9D200)]
ATLAS = 0x9000


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(ok, message):
    if not ok:
        raise FormatError(message)



def check_source_reference(ref, member, charset):
    raw = bytes.fromhex(ref['raw_hex'])
    require(ref['offset'] >= 4 and ref['size'] == len(raw), 'Source reference boundary drift')
    require(member[ref['offset']:ref['offset']+ref['size']] == raw, 'Reference bytes not in locked original ROM')
    require(decode_source(raw,charset) == ref['text'], 'Reference text not original ROM decoded text')
    return True


def inferred_charset(rows, charset):
    old = base_encoder(charset)
    chars = set()
    for row in rows:
        speaker = False
        for part in re.split(r'(<[^<>]+>|\n)', row['translation']):
            if part == '<SPEAKER>':
                speaker = not speaker
            elif not speaker and not part.startswith('<') and part != '\n':
                chars.update(c for c in part if '\u3400' <= c <= '\u9fff' or c not in old)
        require(not speaker, 'Unclosed speaker')
    slots = [i for i in range(1,4096) if (i & 255) != 248]
    require(0 < len(chars) <= len(slots), 'Atlas budget')
    return dict(zip(sorted(chars),slots))


def tile_pixels(page, index):
    require(len(page) == 32768 and 0 <= index < 256, 'Atlas tile bounds')
    pixels = bytearray(256)
    for ty in range(2):
        for tx in range(2):
            start = ((index//16*2+ty)*32 + index%16*2+tx)*32
            for y in range(8):
                for x in range(4):
                    v = page[start+y*4+x]
                    dst = (ty*8+y)*16+tx*8+x*2
                    pixels[dst:dst+2] = bytes((v & 15, v >> 4))
    return pixels


def check_atlas(data, mapping):
    require(len(data) % 32768 == 0, 'Partial atlas page')
    by_index = {v:k for k,v in mapping.items()}
    checked = 0
    for index in range(len(data)//128):
        page = data[index//256*32768:(index//256+1)*32768]
        actual = tile_pixels(page,index%256)
        expected = render_glyph(by_index[index], 'crisp14',14)[0] if index in by_index else bytearray([1]*256)
        require(actual == expected, 'Atlas pixels differ at index '+str(index))
        checked += index in by_index
    require(checked == len(mapping), 'Missing atlas glyphs')
    return checked


def check_map(raw, expected):
    require(len(raw) == len(expected)*8, 'Relocation table length drift')
    entries = [struct.unpack_from('<II',raw,i) for i in range(0,len(raw),8)]
    keys = [x[0] for x in entries]
    require(keys == sorted(set(keys)), 'Unsorted or duplicate relocation keys')
    require(entries == expected, 'Relocation table redirects unexpected offset')
    return entries


def check_dispatch(raw):
    require(len(raw) == 0xF0, 'Copied dispatcher size')
    original = 0x0209B478
    code_end = 0x0209B55C
    cap = Cs(CS_ARCH_ARM,CS_MODE_ARM)
    cap.detail = True
    branches, literals = [], []
    for ins in cap.disasm(raw[:code_end-original],original):
        if ins.mnemonic.startswith('b') and ins.mnemonic not in ('bic','bics'):
            for op in ins.operands:
                if op.type == ARM_OP_IMM:
                    require(original <= op.imm < code_end, 'Copied dispatcher has external direct branch')
                    branches.append([ins.address,op.imm])
        for op in ins.operands:
            if op.type == ARM_OP_MEM and op.mem.base == ARM_REG_PC:
                target = ins.address+8+op.mem.disp
                require(original <= target and target+4 <= original+len(raw), 'Copied PC literal outside owner')
                literals.append([ins.address,target])
    require(branches and literals, 'Unexpected dispatcher structure')
    return {'internal_branches':branches,'owned_literals':literals,
            'literal_pool_copied_verbatim':True,'external_callback':'original blx register table, unchanged'}


def check_ram(raw, fonts):
    require(len(raw) == 0x400000, 'Main RAM dump size')
    ptrs = struct.unpack_from('<4I',raw,0x1453F0)
    ranges = []
    for n, (ptr, font) in enumerate(zip(ptrs,fonts)):
        off = ptr-0x02000000
        require(0 <= off and off+len(font) <= len(raw), 'Font pointer outside main RAM')
        require(raw[off:off+len(font)] == font, 'Loaded font/code/map differs from final ROM')
        ranges.append((ptr,ptr+len(font)))
    for i,a in enumerate(ranges):
        for b in ranges[i+1:]:
            require(a[1] <= b[0] or b[1] <= a[0], 'Loaded fonts overlap')
    return {'pointers':[hex(p) for p in ptrs], 'all_four_members_match_final_ROM':True,
            'expanded_code_and_map_loaded_exactly':True,'nonoverlapping_font_ranges':True,
            'allocator_lifetime_stress_test':False,'cache_coherence_on_hardware':False}


def audit(rompath, translationspath, reportpath=None, ramdir=None):
    raw = Path(rompath).read_bytes()
    source = (ROOT/'inputs/genki_slime2_jp.nds').read_bytes()
    baseraw = (ROOT/'work/builds/slime2_opening_candidate03_fontcrisp.nds').read_bytes()
    require(sha(source) == SOURCE_HASH and sha(baseraw) == BASE_HASH, 'Source lock failed')
    base, final = NintendoDSRom(baseraw), NintendoDSRom(raw)
    original = NintendoDSRom(source)
    sourcemsg = unpack(original.files[original.filenames.idOf('msgdata.bin')])
    sourcecs = source_charset(original.arm9)
    rows = json.loads(Path(translationspath).read_text('utf8'))
    refs = {r['id']:r for r in json.loads((ROOT/'work/messages_jp.json').read_text('utf8'))}
    require(rows and len({r['id'] for r in rows}) == len(rows), 'Empty/duplicate reviewed set')
    for row in rows:
        require(row['id'] in refs and row['source'] == refs[row['id']]['text'], 'Source text drift')
        ref = refs[row['id']]
        require(0 <= ref['member'] < len(sourcemsg), 'Source member outside original')
        check_source_reference(ref,sourcemsg[ref['member']].data,sourcecs)
        s = re.findall(r'<SPEAKER>(.*?)<SPEAKER>',row['source'],re.S)
        t = re.findall(r'<SPEAKER>(.*?)<SPEAKER>',row['translation'],re.S)
        require(s == t, 'Unsupported small-font caption translation')
    require(raw[:0x20] == baseraw[:0x20], 'Game identity drift')
    for headeroff in [0x24,0x28,0x2C,0x34,0x38,0x3C]:
        require(raw[headeroff:headeroff+4] == baseraw[headeroff:headeroff+4], 'CPU address/size changed')
    require(len(final.arm9) == len(base.arm9), 'ARM9 grew into BSS')
    require(final.arm7 == base.arm7, 'ARM7 drift')
    require(final.arm9OverlayTable == base.arm9OverlayTable and final.arm7OverlayTable == base.arm7OverlayTable, 'Overlay table drift')
    require(fnt.save(final.filenames) == fnt.save(base.filenames), 'FNT path/ID drift')
    require(len(final.files) == len(base.files), 'NitroFS file count drift')
    fontid, msgid = final.filenames.idOf('font_data.bin'), final.filenames.idOf('msgdata.bin')
    untouched_files = 0
    for i,(a,b) in enumerate(zip(final.files,base.files)):
        if i not in (fontid,msgid):
            require(a == b, 'Nontarget NitroFS file changed '+str(i))
            untouched_files += 1
    changed = [i for i,(a,b) in enumerate(zip(base.arm9,final.arm9)) if a != b]
    require(all(any(s <= i < e for s,e in ALLOWED) for i in changed), 'Undeclared ARM9 write')
    fonts = [x.data for x in unpack(final.files[fontid])]
    oldfonts = [x.data for x in unpack(base.files[fontid])]
    require(len(fonts) == len(oldfonts) == 4, 'Font member count drift')
    require(fonts[:3] == oldfonts[:3] and fonts[3][:0x8000] == oldfonts[3], 'Original font content changed')
    mapping = inferred_charset(rows,source_charset(base.arm9))
    pages = max(mapping.values())//256+1
    mapstart = ATLAS+pages*32768
    require(len(fonts[3]) == mapstart+8*len(rows), 'Expanded font/code/atlas/map boundary drift')
    glyphs = check_atlas(fonts[3][ATLAS:mapstart],mapping)
    require(fonts[3][0x8200:0x82F0] == base.arm9[0x9B478:0x9B568], 'Copied old dispatcher/literals drift')
    dispatcher = check_dispatch(fonts[3][0x8200:0x82F0])
    oldmsg = unpack(base.files[msgid]); newmsg = unpack(final.files[msgid])
    require(len(oldmsg) == len(newmsg), 'Message member count drift')
    cursors = [len(m.data) for m in oldmsg]
    for a,b in zip(oldmsg,newmsg):
        require(b.data[4:len(a.data)] == a.data[4:], 'Old message offsets/bytes changed')
        require(int.from_bytes(b.data[:4],'big') == len(b.data)-4, 'Member size header incorrect')
    expected_maps, readback = [], []
    extcs = {v:k for k,v in mapping.items()}
    for row in sorted(rows,key=lambda r:(refs[r['id']]['member'],refs[r['id']]['offset'])):
        ref = refs[row['id']]; member = ref['member']; start = cursors[member]
        require(start < len(newmsg[member].data), 'Missing relocated record')
        stop = newmsg[member].data.find(b'\xf8',start)
        require(stop >= start, 'No relocated terminator')
        body = newmsg[member].data[start:stop+1]
        tokens = tokenize(body)
        visible = decode(body,source_charset(base.arm9),extcs)
        require(unicodedata.normalize('NFKC',visible) == unicodedata.normalize('NFKC',row['translation']), 'Final text readback mismatch '+row['id'])
        require(controls(body) == controls(bytes.fromhex(ref['raw_hex'])), 'Control/newline/parameter drift '+row['id'])
        require(ref['member'] < 65536 and ref['offset'] < 65536, 'Source key overflow')
        expected_maps.append((member<<16|ref['offset'],start)); cursors[member] = stop+1
        readback.append({'id':row['id'],'relocated_offset':start,'bytes':len(body),'text_and_controls_match':True})
    require(cursors == [len(m.data) for m in newmsg], 'Unreferenced trailing message data')
    check_map(fonts[3][mapstart:],expected_maps)
    # Exact machine-code reproduction ties the independently audited final data
    # to the implementation exercised by ARM tests; not independent semantics.
    fresharm = bytearray(base.arm9)
    expected_code, emitted = apply_engine(fresharm,base.arm9[0x9B478:0x9B568],max(mapping.values())+1,expected_maps,pages*32768)
    require(bytes(fresharm) == final.arm9 and expected_code == fonts[3][0x8000:0x9000], 'Final engine differs from tested emitter')
    runtime = None
    if ramdir:
        run = Path(ramdir)
        rr = json.loads((run/'report.json').read_text('utf8'))
        pe = json.loads((run/'process_exit.json').read_text('utf8'))
        require(rr['rom_sha256'] == sha(raw) and pe['rom_sha256'] == sha(raw), 'Cross-SHA runtime proof')
        require(pe['returncode'] == 0 and not rr['runtime_ram_writes'], 'Runtime not natural successful exit')
        runtime = check_ram((run/'mainram.bin').read_bytes(),fonts)
        runtime['same_sha_natural_run'] = True
        runtime['run_directory'] = str(run)
    result = {'scope':'NDS ADQJ; final-byte static audit + optional same-SHA RAM',
              'candidate_sha256':sha(raw),'input_sha256':SOURCE_HASH,'base_sha256':BASE_HASH,
              'translated_body_records':len(readback),'all_selected_source_references_match_original_ROM':True,'glyphs_checked':glyphs,'atlas_pages':pages,
              'original_message_bytes_and_offsets_preserved':True,'untargeted_NitroFS_files':untouched_files,
              'ARM9_and_BSS_cpu_address_limits_unchanged':True,'only_allowed_ARM9_writes':True,
              'sorted_exact_relocation_map':True,'atlas_pixels_including_unused_holes_exact':True,
              'copied_dispatcher_relocation_analysis':dispatcher,'tested_emitter_byte_identity':True,
              'expanded_font_heap_bytes':len(fonts[3])-len(oldfonts[3]),'max_message_member_bytes':max(len(m.data) for m in newmsg),
              'loaded_RAM':runtime,'small_speaker_CJK':False,'full_game_playthrough':False,
              'hardware_cache_verification':False,'complete_game_translation':False,
              'readback':readback,'status':'passed_with_explicit_coverage_limits'}
    if reportpath:
        rp = Path(reportpath)
        require(not rp.exists(), 'Do not overwrite historical audit')
        rp.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    return result


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('rom',type=Path); ap.add_argument('translations',type=Path)
    ap.add_argument('--report',type=Path,required=True); ap.add_argument('--ramdir',type=Path)
    args = ap.parse_args()
    result = audit(args.rom,args.translations,args.report,args.ramdir)
    print(json.dumps({k:v for k,v in result.items() if k not in ('readback','copied_dispatcher_relocation_analysis')},ensure_ascii=False,indent=2))
