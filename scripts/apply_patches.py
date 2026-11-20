"""Apply the English patch on a PC (no other tools needed: Python 3.8+ only).

Usage:
    python apply_patches.py <decrypted game folder> [<decrypted update folder>] [--out <folder>]

The folders are the decrypted copies of ux0:app/PCSG00675 (game) and ux0:patch/PCSG00675 (update 1.02), e.g.
copied from VitaShell's "Open decrypted" over FTP, or Vita3K's ux0/app/PCSG00675 (Vita3K merges the update
into it, so one folder is enough). Each file is matched by its path and SHA-1, then patched.

Output: <out>/rePatch/PCSG00675/... (default out: the current folder). Copy that rePatch folder to ux0: on the
Vita (needs the rePatch plugin).

The patches and manifest.json are read from the patches/ folder next to this script (or ../patches).
The VCDIFF decoder below handles what `xdelta3 -e -S none -A` writes (same as the web patcher).
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

VCD_SOURCE, VCD_TARGET, VCD_ADLER32 = 1, 2, 4
NOOP, ADD, RUN, COPY = 0, 1, 2, 3


def _code_table():
    t = [(RUN, 0, 0, NOOP, 0, 0), (ADD, 0, 0, NOOP, 0, 0)]
    t += [(ADD, s, 0, NOOP, 0, 0) for s in range(1, 18)]
    for m in range(9):
        t.append((COPY, 0, m, NOOP, 0, 0))
        t += [(COPY, s, m, NOOP, 0, 0) for s in range(4, 19)]
    for m in range(6):
        t += [(ADD, a, 0, COPY, c, m) for a in range(1, 5) for c in range(4, 7)]
    for m in range(6, 9):
        t += [(ADD, a, 0, COPY, 4, m) for a in range(1, 5)]
    t += [(COPY, 4, m, ADD, 1, 0) for m in range(9)]
    assert len(t) == 256
    return t


CODE_TABLE = _code_table()


class PatchError(Exception):
    pass


class Reader:
    def __init__(self, buf, pos=0, end=None):
        self.buf, self.pos, self.end = buf, pos, len(buf) if end is None else end

    def byte(self):
        if self.pos >= self.end:
            raise PatchError('patch file is truncated or damaged')
        self.pos += 1
        return self.buf[self.pos - 1]

    def varint(self):
        v = 0
        while True:
            b = self.byte()
            v = v * 128 + (b & 0x7f)
            if not b & 0x80:
                return v

    def bytes(self, n):
        if self.pos + n > self.end:
            raise PatchError('patch file is truncated or damaged')
        self.pos += n
        return self.buf[self.pos - n:self.pos]


def adler32(buf):
    import zlib
    return zlib.adler32(buf) & 0xffffffff


def decode_window(src, tlen, data, inst, addr):
    out = bytearray(tlen)
    slen = len(src)
    near, same = [0, 0, 0, 0], [0] * 768
    nxt = 0
    t = 0

    def decode_addr(mode):
        nonlocal nxt
        here = slen + t
        if mode == 0:
            a = addr.varint()
        elif mode == 1:
            a = here - addr.varint()
        elif mode < 6:
            a = near[mode - 2] + addr.varint()
        else:
            a = same[(mode - 6) * 256 + addr.byte()]
        near[nxt] = a
        nxt = (nxt + 1) & 3
        same[a % 768] = a
        return a

    while inst.pos < inst.end:
        c = CODE_TABLE[inst.byte()]
        for typ, size, mode in ((c[0], c[1], c[2]), (c[3], c[4], c[5])):
            if typ == NOOP:
                continue
            if size == 0:
                size = inst.varint()
            if t + size > tlen:
                raise PatchError('patch writes past the end of a window (damaged patch)')
            if typ == ADD:
                out[t:t + size] = data.bytes(size)
            elif typ == RUN:
                out[t:t + size] = bytes([data.byte()]) * size
            else:
                a = decode_addr(mode)
                if a >= slen + t:
                    raise PatchError('bad copy address (damaged patch)')
                n, d = size, t
                if a < slen:
                    k = min(n, slen - a)
                    out[d:d + k] = src[a:a + k]
                    a += k
                    d += k
                    n -= k
                if n > 0:
                    s = a - slen
                    if s + n <= d:
                        out[d:d + n] = out[s:s + n]
                    else:
                        for i in range(n):
                            out[d + i] = out[s + i]
            t += size
    if t != tlen:
        raise PatchError('window size mismatch (damaged patch)')
    return out


def apply_patch(patch, src_file, out_file):
    r = Reader(patch)
    if bytes([r.byte(), r.byte(), r.byte()]) != b'\xd6\xc3\xc4':
        raise PatchError('not an xdelta / VCDIFF patch')
    r.byte()
    hdr = r.byte()
    if hdr & 3:
        raise PatchError('unsupported patch (secondary compression or custom code table)')
    if hdr & 4:
        r.bytes(r.varint())
    total = 0
    while r.pos < r.end:
        win = r.byte()
        if win & VCD_TARGET:
            raise PatchError('target-referencing windows are unsupported')
        src = b''
        if win & VCD_SOURCE:
            ln, pos = r.varint(), r.varint()
            src_file.seek(pos)
            src = src_file.read(ln)
            if len(src) != ln:
                raise PatchError('original file is too short (wrong file?)')
        r.varint()
        tlen = r.varint()
        if r.byte() != 0:
            raise PatchError('compressed patch sections are unsupported')
        dl, il, al = r.varint(), r.varint(), r.varint()
        want = int.from_bytes(r.bytes(4), 'big') if win & VCD_ADLER32 else None
        data = Reader(patch, r.pos, r.pos + dl); r.pos += dl
        inst = Reader(patch, r.pos, r.pos + il); r.pos += il
        addr = Reader(patch, r.pos, r.pos + al); r.pos += al
        out = decode_window(src, tlen, data, inst, addr)
        if want is not None and adler32(out) != want:
            raise PatchError('checksum mismatch: the original file does not match this patch')
        out_file.write(out)
        total += len(out)
    return total


def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('folders', nargs='+', type=Path, help='decrypted game folder, and the update folder')
    ap.add_argument('--out', type=Path, default=Path('.'))
    ap.add_argument('--patches', type=Path, help='folder with manifest.json (default: patches/ next to this script)')
    a = ap.parse_args()
    here = Path(__file__).resolve().parent
    pdir = a.patches or next((p for p in (here / 'patches', here.parent / 'patches') if (p / 'manifest.json').exists()),
                             None)
    if not pdir:
        sys.exit('patches/manifest.json not found next to this script; use --patches')
    man = json.loads((pdir / 'manifest.json').read_text(encoding='utf-8'))
    bad = 0
    for i, e in enumerate(man['files'], 1):
        rel, want = e['source']['path'], e['source']['sha1']
        src = None
        for folder in a.folders:
            for cand in (folder / rel, folder / rel.split('/', 1)[1] if '/' in rel else None):
                if cand and cand.is_file() and cand.stat().st_size == e['source']['size'] and sha1(cand) == want:
                    src = cand
                    break
            if src:
                break
        if not src:
            print(f'[{i}/{len(man["files"])}] MISSING {rel} (need the decrypted '
                  f'{"update 1.02" if e["source"]["origin"] == "patch" else "game"} file, SHA-1 {want})')
            bad += 1
            continue
        dst = a.out / e['target']['path']
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(src, 'rb') as sf, open(dst, 'wb') as of:
                apply_patch((pdir / e['patch']).read_bytes(), sf, of)
            if sha1(dst) != e['target']['sha1']:
                raise PatchError('patched file has the wrong checksum')
        except PatchError as err:
            print(f'[{i}/{len(man["files"])}] FAILED {rel}: {err}')
            dst.unlink(missing_ok=True)
            bad += 1
            continue
        print(f'[{i}/{len(man["files"])}] ok {e["target"]["path"]}')
    if bad:
        sys.exit(f'{bad} file(s) not patched, see above')
    print(f'done: copy {a.out / "rePatch"} to ux0: on your Vita')


if __name__ == '__main__':
    main()
