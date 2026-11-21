"""English for the text built into the eboot (result screen, confirm dialogs, save/DLC messages, name lists).

Usage: python -P tools/build_eboot.py [--elf eboot/patch/PCSG00675/eboot.bin.elf] [--auth .../self_auth.bin]
                                      [--out build/rePatch/PCSG00675]

Some on-screen text is not in the string tables but in the eboot's read-only data as NUL-terminated UTF-8 (e.g.
'このミッションを遊びます。よろしいですか？', the result screen labels). text/eboot.json maps the first 10 hex digits of
sha1(Japanese UTF-8) to English, like the string tables. Every NUL-terminated string in the first (code + rodata)
segment whose hash is in the table is overwritten in place: the English must fit in the original bytes plus the
NUL padding up to the next 4-byte boundary, the rest is filled with NULs. Pointers don't move, so nothing else changes.

Input is the update 1.02 ELF from FAGDec (eboot.bin.elf); the output eboot.bin is a fake-signed SELF (tools/fself.py)
that rePatch loads from ux0:rePatch/PCSG00675/eboot.bin.
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fself import authid_from_self_auth, make_fself

ROOT = Path(__file__).resolve().parent.parent
FAG = ROOT / 'eboot/patch/PCSG00675'
TABLE = ROOT / 'text/eboot.json'


def seg0(elf):
    e_phoff, = struct.unpack_from('<I', elf, 28)
    _, off, _, _, filesz, *_ = struct.unpack_from('<8I', elf, e_phoff)
    return off, off + filesz


def patch(elf: bytes, table: dict) -> tuple[bytes, int, set]:
    out = bytearray(elf)
    lo, hi = seg0(elf)
    n, used, i = 0, set(), lo
    while i < hi:
        j = elf.find(b'\0', i, hi)
        if j < 0:
            break
        s = elf[i:j]
        if s and elf[i - 1] == 0:
            k = hashlib.sha1(s).hexdigest()[:10]
            if k in table:
                try:
                    s.decode('utf8')
                except UnicodeDecodeError:
                    pass
                else:
                    end = j + 1
                    while end < hi and elf[end] == 0 and end % 4:
                        end += 1
                    en = table[k].encode('utf8')
                    if len(en) > end - i - 1:
                        raise ValueError(f'{k}: "{table[k]}" is {len(en)} bytes, only {end - i - 1} fit')
                    out[i:end] = en + bytes(end - i - len(en))
                    n += 1
                    used.add(k)
        i = j + 1
    return bytes(out), n, used


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--elf', type=Path, default=FAG / 'eboot.bin.elf')
    ap.add_argument('--auth', type=Path, default=FAG / 'self_auth.bin')
    ap.add_argument('--out', type=Path, default=ROOT / 'build/rePatch/PCSG00675')
    a = ap.parse_args()
    table = json.loads(TABLE.read_text(encoding='utf8'))
    elf, n, used = patch(a.elf.read_bytes(), table)
    unused = set(table) - used
    if unused:
        print(f'warning: {len(unused)} entries not found in the ELF: {sorted(unused)[:5]}')
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'eboot.bin').write_bytes(make_fself(elf, authid=authid_from_self_auth(a.auth), compress=False))
    print(f'eboot.bin: {n} strings replaced ({len(used)} of {len(table)} entries)')


if __name__ == '__main__':
    main()
