"""FPK2 archives (Battride War Sousei, Vita): read, extract and rebuild.

Layout (little endian), reversed from the 1.02 eboot (loader at 0x81212b6a):

    header (0x30 bytes, rounded up to `align`):
      0x00 "FPK2"
      0x04 u32 version 0x204
      0x08 u8  flags      bit0 = entry table encrypted (high nibble is cleared by the loader)
      0x09 u8  flags2     bit 0x40 must be set
      0x0a u16 align      0 means 16
      0x0c u32 count
      0x10 u32 archive size
      0x14 ..  (unknown, kept)
      0x28 u64 table key
    count entries (0x20 bytes each, rounded up to `align`), each encrypted on its own with the table key:
      0x00 u64 key        data key (data is encrypted only when flags & 0x20; not used by any shipped file)
      0x08 u32 flags      0x04 = zlib, 0x10 = use the u16 at 0x1a as a mask for 0x18, 0x20 = data encrypted
      0x0c u32 offset     from the archive start
      0x10 u32 size       stored size
      0x14 u32 usize      size after decompression
      0x18 u16, 0x1a u16  (unknown, kept)
      0x1c u32 crc        CRC-32/BZIP2 of the decrypted entry with this field set to 0

The cipher (0x81213218) is an 8-byte-key byte mixer plus a 16-bit LFSR keystream; parameters come from a
10-row table in the eboot (0x81693068), copied below.
"""
import struct, zlib, sys, argparse
from pathlib import Path

MAGIC = b'FPK2'
# (w0, w1, w2, w3, rounds_per_byte, xor_byte) for each of the 10 rows at 0x81693068
ROWS = [(0x86, 0x87, 0xa4, 0xa5, 7, 0x75), (0x11, 0x12, 0x7c, 0x7d, 4, 0x53), (0x3e, 0x3f, 0x79, 0x7a, 8, 0xfc),
        (0x2a, 0x2c, 0x69, 0x6b, 3, 0x21), (0x19, 0x1b, 0x98, 0x9a, 5, 0xca), (0x36, 0x37, 0x45, 0x46, 4, 0x78),
        (0x63, 0x65, 0x7e, 0x80, 6, 0xb4), (0x2d, 0x2e, 0x73, 0x74, 3, 0x3d), (0x97, 0x99, 0xa6, 0xa8, 9, 0x44),
        (0x27, 0x28, 0x94, 0x95, 5, 0xc6)]


def _key_hash(key):
    h = 0
    for i, b in enumerate(key, 1):
        s = i & 31
        h = (h + ((b >> s) | (((b & ((1 << s) - 1)) << (32 - s)) & 0xffffffff))) & 0x7fffffff
    return h


def _schedule(key, n):
    """The byte-mixing steps: list of (target, [sources])."""
    h = _key_hash(key)
    w0, w1, w2, w3, rounds, xb = ROWS[h % 10]
    words = (w3, w2, w1, w0)            # the game reads them from sp+8..sp+0x14 in this order
    steps, r8 = [], 1
    for _ in range((rounds * n) & 0xffffffff):
        t = (r8 + n - 1) % n
        steps.append((t, [s for s in ((w + r8) % n for w in words) if s != t]))
        r8 += 1
        if n <= r8:
            r8 = 0
    return h, xb, steps


def _keystream(h, xb, n):
    r3 = (h ^ (h >> 16)) & 0xffff
    out = bytearray(n)
    for i in range(n):
        bit = (r3 ^ (r3 >> 2) ^ (r3 >> 3) ^ (r3 >> 5)) & 1
        r3 = (bit << 15) | ((r3 >> 1) & 0x7fff)
        out[i] = (r3 & 0xff) ^ xb
    return out


def decrypt(key, data):
    buf = bytearray(data)
    h, xb, steps = _schedule(key, len(buf))
    for t, srcs in steps:
        v = buf[t]
        for s in srcs:
            v ^= buf[s]
        buf[t] = v
    for i, k in enumerate(_keystream(h, xb, len(buf))):
        buf[i] ^= k
    return bytes(buf)


def encrypt(key, data):
    buf = bytearray(data)
    h, xb, steps = _schedule(key, len(buf))
    for i, k in enumerate(_keystream(h, xb, len(buf))):
        buf[i] ^= k
    for t, srcs in reversed(steps):     # each step is its own inverse (t is never one of its sources)
        v = buf[t]
        for s in srcs:
            v ^= buf[s]
        buf[t] = v
    return bytes(buf)


_CRC = []
for _i in range(256):
    _c = _i << 24
    for _ in range(8):
        _c = ((_c << 1) ^ 0x04C11DB7) if _c & 0x80000000 else (_c << 1)
    _CRC.append(_c & 0xffffffff)


def crc32_bzip2(data, crc=0xffffffff):
    for b in data:
        crc = ((crc << 8) & 0xffffffff) ^ _CRC[(crc >> 24) ^ b]
    return crc ^ 0xffffffff


def _round(x, a):
    return (x + a - 1) // a * a


class Entry:
    __slots__ = ('key', 'flags', 'offset', 'size', 'usize', 'u18', 'u1a', 'crc', 'data')

    def pack(self):
        raw = struct.pack('<QIIIIHHI', self.key, self.flags, self.offset, self.size, self.usize, self.u18, self.u1a, 0)
        return raw[:0x1c] + struct.pack('<I', crc32_bzip2(raw))

    def content(self):
        """The file's bytes after decompression."""
        if self.flags & 0x20:
            raise NotImplementedError('encrypted entry data')
        return zlib.decompress(self.data) if self.flags & 4 else self.data


class Fpk:
    def __init__(self, data):
        if data[:4] != MAGIC or struct.unpack_from('<I', data, 4)[0] != 0x204:
            raise ValueError('not an FPK2 archive')
        self.header = bytearray(data[:0x30])
        self.align = struct.unpack_from('<H', data, 0xa)[0] or 16
        count = struct.unpack_from('<I', data, 0xc)[0]
        key = data[0x28:0x30]
        hsize, esize = _round(0x30, self.align), _round(0x20, self.align)
        self.entries = []
        for i in range(count):
            raw = data[hsize + i * esize:hsize + i * esize + 0x20]
            if self.encrypted:
                raw = decrypt(key, raw)
            e = Entry()
            e.key, e.flags, e.offset, e.size, e.usize, e.u18, e.u1a, e.crc = struct.unpack('<QIIIIHHI', raw)
            if self.encrypted and crc32_bzip2(raw[:0x1c] + b'\0\0\0\0') != e.crc:
                raise ValueError(f'entry {i}: checksum mismatch')
            e.data = data[e.offset:e.offset + e.size]
            self.entries.append(e)
        self._raw = bytes(data)
        self._orig = [(e.offset, e.size) for e in self.entries]
        self._dirty = set()

    @property
    def encrypted(self):
        return bool(self.header[8] & 1)

    def build(self):
        """Rebuild the archive, keeping the original layout so patches stay small.

        Unchanged entries keep their bytes. A changed entry is written over its old data when it fits and no other
        entry shares that data (the original archives store identical files once); otherwise it goes at the end.
        """
        hsize, esize = _round(0x30, self.align), _round(0x20, self.align)
        out = bytearray(self._raw)
        users = {}
        for e in self.entries:
            users[e.offset] = users.get(e.offset, 0) + 1
        end = len(out)
        key = bytes(self.header[0x28:0x30])
        for i in sorted(self._dirty):
            e = self.entries[i]
            old_off, old_size = self._orig[i]
            if len(e.data) <= old_size and users[old_off] == 1:
                out[old_off:old_off + old_size] = bytes(old_size)
                e.offset = old_off
            else:
                e.offset = end
                end = _round(end + len(e.data), self.align)
                out.extend(bytes(end - len(out)))
            e.size = len(e.data)
            out[e.offset:e.offset + e.size] = e.data
            raw = e.pack()
            out[hsize + i * esize:hsize + i * esize + 0x20] = encrypt(key, raw) if self.encrypted else raw
        struct.pack_into('<I', out, 0x10, len(out))
        return bytes(out)

    def set_content(self, i, content, level=9):
        e = self.entries[i]
        e.usize = len(content)
        e.data = zlib.compress(content, level) if e.flags & 4 else bytes(content)
        self._dirty.add(i)


def main():
    ap = argparse.ArgumentParser(description='FPK2 archive tool')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('list'); s.add_argument('fpk', type=Path)
    s = sub.add_parser('extract'); s.add_argument('fpk', type=Path); s.add_argument('out', type=Path)
    a = ap.parse_args()
    f = Fpk(a.fpk.read_bytes())
    if a.cmd == 'list':
        print(f'{len(f.entries)} entries, align {f.align}, encrypted table: {f.encrypted}')
        for i, e in enumerate(f.entries):
            print(f'{i:5d} flags={e.flags:#04x} off={e.offset:#9x} size={e.size:8d} usize={e.usize:8d} '
                  f'u18={e.u18:#06x} u1a={e.u1a:#06x} key={e.key:016x}')
    elif a.cmd == 'extract':
        a.out.mkdir(parents=True, exist_ok=True)
        for i, e in enumerate(f.entries):
            (a.out / f'{i:04d}.bin').write_bytes(e.content())


if __name__ == '__main__':
    main()
