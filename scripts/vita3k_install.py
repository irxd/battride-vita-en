"""Install the decrypted game into Vita3K for testing, and copy the patched files over it.

    python -P scripts/vita3k_install.py [--ux0 <Vita3K ux0 folder>] [--base] [--original]

--base       (re)copy the decrypted game with update 1.02 merged in (Vita3K reads only ux0/app; it merges updates
             when it installs them), make an fself eboot from eboot/patch/*/eboot.bin.elf, and add the license
--original   put the unpatched game files back instead of the patched ones
Without flags, only the files in build/rePatch/PCSG00675 are copied.
"""
import argparse, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
from fself import make_fself

TID = 'PCSG00675'
DEFAULT_UX0 = Path.home() / 'AppData/Roaming/Vita3K/Vita3K/ux0'
DEC = [ROOT / 'decrypted/patch' / TID, ROOT / 'decrypted/app' / TID]    # 1.02 first


def original(rel):
    return next(d / rel for d in DEC if (d / rel).is_file())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ux0', type=Path, default=DEFAULT_UX0)
    ap.add_argument('--base', action='store_true')
    ap.add_argument('--original', action='store_true')
    a = ap.parse_args()
    app = a.ux0 / 'app' / TID
    if a.base:
        for src in reversed(DEC):
            print(f'copying {src} -> {app}')
            shutil.copytree(src, app, dirs_exist_ok=True)
        elf = (ROOT / 'eboot/patch' / TID / 'eboot.bin.elf').read_bytes()
        (app / 'eboot.bin').write_bytes(make_fself(elf, compress=False))
        # the game's sce_module/*.suprx stay NPDRM-encrypted; Vita3K decrypts them with the NoNpDrm license
        lic = a.ux0 / 'license' / TID / 'JP0700-PCSG00675_00-MASKEDRIDERBWLN0.rif'
        lic.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'dump/app' / TID / 'sce_sys/package/work.bin', lic)
    patched = ROOT / 'build/rePatch' / TID
    for f in sorted(p for p in patched.rglob('*') if p.is_file()):
        rel = f.relative_to(patched)
        shutil.copyfile(original(rel) if a.original else f, app / rel)
        print(f'{"restored" if a.original else "patched"} {rel}')


if __name__ == '__main__':
    main()
