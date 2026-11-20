"""Vita GXT textures: parse, decode to PNG, re-encode.

Usage:
  gxt.py info <file.gxt>...
  gxt.py dump <dir> <outdir>          decode every GXT in an extracted archive folder to PNG
"""
import struct
import sys
from pathlib import Path
from PIL import Image

TYPES = {0x00000000: 'swizzled', 0x40000000: 'cube', 0x60000000: 'linear', 0x80000000: 'tiled',
         0x0C000000: 'linear_strided'}
# base formats (SceGxmTextureBaseFormat, top byte(s) of the format word)
FMT = {0x85000000: 'UBC1', 0x86000000: 'UBC2', 0x87000000: 'UBC3', 0x0C000000: 'U8U8U8U8',
       0x94000000: 'P8', 0x95000000: 'P4', 0x00000000: 'U8', 0x05000000: 'U4U4U4U4',
       0x04000000: 'U5U6U5', 0x10000000: 'U5U5U5U1', 0x8B000000: 'PVRTII2', 0x80000000: 'PVRT2BPP',
       0x81000000: 'PVRT4BPP', 0x82000000: 'PVRTII2BPP', 0x83000000: 'PVRTII4BPP'}


def parse(data):
    magic, ver, n, doff, dsize, np4, np8, _ = struct.unpack_from('<4s7I', data, 0)
    assert magic == b'GXT\0', magic
    texs = []
    for i in range(n):
        off = 0x20 + i * 0x20
        o, size, pal, flags, typ, fmt, w, h, mips, _ = struct.unpack_from('<6I4H', data, off)
        texs.append(dict(off=o, size=size, pal=pal, flags=flags, type=typ, fmt=fmt, w=w, h=h, mips=mips,
                         hdr=off))
    # palettes follow the texture data: P4 palettes (16*4 bytes) then P8 (256*4)
    pal_base = doff + dsize - np4 * 64 - np8 * 1024
    return dict(ver=ver, n=n, doff=doff, dsize=dsize, np4=np4, np8=np8, texs=texs, pal_base=pal_base)


def fmt_name(t):
    return FMT.get(t['fmt'] & 0xFF000000, hex(t['fmt']))


def _morton(x, y):
    r = 0
    for i in range(16):
        r |= ((y >> i) & 1) << (2 * i) | ((x >> i) & 1) << (2 * i + 1)
    return r


def swizzle_index_table(bw, bh):
    """For a bw x bh grid (units: blocks or pixels), linear index -> swizzled index (Vita morton order)."""
    m = min(bw, bh)
    tab = [0] * (bw * bh)
    for y in range(bh):
        for x in range(bw):
            if bw >= bh:
                tile, lx, ly = x // m, x % m, y
            else:
                tile, lx, ly = y // m, x, y % m
            tab[y * bw + x] = tile * m * m + _morton(lx, ly)
    return tab


def _p2(v):
    p = 1
    while p < v:
        p <<= 1
    return p


def unswizzle(data, bw, bh, unit):
    """Swizzled textures are stored at power-of-two dimensions."""
    pw, ph = _p2(bw), _p2(bh)
    tab = swizzle_index_table(pw, ph)
    out = bytearray(bw * bh * unit)
    for y in range(bh):
        for x in range(bw):
            s = tab[y * pw + x] * unit
            d = (y * bw + x) * unit
            out[d:d + unit] = data[s:s + unit]
    return bytes(out)


def swizzle(lin, bw, bh, unit, size):
    pw, ph = _p2(bw), _p2(bh)
    tab = swizzle_index_table(pw, ph)
    out = bytearray(size)
    for y in range(bh):
        for x in range(bw):
            s = (y * bw + x) * unit
            d = tab[y * pw + x] * unit
            out[d:d + unit] = lin[s:s + unit]
    return bytes(out)


def layout(t):
    """(block w, block h, bytes per unit, pixels per unit side) of the top mip."""
    f = fmt_name(t)
    if f in ('UBC1', 'UBC2', 'UBC3'):
        return (t['w'] + 3) // 4, (t['h'] + 3) // 4, 8 if f == 'UBC1' else 16, 4
    bpp = {'U8U8U8U8': 4, 'P8': 1, 'U8': 1, 'U4U4U4U4': 2, 'U5U6U5': 2, 'U5U5U5U1': 2}[f]
    return t['w'], t['h'], bpp, 1


def linear_data(data, t):
    bw, bh, unit, _ = layout(t)
    raw = data[t['off']:t['off'] + t['size']]
    typ = TYPES.get(t['type'] & 0xFF000000 if t['type'] & 0xFF000000 else t['type'], t['type'])
    if typ == 'swizzled':
        return unswizzle(raw, bw, bh, unit)
    if typ in ('linear', 'linear_strided'):
        # linear rows are padded to 8 pixels? keep simple: assume no padding unless size says so
        stride = len(raw) // bh if bh else 0
        rowb = bw * unit
        if stride > rowb and stride * bh <= len(raw):
            return b''.join(raw[y * stride:y * stride + rowb] for y in range(bh))
        return raw[:bw * bh * unit]
    raise NotImplementedError(f'texture type {t["type"]:#x}')


def palette(data, g, t):
    f = fmt_name(t)
    if f == 'P8':
        o = g['pal_base'] + g['np4'] * 64 + t['pal'] * 1024
        n = 256
    else:
        o = g['pal_base'] + t['pal'] * 64
        n = 16
    return [tuple(data[o + i * 4:o + i * 4 + 4]) for i in range(n)]


def order(t, px):
    """Swap channel order according to the swizzle field of the format word (ABGR is Vita default)."""
    sw = t['fmt'] & 0x0000F000
    if sw == 0x1000:   # ARGB -> stored as B,G,R,A bytes
        return px[2], px[1], px[0], px[3]
    return px


def decode(data, t, g=None):
    f = fmt_name(t)
    lin = linear_data(data, t)
    w, h = t['w'], t['h']
    if f in ('UBC1', 'UBC2', 'UBC3'):
        bw, bh, unit, _ = layout(t)
        n = {'UBC1': 1, 'UBC2': 2, 'UBC3': 3}[f]
        img = Image.frombytes('RGBA', (bw * 4, bh * 4), lin, 'bcn', n)
        return img.crop((0, 0, w, h))
    if f == 'U8U8U8U8':
        img = Image.frombytes('RGBA', (w, h), lin)
        if (t['fmt'] & 0xF000) == 0x1000:
            b, gch, r, a = img.split()
            img = Image.merge('RGBA', (r, gch, b, a))
        return img
    if f == 'P8':
        pal = palette(data, g, t)
        sw = (t['fmt'] & 0xF000) == 0x1000
        img = Image.new('RGBA', (w, h))
        img.putdata([(p[2], p[1], p[0], p[3]) if sw else p for p in (pal[i] for i in lin)])
        return img
    if f == 'U8':
        return Image.frombytes('L', (w, h), lin).convert('RGBA')
    raise NotImplementedError(f)


def is_gxt(p):
    with open(p, 'rb') as fh:
        return fh.read(4) == b'GXT\0'


def main():
    cmd = sys.argv[1]
    if cmd == 'info':
        for a in sys.argv[2:]:
            d = Path(a).read_bytes()
            g = parse(d)
            for i, t in enumerate(g['texs']):
                print(a, i, f"{t['w']}x{t['h']}", fmt_name(t), hex(t['fmt']), TYPES.get(t['type'], hex(t['type'])),
                      'mips', t['mips'])
    elif cmd == 'dump':
        src, out = Path(sys.argv[2]), Path(sys.argv[3])
        out.mkdir(parents=True, exist_ok=True)
        for p in sorted(src.rglob('*')):
            if not p.is_file() or not is_gxt(p):
                continue
            d = p.read_bytes()
            g = parse(d)
            for i, t in enumerate(g['texs']):
                name = f"{p.relative_to(src).with_suffix('')}".replace('/', '_').replace(chr(92), '_')
                try:
                    decode(d, t, g).save(out / f'{name}_{i}.png')
                except Exception as e:
                    print('skip', p, i, fmt_name(t), TYPES.get(t['type'], hex(t['type'])), e)


if __name__ == '__main__':
    main()
