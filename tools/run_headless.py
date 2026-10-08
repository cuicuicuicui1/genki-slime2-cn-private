"""Private, no-window DeSmuME runner, py-desmume 0.0.9 / CPython 3.12.
No SDL window, cheats or runtime writes. Cross-ROM snapshots prohibited.
"""
from pathlib import Path
import argparse,hashlib,json,subprocess,shutil,sys,time,os

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def elasto_input(emu,advance,keys,action):
 """Ordinary staged button input: release A before releasing direction.

 No game RAM/registers are touched. Direction stays held during the release
 phase rather than dropping A and the direction in the same input update.
 """
 direction=action.get('direction')
 if direction not in ('UP','DOWN','LEFT','RIGHT'):raise ValueError('Invalid elasto direction')
 charge=action.get('charge',45);travel=action.get('travel',20);gap=action.get('gap',80)
 for name,n,cap in [('charge',charge,240),('travel',travel,240),('gap',gap,3600)]:
  if type(n) is not int or not 1<=n<=cap:raise ValueError('Invalid elasto '+name)
 a,d=keys['A'],keys[direction];mask=a|d
 emu.input.keypad_add_key(mask)
 try:
  advance(charge)
  emu.input.keypad_rm_key(a)
  advance(travel)
 finally:emu.input.keypad_rm_key(mask)
 advance(gap)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('rom',type=Path);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--resume',type=Path);ap.add_argument('--native',action='store_true');args=ap.parse_args()
 out=args.out.resolve();rom=args.rom.resolve()
 if not args.native:
  if out.exists() and any(out.iterdir()):raise ValueError('Fresh empty output required')
  (out/'runtime').mkdir(parents=True);base=Path(sys.base_prefix)
  for name in ['python.exe','python312.dll','vcruntime140.dll','vcruntime140_1.dll']:
   if (base/name).exists():shutil.copyfile(base/name,out/'runtime'/name)
  (out/'runtime/python312._pth').write_text('\n'.join([str(base/'Lib'),str(base/'DLLs'),str(base/'Lib/site-packages'),str(Path(__file__).resolve().parent),'import site'])+'\n',encoding='utf8')
  cmd=[str(out/'runtime/python.exe'),'-u','-X','utf8',str(Path(__file__).resolve()),str(rom),'--out',str(out),'--plan',str(args.plan.resolve()),'--native']
  if args.resume:cmd+=['--resume',str(args.resume.resolve())]
  env=dict(os.environ);env['SDL_AUDIODRIVER']='dummy'
  proc=subprocess.run(cmd,cwd=out,env=env,capture_output=True,text=True,encoding='utf8');(out/'stdout.log').write_text(proc.stdout,encoding='utf8');(out/'stderr.log').write_text(proc.stderr,encoding='utf8')
  exit_info={'returncode':proc.returncode,'unsigned_hex':f'{proc.returncode&0xffffffff:08X}','rom_sha256':digest(rom),'resume_used':bool(args.resume),'sdl_audio_driver':'dummy','runtime_report_exists':(out/'report.json').exists()}
  (out/'process_exit.json').write_text(json.dumps(exit_info,indent=2),encoding='utf8');print(proc.stdout[-5000:]);print(proc.stderr);print('Native process exit',exit_info);sys.exit(proc.returncode)
 from desmume.emulator import DeSmuME
 from PIL import Image
 before=digest(rom);shutil.copyfile(rom,out/'game.nds');print('NATIVE_STAGE init_begin',flush=True);emu=DeSmuME();print('NATIVE_STAGE init_ok',flush=True);emu.open(str(out/'game.nds'));print('NATIVE_STAGE rom_open_ok',flush=True);frame=0;shots=[];start=time.monotonic();(out/'shots').mkdir()
 if args.resume:
  old=json.loads((args.resume/'report.json').read_text('utf8'))
  if old['rom_sha256']!=before:raise ValueError('Cross-ROM savestate reuse prohibited')
  if (args.resume/'runtime/game.dsv').exists():shutil.copyfile(args.resume/'runtime/game.dsv',out/'runtime/game.dsv')
  emu.savestate.load_file(str(args.resume/'checkpoint.dst'));frame=old['last_frame']
 keys={k:1<<i for i,k in enumerate(['A','B','SELECT','START','RIGHT','LEFT','UP','DOWN','R','L','X','Y'])}
 def advance(n):
  nonlocal frame
  for _ in range(n):emu.cycle(with_joystick=False);frame+=1
 try:
  for a in json.loads(args.plan.read_text('utf8')):
   if a['op']=='frames':advance(a['n'])
   elif a['op']=='key':
    mask=keys[a['key']];emu.input.keypad_add_key(mask);advance(a.get('hold',2));emu.input.keypad_rm_key(mask);advance(a.get('gap',30))
   elif a['op']=='keys':
    mask=0
    for key in a['keys']:mask|=keys[key]
    emu.input.keypad_add_key(mask)
    try:advance(a.get('hold',2))
    finally:emu.input.keypad_rm_key(mask)
    advance(a.get('gap',30))
   elif a['op']=='elasto':elasto_input(emu,advance,keys,a)
   elif a['op']=='touch':
    emu.input.touch_set_pos(a['x'],a['y']);advance(a.get('hold',8));emu.input.touch_release();advance(a.get('gap',30))
   elif a['op']=='shot':
    path=out/'shots'/(a['name']+'.png');im=emu.screenshot();im.save(path);shots.append({'name':a['name'],'frame':frame,'path':str(path),'pixels_sha256':hashlib.sha256(im.tobytes()).hexdigest()})
   elif a['op']=='ram':
    raw=bytes(emu.memory.unsigned[0x02000000:0x02400000]);(out/'mainram.bin').write_bytes(raw)
   else:raise ValueError('Unknown action')
  emu.savestate.save_file(str(out/'checkpoint.dst'))
  report={'rom_sha256':before,'source':str(rom),'headless':True,'audio_validation':False,'sdl_audio_driver':os.environ.get('SDL_AUDIODRIVER'),'core':'DeSmuME via py-desmume 0.0.9','last_frame':frame,'shots':shots,'elapsed_seconds':round(time.monotonic()-start,3),'full_playthrough':False,'runtime_ram_writes':False,'source_unchanged':digest(rom)==before,'staged_elasto_input_actions':sum(a['op']=='elasto' for a in json.loads(args.plan.read_text('utf8')))}
  (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False,indent=2))
 finally:emu.close();emu.destroy()
if __name__=='__main__':main()
