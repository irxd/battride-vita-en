"""Sony PSARC archives (PS3/PS4/Vita): list and extract.

Usage:
  psarc.py ls <archive> [glob]
  psarc.py extract <archive> <outdir> [glob]...
"""
import argparse
import fnmatch
import lzma
import struct
import sys
import zlib
from pathlib import Path


class Psarc:
    def __init__(self, path):
        self.f = open(path, 'rb')
        h = self.f.read(0x20)
        assert h[:4] == b'PSAR', h[:4]
        self.comp = h[8:12]
        toc_len, esize, count, self.bsize, self.flags = struct.unpack_from('>IIIII', h, 12)
        toc = self.f.read(toc_len - 0x20)
        self.entries = []
        for i in range(count):
            e = toc[i * esize:(i + 1) * esize]
            block = struct.unpack_from('>I', e, 16)[0]
            usize = int.from_bytes(e[20:25], 'big')
            off = int.from_bytes(e[25:30], 'big')
            self.entries.append((block, usize, off))
        w = 2 if self.bsize <= 0x10000 else 3 if self.bsize <= 0x1000000 else 4
        tab = toc[count * esize:]
        self.sizes = [int.from_bytes(tab[k:k + w], 'big') for k in range(0, len(tab) - w + 1, w)]
        names = [n for n in self.read(0).decode('utf8').replace(chr(0), chr(10)).splitlines() if n]
        self.names = [n.lstrip('/') for n in names]

    def _block(self, data):
        if self.comp == b'zlib' and data[:1] == b'\x78':
            try:
                return zlib.decompress(data)
            except zlib.error:
                return data
        if self.comp == b'lzma' and data[:1] == b'\x5d':
            try:
                return lzma.decompress(data, format=lzma.FORMAT_ALONE)
            except lzma.LZMAError:
                return data
        return data

    def read(self, i):
        block, usize, off = self.entries[i]
        out = bytearray()
        self.f.seek(off)
        while len(out) < usize:
            cs = self.sizes[block] or self.bsize
            data = self.f.read(cs)
            # a block stored at its full output size is raw; anything shorter is compressed
            out += data if cs == min(self.bsize, usize - len(out)) else self._block(data)
            block += 1
        return bytes(out[:usize])

    def files(self):
        for i, n in enumerate(self.names, 1):
            yield n, i


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['ls', 'extract'])
    ap.add_argument('archive', type=Path)
    ap.add_argument('rest', nargs='*')
    a = ap.parse_args()
    p = Psarc(a.archive)
    pats = (a.rest[1:] if a.cmd == 'extract' else a.rest) or ['*']
    for name, i in p.files():
        if not any(fnmatch.fnmatch(name, pat) for pat in pats):
            continue
        if a.cmd == 'ls':
            print(f'{p.entries[i][1]:12d}  {name}')
            continue
        out = Path(a.rest[0]) / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(p.read(i))
        print(f'{p.entries[i][1]:12d}  {name}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
