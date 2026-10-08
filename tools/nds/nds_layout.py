"""Native main-dialogue width diagnostics, not an automatic reflow engine.
FD uses the tested mode-2/3 14px advance (mode 3 observed in cold dialogue). Old glyphs use the actual routine's
width-table value + 1. Dynamic substitutions are reported under explicit
assumptions, not mistaken for known player-name limits or runtime proof.
"""
import json
from pathlib import Path
from nds_extended_codec import tokenize, encode
from text_codec import source_charset, WIDTH_TABLE
from nds_audit_extended import inferred_charset
from ndspy.rom import NintendoDSRom


def line_layout(body, arm, dynamic_width=84):
    width = 0
    text_token_count = 0
    substitutions = []
    speaker = False
    lines = []
    def finish():
        nonlocal width, text_token_count, substitutions
        if text_token_count or substitutions:
            lines.append({'width':width,'glyphs':text_token_count,'substitutions':substitutions})
        width = 0; text_token_count = 0; substitutions = []
    for t in tokenize(body):
        if t['kind'] == 'control':
            if t['value'] == 0xFA:
                speaker = not speaker
            elif not speaker and t['value'] in (0xF6,0xF7,0xF8):
                finish()
            elif not speaker and t['value'] == 0xF0 and bytes.fromhex(t['hex'])[1] < 4:
                width += dynamic_width
                substitutions.append(t['hex'])
        elif not speaker:
            if t['extended']:
                width += 14
            else:
                prefix = bytes.fromhex(t['hex'])[0]
                index = t['value'] + (0x100 if prefix == 0xFE else 0)
                width += arm[WIDTH_TABLE+index]+1
            text_token_count += 1
    return lines


def check(rows, arm, limit=224, dynamic_width=84):
    cs = source_charset(arm)
    mapping = inferred_charset(rows,cs)
    reports = []
    for row in rows:
        layout = line_layout(encode(row['translation'],cs,mapping),arm,dynamic_width)
        reports.append({'id':row['id'],'lines':layout,
                        'max_width':max((l['width'] for l in layout),default=0),
                        'exceeds_limit':any(l['width']>limit for l in layout)})
    return {'consumer':'mode-2/3 14px main dialogue assumptions; excludes preserved small speaker and other consumers',
            'limit_px':limit,'dynamic_substitution_assumption_px':dynamic_width,
            'assumption_is_not_a_known_name_input_limit':True,
            'overflow_ids':[r['id'] for r in reports if r['exceeds_limit']],
            'records':reports,'runtime_layout_proof':False}


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('translations',type=Path); ap.add_argument('--rom',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True); ap.add_argument('--dynamic-width',type=int,default=84)
    args = ap.parse_args()
    report = check(json.loads(args.translations.read_text('utf8')),NintendoDSRom(args.rom.read_bytes()).arm9,dynamic_width=args.dynamic_width)
    if args.out.exists(): raise ValueError('Do not overwrite past diagnostics')
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='records'},ensure_ascii=False,indent=2))
    for r in report['records']:
        if r['exceeds_limit']:print(r['id'],r['lines'])
