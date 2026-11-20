"""Minimal UnityFS (asset bundle, format 6) reader: unpack the files inside and pull out text.

Usage:
  unityfs.py ls <bundle>...                      list the files inside
  unityfs.py unpack <bundle> <outdir>             write the files inside
  unityfs.py strings <bundle> [--min N]           print Unity length-prefixed UTF-8 strings (4-byte aligned)
"""
import argparse
import lzma
import struct
import sys
from pathlib import Path


def lz4_block(src, usize):
    """Decompress one raw LZ4 block."""
    dst = bytearray()
    i, n = 0, len(src)
    while i < n:
        tok = src[i]; i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1
                lit += b
                if b != 255:
                    break
        dst += src[i:i + lit]; i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8); i += 2
        ml = tok & 15
        if ml == 15:
            while True:
                b = src[i]; i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(dst) - off
        if off >= ml:
            dst += dst[start:start + ml]
        else:
            for k in range(ml):
                dst.append(dst[start + k])
    if len(dst) != usize:
        raise ValueError(f'lz4: got {len(dst)} bytes, expected {usize}')
    return bytes(dst)


def decompress(data, kind, usize):
    if kind == 0:
        return data
    if kind == 1:
        props, dict_size = data[0], struct.unpack_from('<I', data, 1)[0]
        lc, rem = props % 9, props // 9
        lp, pb = rem % 5, rem // 5
        filt = [{'id': lzma.FILTER_LZMA1, 'dict_size': dict_size, 'lc': lc, 'lp': lp, 'pb': pb}]
        return lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=filt).decompress(data[5:], usize)
    if kind in (2, 3):
        return lz4_block(data, usize)
    raise ValueError(f'compression {kind}')


def _cstr(d, p):
    e = d.index(b'\0', p)
    return d[p:e].decode('utf8'), e + 1


def read_bundle(data):
    """Returns [(path, bytes)]."""
    assert data[:8] == b'UnityFS\0', data[:8]
    p = 8
    fmt = struct.unpack_from('>I', data, p)[0]; p += 4
    _, p = _cstr(data, p)
    _, p = _cstr(data, p)
    size, csize, usize, flags = struct.unpack_from('>QIII', data, p); p += 20
    if fmt >= 7:
        p = (p + 15) & ~15
    if flags & 0x80:
        info_raw = data[len(data) - csize:]
        body = p
    else:
        info_raw = data[p:p + csize]
        body = p + csize
    info = decompress(info_raw, flags & 0x3F, usize)
    q = 16
    nblocks = struct.unpack_from('>I', info, q)[0]; q += 4
    blocks = []
    for _ in range(nblocks):
        bu, bc, bf = struct.unpack_from('>IIH', info, q); q += 10
        blocks.append((bu, bc, bf))
    nnodes = struct.unpack_from('>I', info, q)[0]; q += 4
    nodes = []
    for _ in range(nnodes):
        off, sz, nf = struct.unpack_from('>qqI', info, q); q += 20
        name, q = _cstr(info, q)
        nodes.append((name, off, sz))
    stream = bytearray()
    for bu, bc, bf in blocks:
        stream += decompress(data[body:body + bc], bf & 0x3F, bu)
        body += bc
    return [(name, bytes(stream[off:off + sz])) for name, off, sz in nodes]


def strings(d, minlen=2):
    """Length-prefixed (u32 LE) UTF-8 strings at 4-byte aligned offsets."""
    out, p, n = [], 0, len(d)
    while p + 4 <= n:
        ln = struct.unpack_from('<I', d, p)[0]
        if minlen <= ln < 0x10000 and p + 4 + ln <= n:
            raw = d[p + 4:p + 4 + ln]
            try:
                s = raw.decode('utf8')
            except UnicodeDecodeError:
                s = None
            if s and s.isprintable() or (s and all(c.isprintable() or c in '\n\r\t' for c in s)):
                out.append((p, s))
                p = (p + 4 + ln + 3) & ~3
                continue
        p += 4
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['ls', 'unpack', 'strings'])
    ap.add_argument('files', nargs='+', type=Path)
    ap.add_argument('--min', type=int, default=2)
    a = ap.parse_args()
    out = sys.stdout
    if a.cmd == 'unpack':
        bundle, dst = a.files
        for name, d in read_bundle(bundle.read_bytes()):
            (dst / name).parent.mkdir(parents=True, exist_ok=True)
            (dst / name).write_bytes(d)
            print(len(d), name)
        return
    for f in a.files:
        for name, d in read_bundle(f.read_bytes()):
            if a.cmd == 'ls':
                print(f'{len(d):10d}  {f.name}:{name}')
            else:
                for off, s in strings(d, a.min):
                    out.write(f'{f.name}:{name}:{off:x}\t' + s.replace('\n', '\\n') + '\n')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
