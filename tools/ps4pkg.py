"""Read PS4 fake PKGs (PFS image inside, XTS-encrypted; inner pfs_image.dat PFSC-compressed) without extracting
everything. AES comes from Windows bcrypt.dll (no extra Python packages).

Usage:
  ps4pkg.py info <pkg>
  ps4pkg.py ls <pkg> [glob]                 list files of the game image (path, size)
  ps4pkg.py extract <pkg> <outdir> [glob]...  extract matching files (default: everything)

Fake PKGs (made with the public tools) derive the PFS key from the content ID and the passcode (all zeros unless
--passcode is given): EKPFS = sha256(index || sha256(content id padded to 48 bytes) || passcode).
"""
import argparse
import ctypes
import fnmatch
import hashlib
import hmac
import struct
import sys
import zlib
from ctypes import byref, c_void_p, c_ulong
from functools import lru_cache
from pathlib import Path

# ---------------------------------------------------------------- AES (Windows CNG)
_bc = ctypes.WinDLL('bcrypt')


class Aes:
    def __init__(self, key):
        self.alg, self.key = c_void_p(), c_void_p()
        assert _bc.BCryptOpenAlgorithmProvider(byref(self.alg), 'AES', None, 0) == 0
        mode = ctypes.create_unicode_buffer('ChainingModeECB')
        assert _bc.BCryptSetProperty(self.alg, 'ChainingMode', mode, ctypes.sizeof(mode), 0) == 0
        self._k = ctypes.create_string_buffer(bytes(key))
        assert _bc.BCryptGenerateSymmetricKey(self.alg, byref(self.key), None, 0, self._k, len(key), 0) == 0

    def _run(self, fn, data):
        src = ctypes.create_string_buffer(bytes(data), len(data))
        dst = ctypes.create_string_buffer(len(data))
        n = c_ulong()
        assert fn(self.key, src, len(data), None, None, 0, dst, len(data), byref(n), 0) == 0
        return dst.raw

    def encrypt(self, data):
        return self._run(_bc.BCryptEncrypt, data)

    def decrypt(self, data):
        return self._run(_bc.BCryptDecrypt, data)


class Xts:
    """AES-128-XTS, decrypt only; tweak = sector number (little endian)."""
    MASK = (1 << 128) - 1

    def __init__(self, data_key, tweak_key, sector=0x1000):
        self.d, self.t, self.sector = Aes(data_key), Aes(tweak_key), sector

    def decrypt_sector(self, data, num):
        t = int.from_bytes(self.t.encrypt(num.to_bytes(16, 'little')), 'little')
        tw = bytearray()
        for _ in range(len(data) // 16):
            tw += t.to_bytes(16, 'little')
            t = ((t << 1) & self.MASK) ^ (0x87 if t >> 127 else 0)
        n = len(data)
        x = (int.from_bytes(data, 'little') ^ int.from_bytes(tw, 'little')).to_bytes(n, 'little')
        p = self.d.decrypt(x)
        return (int.from_bytes(p, 'little') ^ int.from_bytes(tw, 'little')).to_bytes(n, 'little')


# ---------------------------------------------------------------- byte sources with random access
class FileSrc:
    def __init__(self, f, off, size):
        self.f, self.off, self.size = f, off, size

    def read(self, pos, n):
        self.f.seek(self.off + pos)
        return self.f.read(n)


class XtsSrc:
    """Encrypted PFS image: sectors from `start` on are XTS-encrypted."""
    def __init__(self, src, xts, start_sector):
        self.src, self.xts, self.start, self.size = src, xts, start_sector, src.size

    @lru_cache(maxsize=4096)
    def _sector(self, i):
        raw = self.src.read(i * 0x1000, 0x1000)
        return raw if i < self.start else self.xts.decrypt_sector(raw, i)

    def read(self, pos, n):
        out = bytearray()
        while n > 0:
            i, o = divmod(pos, 0x1000)
            chunk = self._sector(i)[o:o + n]
            if not chunk:
                break
            out += chunk
            pos += len(chunk)
            n -= len(chunk)
        return bytes(out)


class SubSrc:
    def __init__(self, src, off, size):
        self.src, self.off, self.size = src, off, size

    def read(self, pos, n):
        n = max(0, min(n, self.size - pos))
        return self.src.read(self.off + pos, n)


class PfscSrc:
    """PFSC-compressed data: block table of offsets, each block zlib-compressed unless stored raw."""
    def __init__(self, src):
        self.src = src
        h = src.read(0, 0x30)
        assert h[:4] == b'PFSC', h[:4]
        self.bsize = struct.unpack_from('<I', h, 0xC)[0]
        table, self.data_start, self.size = struct.unpack_from('<QQQ', h, 0x18)
        n = (self.size + self.bsize - 1) // self.bsize
        self.offs = struct.unpack(f'<{n + 1}Q', src.read(table, 8 * (n + 1)))

    @lru_cache(maxsize=256)
    def _block(self, i):
        a, b = self.offs[i], self.offs[i + 1]
        raw = self.src.read(a, b - a)
        if b - a == self.bsize:
            return raw
        if b - a == 0:
            return bytes(self.bsize)
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -15)

    def read(self, pos, n):
        out = bytearray()
        n = max(0, min(n, self.size - pos))
        while n > 0:
            i, o = divmod(pos, self.bsize)
            chunk = self._block(i)[o:o + n]
            out += chunk
            pos += len(chunk)
            n -= len(chunk)
        return bytes(out)


# ---------------------------------------------------------------- PFS
class Pfs:
    def __init__(self, src):
        self.src = src
        h = src.read(0, 0x400)
        ver, magic = struct.unpack_from('<QQ', h, 0)
        assert magic == 20130315, f'not a PFS image (magic {magic})'
        self.mode = struct.unpack_from('<H', h, 0x1C)[0]
        self.bsize = struct.unpack_from('<I', h, 0x20)[0]
        self.ndinode, self.ndblock, self.dinode_blocks = struct.unpack_from('<qqq', h, 0x30)
        self.superroot = struct.unpack_from('<q', h, 0x48)[0]
        self.seed = h[0x370:0x380]
        self.signed = bool(self.mode & 1)
        self.wide = bool(self.mode & 2)
        if self.signed:
            self.isize = 0x2C8 if not self.wide else 0x310
        else:
            self.isize = 0xA8 if not self.wide else 0xC8

    def inode(self, ino):
        per = self.bsize // self.isize
        b, k = divmod(ino, per)
        d = self.src.read((1 + b) * self.bsize + k * self.isize, self.isize)
        mode, nlink, flags, size, csize = struct.unpack_from('<HHIqq', d, 0)
        if self.signed:
            db0 = struct.unpack_from('<i', d, 0x64 + 32)[0]
        else:
            db0 = struct.unpack_from('<i', d, 0x64)[0]
        return dict(mode=mode, flags=flags, size=size, csize=csize, block=db0)

    def data(self, ino):
        i = self.inode(ino)
        size = i['csize'] if i['flags'] & 1 else i['size']
        return i, SubSrc(self.src, i['block'] * self.bsize, size)

    def dirents(self, ino):
        i, s = self.data(ino)
        d = s.read(0, i['size'])
        out, p = [], 0
        while p + 16 <= len(d):
            e_ino, typ, nlen, esize = struct.unpack_from('<iiii', d, p)
            if esize == 0:
                # entries do not cross blocks; skip to the next block
                p = (p // self.bsize + 1) * self.bsize
                continue
            name = d[p + 16:p + 16 + nlen].decode('utf8', 'replace')
            if typ not in (4, 5):
                out.append((name, e_ino, typ))
            p += esize
        return out

    def walk(self, ino=None, prefix=''):
        if ino is None:
            root = dict((n, i) for n, i, t in self.dirents(self.superroot))
            ino = root.get('uroot', self.superroot)
        for name, e, typ in self.dirents(ino):
            path = f'{prefix}{name}'
            if typ == 3:
                yield from self.walk(e, path + '/')
            else:
                yield path, e

    def open(self, ino):
        i, s = self.data(ino)
        if i['flags'] & 1:
            return PfscSrc(s)
        return s


# ---------------------------------------------------------------- PKG
def derived_key(content_id, passcode='0' * 32, index=1):
    """Fake-PKG derived key (LibOrbisPkg Crypto.ComputeKeys); index 1 is the EKPFS."""
    sha = lambda b: hashlib.sha256(b).digest()
    return sha(sha(index.to_bytes(4, 'big')) + sha(content_id.encode().ljust(48, b'\0')) + passcode.encode())


def check_passcode(f, content_id, passcode):
    """ENTRY_KEYS (entry 0x10) stores sha256(dk) xor dk for each derived key."""
    h = f.seek(0) or f.read(0x1000)
    table, = struct.unpack_from('>I', h, 0x18)
    count, = struct.unpack_from('>I', h, 0x10)
    f.seek(table)
    for _ in range(count):
        eid, _, _, _, off, size = struct.unpack('>6I', f.read(0x20)[:24])
        if eid == 0x10:
            f.seek(off)
            keys = f.read(size)
            dk = derived_key(content_id, passcode, 1)
            dig = bytes(a ^ b for a, b in zip(hashlib.sha256(dk).digest(), dk))
            return dig in keys
    return False


def open_pkg(path, passcode='0' * 32):
    f = open(path, 'rb')
    h = f.read(0x1000)
    assert h[:4] == b'\x7fCNT', 'not a PKG'
    content_id = h[0x40:0x64].decode()
    if not check_passcode(f, content_id, passcode):
        raise SystemExit('wrong passcode (not a fake PKG, or made with a custom passcode: use --passcode)')
    pfs_flags, pfs_off, pfs_size = struct.unpack_from('>QQQ', h, 0x408)
    outer_raw = FileSrc(f, pfs_off, pfs_size)
    hdr = outer_raw.read(0, 0x400)
    seed = hdr[0x370:0x380]
    ek = derived_key(content_id, passcode, 1)
    if pfs_flags & 0x2000000000000000:     # "new crypt": key material is HMAC(EKPFS, seed)
        ek = hmac.new(ek, seed, hashlib.sha256).digest()
    key = hmac.new(ek, (1).to_bytes(4, 'little') + seed, hashlib.sha256).digest()
    xts = Xts(key[16:], key[:16])
    outer = Pfs(XtsSrc(outer_raw, xts, 0x10000 // 0x1000))
    files = dict(outer.walk())
    img = 'pfs_image.dat'
    assert img in files, f'no pfs_image.dat in outer PFS: {list(files)[:10]}'
    inner = Pfs(outer.open(files[img]))
    return content_id, outer, inner


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['info', 'ls', 'extract'])
    ap.add_argument('pkg', type=Path)
    ap.add_argument('rest', nargs='*')
    ap.add_argument('--passcode', default='0' * 32)
    a = ap.parse_args()
    cid, outer, inner = open_pkg(a.pkg, a.passcode)
    if a.cmd == 'info':
        print('content id', cid)
        print('outer PFS: mode', hex(outer.mode), 'block', hex(outer.bsize), 'files', [p for p, _ in outer.walk()])
        print('inner PFS: mode', hex(inner.mode), 'block', hex(inner.bsize), 'inodes', inner.ndinode)
        return
    pats = (a.rest[1:] if a.cmd == 'extract' else a.rest) or ['*']
    for path, ino in inner.walk():
        if not any(fnmatch.fnmatch(path, p) for p in pats):
            continue
        s = inner.open(ino)
        if a.cmd == 'ls':
            print(f'{s.size:12d}  {path}')
            continue
        out = Path(a.rest[0]) / path
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, 'wb') as o:
            for pos in range(0, s.size, 1 << 20):
                o.write(s.read(pos, min(1 << 20, s.size - pos)))
        print(f'{s.size:12d}  {path}')


if __name__ == '__main__':
    sys.exit(main())
