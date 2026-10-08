"""Passive ARM9 execution observations over the existing no-window runner.
Uses py-desmume's documented register_exec API. No game RAM/register/VRAM
writes, injected messages, save edits, cheats, GUI or global emulator settings.
Hook callbacks are data observations, not proof of an ABI before source review.
"""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess, sys

FIELDS = {f'r{i}' for i in range(16)} | {'cpsr'}
RAM_START, RAM_END = 0x02000000, 0x02400000
DT_START, DT_END = 0x027C0000, 0x027C4000
# Only the font texture interval demonstrated by this source's native
# allocator in cold177. No generic VRAM/BG bank or MMIO reads are enabled.
FONT_VRAM_START, FONT_VRAM_END = 0x06018000, 0x06020000


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalized_sites(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 16:
        raise ValueError('1..16 passive sites required')
    sites, names, addresses = [], set(), set()
    for row in raw:
        if not isinstance(row, dict) or set(row) - {'name', 'address', 'registers', 'pointer_registers', 'bytes', 'limit'}:
            raise ValueError('Unknown passive site field')
        name = row.get('name')
        if not isinstance(name, str) or not name or len(name) > 80 or name in names:
            raise ValueError('Unique bounded site name required')
        a = row.get('address')
        if isinstance(a, bool) or not isinstance(a, (int, str)):
            raise ValueError('Numeric execution address required')
        try:
            address = int(a, 0) if isinstance(a, str) else a
        except ValueError as ex:
            raise ValueError('Invalid execution address') from ex
        if address % 2 or not RAM_START <= address < RAM_END or address in addresses:
            raise ValueError('Unique aligned ARM9 main-RAM site required')
        registers = row.get('registers', ['r0', 'r1', 'r2', 'r3', 'r13', 'r14', 'r15'])
        pointers = row.get('pointer_registers', [])
        if not isinstance(registers, list) or not isinstance(pointers, list):
            raise ValueError('Register lists required')
        if len(registers) != len(set(registers)) or any(not isinstance(x, str) or x not in FIELDS for x in registers):
            raise ValueError('Only read-only named ARM9 register fields allowed')
        if len(pointers) != len(set(pointers)) or any(x not in registers or x == 'cpsr' for x in pointers):
            raise ValueError('Pointer fields must be observed registers')
        n, limit = row.get('bytes', 64), row.get('limit', 256)
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 256:
            raise ValueError('RAM preview limit 0..256 bytes')
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 2048:
            raise ValueError('Stored hit limit 1..2048 per site')
        sites.append(dict(name=name, address=address, registers=registers,
                          pointer_registers=pointers, bytes=n, limit=limit))
        names.add(name); addresses.add(address)
    return sites


def ram_preview(reader, address, n):
    if FONT_VRAM_START <= address < FONT_VRAM_END and n != 0:
        size=min(n,FONT_VRAM_END-address)
        return {'address':f'0x{address:08x}','bytes':size,
                'hex':bytes(reader[address:address+size]).hex(),
                'memory_region':'source-specific demonstrated font texture VRAM;read-only'}
    # Source ARM9 auto-load/SDK stack use the mapped16KiB DTCM window here.
    # This is bounded read-only evidence for on-stack unpacked glyph bytes.
    if DT_START <= address < DT_END and n != 0:
        size=min(n,DT_END-address)
        return {'address':f'0x{address:08x}','bytes':size,
                'hex':bytes(reader[address:address+size]).hex(),
                'memory_region':'source-specific mapped ARM9 DTCM;not 4MiB mainRAM'}
    if not RAM_START <= address < RAM_END or n == 0:
        return None
    size = min(n, RAM_END - address)
    return {'address':f'0x{address:08x}', 'bytes':size,
            'hex':bytes(reader[address:address+size]).hex()}


def install(emu, sites, observations):
    memory = emu.memory
    for site in sites:
        state = observations[site['name']]
        def callback(address, size, site=site, state=state):
            # Never throw a Python exception through a native C callback.
            state['hits'] += 1
            if len(state['samples']) >= site['limit']:
                state['truncated'] = True
                return
            try:
                registers = {name:int(getattr(memory.register_arm9, name)) & 0xffffffff
                             for name in site['registers']}
                preview = {}
                for name in site['pointer_registers']:
                    sample = ram_preview(memory.unsigned, registers[name], site['bytes'])
                    if sample is not None:preview[name] = sample
                state['samples'].append({'ordinal':state['hits'], 'callback_address':f'0x{address:08x}',
                    'callback_size':size, 'registers':{k:f'0x{v:08x}' for k,v in registers.items()},
                    'main_RAM_previews':preview})
            except Exception as ex:
                if len(state['errors']) < 8:state['errors'].append(repr(ex))
        # Leave size=2 as prescribed by this installed SDK. The SDK keeps the
        # CFUNCTYPE instance alive in memory._registered_cbs.
        memory.register_exec(site['address'], callback)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('rom',type=Path);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sites',type=Path,required=True)
    ap.add_argument('--resume',type=Path);ap.add_argument('--native',action='store_true')
    args=ap.parse_args();out=args.out.resolve();rom=args.rom.resolve()
    sites=normalized_sites(json.loads(args.sites.read_text('utf-8-sig')))
    if not args.native:
        if out.exists() and any(out.iterdir()):raise ValueError('Fresh empty output required')
        (out/'runtime').mkdir(parents=True);base=Path(sys.base_prefix)
        for name in ['python.exe','python312.dll','vcruntime140.dll','vcruntime140_1.dll']:
            if (base/name).exists():shutil.copyfile(base/name,out/'runtime'/name)
        (out/'runtime/python312._pth').write_text('\n'.join([str(base/'Lib'),str(base/'DLLs'),str(base/'Lib/site-packages'),str(Path(__file__).resolve().parent),'import site'])+'\n',encoding='utf8')
        cmd=[str(out/'runtime/python.exe'),'-u','-X','utf8',str(Path(__file__).resolve()),str(rom),'--out',str(out),'--plan',str(args.plan.resolve()),'--sites',str(args.sites.resolve()),'--native']
        if args.resume:cmd+=['--resume',str(args.resume.resolve())]
        env=dict(os.environ);env['SDL_AUDIODRIVER']='dummy'
        proc=subprocess.run(cmd,cwd=out,env=env,capture_output=True,text=True,encoding='utf8')
        (out/'stdout.log').write_text(proc.stdout,encoding='utf8');(out/'stderr.log').write_text(proc.stderr,encoding='utf8')
        info={'returncode':proc.returncode,'unsigned_hex':f'{proc.returncode & 0xffffffff:08X}',
              'rom_sha256':sha(rom),'resume_used':bool(args.resume),'runtime_report_exists':(out/'report.json').exists(),
              'trace_exists':(out/'passive_trace.json').exists(),'sdl_audio_driver':'dummy'}
        (out/'process_exit.json').write_text(json.dumps(info,indent=2)+'\n',encoding='utf8')
        print(proc.stdout[-3000:]);print(proc.stderr);print('Native passive process exit',info)
        sys.exit(proc.returncode)
    # Reuse the established native runner and ordinary input actions unchanged.
    import desmume.emulator as sdk
    import run_headless
    original_factory=sdk.DeSmuME
    initial_source_sha=sha(rom)
    diagnostic={'read_only_snapshots':[], 'positive_exec_counts':{}}
    observations={s['name']:{'address':f"0x{s['address']:08x}", 'hits':0,
                   'truncated':False,'samples':[],'errors':[]} for s in sites}
    def attach(emu,label):
        # Savestate loading may reset debugging state; observe again after it.
        install(emu,sites,observations)
        pc=int(emu.memory.get_next_instruction()) & 0xffffffff
        reg_pc=int(emu.memory.register_arm9.r15) & 0xffffffff
        diagnostic['read_only_snapshots'].append({'phase':label,
            'next_instruction_api':f'0x{pc:08x}', 'ARM9_r15':f'0x{reg_pc:08x}'})
        if RAM_START <= pc < RAM_END and pc % 2 == 0 and pc not in {s['address'] for s in sites}:
            key=f'0x{pc:08x}'
            diagnostic['positive_exec_counts'].setdefault(key,0)
            def positive(address,size,key=key):
                diagnostic['positive_exec_counts'][key]+=1
            emu.memory.register_exec(pc,positive)
    def factory():
        emu=original_factory();original_open=emu.open;original_load=emu.savestate.load_file
        def open_observed(path):
            result=original_open(path)
            attach(emu,'after_open')
            return result
        def load_observed(path):
            result=original_load(path)
            attach(emu,'after_same_SHA_savestate_load')
            return result
        emu.open=open_observed
        emu.savestate.load_file=load_observed
        return emu
    original_argv=sys.argv[:]
    sdk.DeSmuME=factory
    sys.argv=[str(Path(run_headless.__file__)),str(rom),'--out',str(out),'--plan',str(args.plan.resolve()),'--native']
    if args.resume:sys.argv+=['--resume',str(args.resume.resolve())]
    try:
        run_headless.main()
    finally:
        sdk.DeSmuME=original_factory;sys.argv=original_argv
        result={'kind':'passive ARM9 execution callback observations', 'rom_sha256':initial_source_sha,
                'sites_sha256':sha(args.sites), 'source_unchanged':sha(rom)==initial_source_sha,
                'runtime_game_RAM_writes':False,'runtime_game_register_writes':False,
                'ABI_phase_assumed':False,'frame_attribution':False,'site_observations':observations,
                'execution_callback_diagnostic':diagnostic,
                'note':'Samples are observed at SDK callbacks; semantics and consumer eligibility need independent source/scene review. Zero hits are not a pass.'}
        (out/'passive_trace.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

if __name__=='__main__':main()
