"""Source-specific NDS pause graphics: same-size, data-only native-grid edit.

Only pause_data member0 tiles32..185 used by the two ordinary field pause
frames. Indexed-map table is proved here per this file, not a universal format.
Other UI/battle pause, maps, palettes, fonts, executable code and save untouched.
"""
from dataclasses import dataclass
from functools import lru_cache
import hashlib, struct
from PIL import Image
from rs_format import FormatError, unpack
from font_renderer import render_glyph, profile_manifest

SOURCE_PACK_SHA='1100b307254e0d4e765a818f1fc8432607a55b99e79faa7eff6ee7208a0aba5b'
SOURCE_MAP_SHA='a8b74158efe7e3538a873ae581c97f1dd8615c976129e8d1ef13e2fad290ec5c'
PACK_SIZE=15680
TILE_BASE=704
BLANK=0x2000
# File-local tile ranges. All are complete 16px-high horizontal strips.
STRIPS=((32,9,'title',0),(50,9,'title',1),(68,15,'look_upper',None),
        (98,11,'buttons',0),(120,11,'buttons',1),
        (142,11,'switch_screen',0),(164,11,'switch_screen',1))
LABELS={'title':'\u6682\u505c','look_upper':'\u8bf7\u770b\u4e0a\u5c4f\uff01',
        'buttons':'\u6309L\u3001R\u952e','switch_screen':'\u5207\u6362\u753b\u9762'}
JP_LABELS={'title':'PAUSE','look_upper':'\u3046\u3048\u304c\u3081\u3093 \u3061\u3085\u3046\u3082\u304f!!',
           'buttons':'L\u30dc\u30bf\u30f3\u3068R\u30dc\u30bf\u30f3\u3067',
           'switch_screen':'\u304c\u3081\u3093\u3078\u3093\u3053\u3046'}
# Observed as a single-valued mapping for all4097 nontransparent source pixels
# in ordinary field frame0 at (40,248) in D941 natural run221.
OBSERVED_COLORS={0:(0,0,0),1:(248,248,248),2:(208,208,208),3:(120,120,176),
 4:(48,48,96),8:(248,200,208),9:(248,152,96),10:(248,24,56),
 14:(136,240,248),15:(0,104,200)}

@dataclass(frozen=True)
class MapFrame:
 width:int
 height:int
 entries:tuple


def indexed_maps(blob):
 if len(blob)<6:raise FormatError('Truncated pause indexed maps')
 count=struct.unpack_from('<H',blob)[0]
 if not 1<=count<=16 or len(blob)<2+2*count:raise FormatError('Map count invalid')
 offsets=struct.unpack_from('<'+'H'*count,blob,2)
 if offsets[0]!=2+2*count or list(offsets)!=sorted(set(offsets)):
  raise FormatError('Noncanonical map offsets')
 frames=[]
 for start,end in zip(offsets,(*offsets[1:],len(blob))):
  if not 0<=start<end<=len(blob) or start+2>end:raise FormatError('Map offset outside member')
  w,h=blob[start:start+2]
  if not w or not h or end-start!=2+2*w*h:raise FormatError('Map dimensions/length disagree')
  entries=struct.unpack_from('<'+'H'*(w*h),blob,start+2)
  frames.append(MapFrame(w,h,entries))
 return tuple(frames)


def decode_tiles(blob):
 if not blob or len(blob)%32:raise FormatError('Partial 4bpp tile')
 tiles=[]
 for start in range(0,len(blob),32):
  pixels=bytes(v for b in blob[start:start+32] for v in (b&15,b>>4))
  tiles.append(Image.frombytes('L',(8,8),pixels))
 return tuple(tiles)


def render_map(tiles,frame,base=TILE_BASE):
 out=Image.new('L',(frame.width*8,frame.height*8))
 for i,entry in enumerate(frame.entries):
  if entry==BLANK:continue
  # This known member uses bank0 for all foreground. Not general BG support.
  if entry>>12:raise FormatError('Unsupported pause palette bank')
  index=(entry&1023)-base
  if not 0<=index<len(tiles):raise FormatError('Pause tile outside resource')
  tile=tiles[index]
  if entry&1024:tile=tile.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
  if entry&2048:tile=tile.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
  out.paste(tile,((i%frame.width)*8,(i//frame.width)*8))
 return out


def encode_tile(tile):
 if tile.mode!='L' or tile.size!=(8,8):raise FormatError('Native 8x8 index tile required')
 p=tile.tobytes()
 if any(v>15 for v in p):raise FormatError('Not a 4bpp nibble')
 return bytes(p[i]|(p[i+1]<<4) for i in range(0,64,2))


def strip_positions(frame,first,columns):
 wanted=set(range(first,first+columns*2));found={}
 for i,e in enumerate(frame.entries):
  n=(e&1023)-TILE_BASE
  if e!=BLANK and n in wanted:
   if e&0xfc00 or n in found:raise FormatError('Strip uses transformed/duplicate tiles')
   found[n]=(i%frame.width,i//frame.width)
 if set(found)!=wanted:raise FormatError('Strip not wholly present')
 x,y=found[first]
 for n in range(columns*2):
  if found[first+n]!=(x+n%columns,y+n//columns):raise FormatError('Not row-major label strip')
 return (x*8,y*8,(x+columns)*8,(y+2)*8)


def native_label(text,width):
 if not isinstance(text,str) or not text or any(c in text for c in '\n\r<>'):
  raise FormatError('One fixed bounded label required')
 if type(width)is not int or width%8 or width<16:raise FormatError('Invalid strip width')
 if len(text)*14+2>width:raise FormatError('Chinese label would clip')
 mask=Image.new('L',(width,16));metadata=[];x0=(width-len(text)*14)//2
 for i,ch in enumerate(text):
  glyph,meta=render_glyph(ch,'crisp14',advance=14)
  metadata.append(meta)
  for y in range(16):
   for x in range(16):
    if glyph[y*16+x]==4:
     xx=x0+i*14+x
     if not 1<=xx<width-1 or not 1<=y<15:raise FormatError('Label ink not padded for border')
     mask.putpixel((xx,y),1)
 out=Image.new('L',(width,16))
 # Contrast border is symmetric1px, not a drop shadow or resized bitmap.
 # Original pause labels are foreground-white on busy scenery, unlike paper body.
 for y in range(16):
  for x in range(width):
   if mask.getpixel((x,y)):
    for dx,dy in ((-1,0),(1,0),(0,-1),(0,1)):
     out.putpixel((x+dx,y+dy),4)
 for y in range(16):
  for x in range(width):
   if mask.getpixel((x,y)):out.putpixel((x,y),1)
 return out,metadata


def replace_pause(pack,labels=None):
 if hashlib.sha256(pack).hexdigest()!=SOURCE_PACK_SHA or len(pack)!=PACK_SIZE:
  raise FormatError('Pause source fingerprint mismatch')
 labels=LABELS if labels is None else labels
 if set(labels)!=set(LABELS):raise FormatError('Four explicit labels required')
 members=unpack(pack)
 if [(m.offset,m.size) for m in members]!=[(36,10240),(10276,934),(11212,4096),(15308,370)]:
  raise FormatError('Pause member layout mismatch')
 m0,m1=members[:2];atlas=bytearray(pack[m0.offset:m0.offset+m0.size])
 maps=pack[m1.offset:m1.offset+m1.size]
 if hashlib.sha256(maps).hexdigest()!=SOURCE_MAP_SHA:raise FormatError('Pause maps drift')
 frames=indexed_maps(maps)
 if len(frames)!=2 or any((f.width,f.height)!=(21,11) for f in frames):
  raise FormatError('Ordinary pause dimensions drift')
 touched=set();rows=[]
 for first,columns,key,fnum in STRIPS:
  ids=set(range(first,first+columns*2))
  if touched&ids:raise FormatError('Shared label storage overlap')
  touched|=ids
  targets=range(2) if fnum is None else (fnum,)
  rects=[strip_positions(frames[f],first,columns) for f in targets]
  picture,glyphs=native_label(labels[key],columns*8)
  for n in range(columns*2):
   tile=picture.crop(((n%columns)*8,(n//columns)*8,(n%columns+1)*8,(n//columns+1)*8))
   atlas[(first+n)*32:(first+n+1)*32]=encode_tile(tile)
  rows.append(dict(label=key,source_JP=JP_LABELS[key],translation=labels[key],
                   native_design14=True,symmetric_contrast_border1=True,not_resampled=True,
                   first_tile=first,columns=columns,frames=list(targets),map_rects=rects,glyphs=glyphs))
 if touched!=set(range(32,186)):raise FormatError('Unexpected tile ownership')
 for f in frames:
  # Every glyph-strip reference belongs to the explicit labels, not hidden aliases.
  if any(e!=BLANK and 32<=(e&1023)-TILE_BASE<186 and e&0xfc00 for e in f.entries):
   raise FormatError('Transformed shared label alias')
 result=bytearray(pack);result[m0.offset:m0.offset+m0.size]=atlas
 # Structural bytes are exactly kept. No map reindexing or new resource sizes.
 assert result[:m0.offset]==pack[:m0.offset] and result[m0.offset+m0.size:]==pack[m0.offset+m0.size:]
 assert atlas[:32*32]==pack[m0.offset:m0.offset+32*32]
 assert atlas[186*32:]==pack[m0.offset+186*32:m0.offset+m0.size]
 return bytes(result),dict(labels=rows,profile=profile_manifest('crisp14'),
  file_bytes_equal_size=True,changed_allowed_tiles=[32,185],map_bytes_unchanged=True,
  top_hud_tiles186_319_and_blank0_31_untouched=True,battle_members2_3_untouched=True,
  no_code_fonts_palette_or_save_changes=True,fixed_graphic_strings4_not_body_records=True)


def color_view(index_image):
 out=Image.new('RGB',index_image.size)
 for y in range(out.height):
  for x in range(out.width):out.putpixel((x,y),OBSERVED_COLORS[index_image.getpixel((x,y))])
 return out
