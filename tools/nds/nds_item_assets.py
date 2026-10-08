"""Bounded packed-OAM inspection and data-only name-tile replacement.

JP source and natural inventory observations, not a generic DS sprite editor.
The 128-byte OBJ boundary used by this consumer means tile_num * 4 tiles.
No ROM writes, OAM changes, allocator patches or font-slot reuse here.
"""
from dataclasses import dataclass
import struct
from PIL import Image
from rs_format import FormatError
from font_renderer import render_glyph

SIZES = (((8,8),(16,16),(32,32),(64,64)),
         ((16,8),(32,8),(32,16),(64,32)),
         ((8,16),(8,32),(16,32),(32,64)))


@dataclass(frozen=True)
class Obj:
    x: int
    y: int
    w: int
    h: int
    first_tile: int
    hflip: bool
    vflip: bool
    palette: int

    @property
    def tiles(self):
        return frozenset(range(self.first_tile, self.first_tile+self.w*self.h//64))


def parse_frames(blob, tile_count):
    if len(blob)<6 or not isinstance(tile_count,int) or tile_count<1:
        raise FormatError('Truncated OAM or empty tile set')
    end,n=struct.unpack_from('<HH',blob)
    if not 1<=n<=128 or not 4+2*n<=end<=len(blob):
        raise FormatError('Bad packed OAM header')
    starts=[4+x for x in struct.unpack_from('<'+'H'*n,blob,4)]
    if starts[0]!=4+2*n or starts!=sorted(set(starts)):
        raise FormatError('Noncanonical packed frame offsets')
    frames=[]
    for i,start in enumerate(starts):
        limit=starts[i+1] if i+1<n else end
        if start+2>limit:raise FormatError('Frame count crosses boundary')
        count=struct.unpack_from('<H',blob,start)[0]
        if start+2+count*6!=limit:raise FormatError('OAM frame length mismatch')
        objs=[]
        for j in range(count):
            a,b,c=struct.unpack_from('<HHH',blob,start+2+j*6)
            if a&0x2300 or a>>14==3:
                raise FormatError('Affine/disabled/8bpp/invalid-shape object unsupported')
            w,h=SIZES[a>>14][b>>14]
            x=b&511;y=a&255
            x=x-512 if x>=256 else x;y=y-256 if y>=128 else y
            obj=Obj(x,y,w,h,(c&1023)*4,bool(b&4096),bool(b&8192),c>>12)
            if max(obj.tiles)>=tile_count:raise FormatError('OBJ tile outside resource')
            objs.append(obj)
        frames.append(tuple(objs))
    return tuple(frames)


def bounds(frame):
    if not frame:raise FormatError('Empty frame has no name rectangle')
    return (min(o.x for o in frame),min(o.y for o in frame),
            max(o.x+o.w for o in frame),max(o.y+o.h for o in frame))


def source_pixels(obj):
    """Yield canvas x,y and stored nibble address, handling source flips."""
    for yy in range(obj.h):
        for xx in range(obj.w):
            tile=obj.first_tile+xx//8+yy//8*(obj.w//8)
            byte=tile*32+(yy%8)*4+xx%8//2
            yield (obj.x+(obj.w-1-xx if obj.hflip else xx),
                   obj.y+(obj.h-1-yy if obj.vflip else yy),byte,4*(xx%2))


def render_frame(tiles, frame):
    if len(tiles)%32:raise FormatError('Partial tile resource')
    x0,y0,x1,y1=bounds(frame);out=Image.new('L',(x1-x0,y1-y0),0)
    for obj in reversed(frame):
        for x,y,off,shift in source_pixels(obj):
            if off>=len(tiles):raise FormatError('OBJ tile read outside resource')
            value=tiles[off]>>shift&15
            if value:out.putpixel((x-x0,y-y0),value)
    return out


def replace_name_frame(tiles, oam, pixels, frame_index=0):
    """Return same-size graphics only when the name owns every edited tile.

    Shared icon tiles, repeated aliases with inconsistent pixels, overlapping
    objects, unsupported palette banks and uncovered visible pixels fail closed.
    """
    if len(tiles)%32:raise FormatError('Partial tile resource')
    frames=parse_frames(oam,len(tiles)//32)
    if not isinstance(frame_index,int) or not 0<=frame_index<len(frames):
        raise FormatError('Unknown frame')
    frame=frames[frame_index];x0,y0,x1,y1=bounds(frame)
    if pixels.mode!='L' or pixels.size!=(x1-x0,y1-y0) or max(pixels.tobytes())>15:
        raise FormatError('Expected exact native-sized palette-index image')
    owned=set().union(*(o.tiles for o in frame))
    other=set().union(*(o.tiles for i,f in enumerate(frames) if i!=frame_index for o in f))
    if owned&other:raise FormatError('Name shares tiles with non-name frame')
    if any(o.palette!=0 for o in frame):raise FormatError('Name palette not proved')
    assignments={};seen=set()
    for obj in frame:
        for x,y,off,shift in source_pixels(obj):
            xy=x-x0,y-y0
            if xy in seen:raise FormatError('Overlapping name objects unsupported')
            seen.add(xy);key=off,shift;value=pixels.getpixel(xy)
            if key in assignments and assignments[key]!=value:
                raise FormatError('Aliased tile cannot represent both positions')
            assignments[key]=value
    for y in range(pixels.height):
        for x in range(pixels.width):
            if (x,y) not in seen and pixels.getpixel((x,y))!=0:
                raise FormatError('Text spills outside drawable name objects')
    out=bytearray(tiles)
    for (off,shift),value in assignments.items():out[off]=(out[off]&~(15<<shift))|(value<<shift)
    if render_frame(out,frame).tobytes()!=pixels.tobytes():
        raise FormatError('Final name bitmap did not roundtrip exactly')
    if any(tiles[i*32:(i+1)*32]!=out[i*32:(i+1)*32] for i in range(len(tiles)//32) if i not in owned):
        raise FormatError('Non-name tile drift')
    return bytes(out),dict(name_tiles=sorted(owned),non_name_tiles=sorted(other),
                           frame_rectangle=[x0,y0,x1,y1],same_size=True,OAM_unchanged=True)


def native_name(text, width, height):
    """Prefer14px design, then13/12px native designs; never resample/truncate."""
    if not text or not 1<=width<=256 or not 1<=height<=64:
        raise FormatError('Invalid name/rectangle')
    for advance in (14,13,12):
        if len(text)*advance>width or height<16:continue
        images=[];info=[]
        try:
            for ch in text:
                pix,meta=render_glyph(ch,'crisp14',advance)
                images.append(pix);info.append(meta)
        except FormatError:continue
        out=Image.new('L',(width,height),1);left=(width-len(text)*advance)//2;top=(height-16)//2
        for i,pix in enumerate(images):
            for y in range(16):
                for x in range(16):
                    if pix[y*16+x]==4:
                        xx=left+i*advance+x
                        if not 0<=xx<width:raise FormatError('Unclipped native name does not fit')
                        out.putpixel((xx,top+y),4)
        return out,dict(text=text,advance=advance,glyphs=info,no_shadow=True,no_resampling=True)
    raise FormatError('No native-size name layout fits; translate more concisely')


def replace_name_text(tiles, oam, text):
    frames=parse_frames(oam,len(tiles)//32);original=render_frame(tiles,frames[0]);bb=original.getbbox()
    if bb is None:raise FormatError('Empty name alpha region')
    opaque=original.crop(bb)
    if 0 in opaque.tobytes():raise FormatError('Name alpha region is not a solid rectangle')
    face,layout=native_name(text,opaque.width,opaque.height)
    canvas=Image.new('L',original.size,0);canvas.paste(face,(bb[0],bb[1]))
    if [v==0 for v in canvas.tobytes()]!=[v==0 for v in original.tobytes()]:
        raise FormatError('Name transparency silhouette drift')
    patched,proof=replace_name_frame(tiles,oam,canvas)
    return patched,dict(proof,layout=layout,original_alpha_rectangle=list(bb),alpha_preserved=True)
