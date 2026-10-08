"""Strict Rocket Slime packed-file reader; originals are never rewritten.
Archive layout checked against 0Unique FS.zig, pinned e8a8065.
LZ10 is treated as standard bytes only; unknown variants fail closed.
"""
from dataclasses import dataclass
import struct

class FormatError(ValueError): pass
@dataclass(frozen=True)
class Member:
    index: int
    offset: int
    size: int
    data: bytes

def unpack(data: bytes) -> list[Member]:
    if len(data) < 4: raise FormatError('Truncated archive')
    count=struct.unpack_from('<I',data)[0]
    if not 1 <= count <= 8192: raise FormatError('Invalid member count')
    base=4+8*count
    if base>len(data): raise FormatError('Truncated directory')
    out=[];last=0
    for i in range(count):
        off,size=struct.unpack_from('<II',data,4+8*i)
        if off<last or base+off+size>len(data):raise FormatError('Overlapping or out-of-bounds member')
        if i==0 and off!=0:raise FormatError('Nonzero first member offset')
        if off-last>3:raise FormatError('Undeclared data gap')
        out.append(Member(i,base+off,size,data[base+off:base+off+size]));last=off+size
    if len(data)-(base+last)>3:raise FormatError('Undeclared archive tail')
    return out

def replace_bounded(data: bytes, replacements: dict[int,bytes]) -> bytes:
    members=unpack(data);out=bytearray(data)
    if any(type(k) is not int or not 0<=k<len(members) for k in replacements):raise FormatError('Unknown member')
    for i,body in replacements.items():
        m=members[i]
        if len(body)!=m.size:raise FormatError('Replacement must preserve allocation and member size')
        out[m.offset:m.offset+m.size]=body
    return bytes(out)

def lz10_decode(src: bytes, limit: int=16*1024*1024) -> bytes:
    if len(src)<4 or src[0]!=0x10:raise FormatError('Not standard LZ10')
    size=int.from_bytes(src[1:4],'little')
    if not 0<size<=limit:raise FormatError('Invalid expanded size')
    pos=4;out=bytearray()
    def take():
        nonlocal pos
        if pos>=len(src):raise FormatError('Truncated LZ10 stream')
        v=src[pos];pos+=1;return v
    while len(out)<size:
        flags=take()
        for bit in range(7,-1,-1):
            if len(out)>=size:break
            if flags & (1<<bit):
                a=take();b=take();length=(a>>4)+3;distance=((a&15)<<8|b)+1
                if distance>len(out) or len(out)+length>size:raise FormatError('Invalid LZ10 backreference')
                for _ in range(length):out.append(out[-distance])
            else:out.append(take())
    return bytes(out)