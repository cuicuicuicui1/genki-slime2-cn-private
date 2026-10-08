"""Source-locked custom dialogue decoder, not a generic Shift-JIS scan."""
from pathlib import Path
import struct,json,hashlib
from rs_format import unpack,FormatError
ROOT=Path(__file__).resolve().parent.parent
SJIS_TABLE=0x137BC8
WIDTH_TABLE=0x1379A8

def source_charset(arm):
    values=struct.unpack_from('<544H',arm,SJIS_TABLE)
    return {i:v.to_bytes(2,'big').decode('cp932') for i,v in enumerate(values)}

def tokenize(data):
    result=[];i=0
    while i<len(data):
        start=i;b=data[i];i+=1
        if b in [0xFF,0xFE]:
            if i>=len(data):raise FormatError('Truncated glyph')
            p=data[i];i+=1;kind='glyph';value=p+(0xF0 if b==0xFF else 0x1E0)
        elif b<0xF0:kind='glyph';value=b
        elif b==0xF0:
            if i>=len(data):raise FormatError('Truncated substitution')
            t=data[i];i+=1
            if t in [0,1,2,3]:
                if i>=len(data):raise FormatError('Truncated indexed substitution')
                i+=1
            if t>4:raise FormatError('Unknown substitution type')
            kind='control';value=b
        elif b in [0xF1,0xF2,0xF3,0xF4]:
            if i>=len(data):raise FormatError('Truncated parameter')
            i+=1;kind='control';value=b
        elif b in [0xF5,0xF6,0xF7,0xF8,0xF9,0xFA]:kind='control';value=b
        else:raise FormatError(f'Unknown control {b:02X}')
        result.append({'start':start,'end':i,'kind':kind,'value':value,'hex':data[start:i].hex()})
    return result

def decode(data,charset):
    tags={0xF5:'<WAIT>',0xF6:'<PAGE>',0xF7:'\n',0xF8:'<END>',0xF9:'<BODY>',0xFA:'<SPEAKER>'}
    text=[]
    for t in tokenize(data):
        if t['kind']=='glyph':text.append(charset.get(t['value'],f"<G{t['value']:03X}>"))
        elif t['value'] in tags:text.append(tags[t['value']])
        else:text.append('<'+t['hex'].upper()+'>')
    return ''.join(text)

def extract():
    arm=(ROOT/'work/extracted/arm9.bin').read_bytes();charset=source_charset(arm);data=(ROOT/'work/extracted/nitrofs/msgdata.bin').read_bytes();rows=[]
    for m in unpack(data):
        if int.from_bytes(m.data[:4],'big')!=m.size-4:raise FormatError('Unexpected message payload size')
        cursor=4;record=0
        while cursor<m.size:
            end=m.data.find(b'\xF8',cursor)
            if end<0:raise FormatError('Unterminated message')
            body=m.data[cursor:end+1];tokens=tokenize(body)
            if not tokens or tokens[-1]['value']!=0xF8:raise FormatError('Raw end-byte inside parameter; cannot infer boundaries')
            rows.append({'id':f'{m.index:02d}:{cursor:04X}','member':m.index,'record':record,'offset':cursor,'size':len(body),'raw_sha256':hashlib.sha256(body).hexdigest(),'raw_hex':body.hex(),'text':decode(body,charset),'tokens':tokens})
            cursor=end+1;record+=1
    (ROOT/'work/messages_jp.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    (ROOT/'work/messages_jp.txt').write_text('\n\n'.join(f"[{r['id']}] {r['text']}" for r in rows),encoding='utf8')
    (ROOT/'reports/text_extraction.json').write_text(json.dumps({'source_charset_offset':SJIS_TABLE,'records':len(rows),'members':73,'roundtrip_raw':True,'scope':'msgdata.bin only; ARM9 embedded messages and raster/UI captions separate'},indent=2),encoding='utf8')
    print('RECORDS',len(rows));print('\n\n'.join(f"[{r['id']}] {r['text']}" for r in rows[:28]))
if __name__=='__main__':extract()