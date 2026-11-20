"""Build the English patch and package it as xdelta files (no game data is distributed).

Usage (from the repo root):
    python -P scripts/make_release.py <version>          e.g.  python -P scripts/make_release.py 0.1.0
    python -P scripts/make_release.py <version> --no-build   package the current build/ without rebuilding

Needs xdelta3 (tools/bin/xdelta3.exe, D:/Personal/shin-gundam-musou-en/tools/bin/xdelta3.exe, or on PATH) and
the decrypted game (scripts/decrypt_vita.ps1):
    decrypted/app/PCSG00675/     game 1.00
    decrypted/patch/PCSG00675/   update 1.02 (its files replace the 1.00 ones, so they are the patch sources)

Steps: clean build/rePatch/PCSG00675, run tools/build_text.py build, tools/build_images.py and tools/build_movies.py
(movie subtitles; needs ffmpeg with h264_nvenc, path from $FFMPEG or the default in build_movies.py), then make one
xdelta patch per changed file against its 1.02 original (round-trip checked).

Output:
    release/battride-war-genesis-en-<version>/          patches/ + manifest.json + checksums.txt + tools/
    release/battride-war-genesis-en-<version>.zip       the same, zipped: this is what gets published
    release/battride-war-genesis-en-<version>-rePatch-LOCAL-ONLY.zip
                                                        the patched rePatch folder, for your own testing.
                                                        It holds game data: never publish it.
    docs/patcher/patches/                               patches + manifest.json for the web patcher
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TID = 'PCSG00675'
BUILD = ROOT / 'build/rePatch' / TID
ORIG = [('patch', ROOT / 'decrypted/patch' / TID), ('app', ROOT / 'decrypted/app' / TID)]   # 1.02 first
WEB = ROOT / 'docs/patcher/patches'
NAME = 'battride-war-genesis-en'
PLAYER_TOOLS = [ROOT / 'scripts/apply_patches.py', ROOT / 'tools/rename_title.py', ROOT / 'tools/build_sfo.py']


def run(*args):
    print('>', ' '.join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], check=True)


def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def find_xdelta():
    for p in (ROOT / 'tools/bin/xdelta3.exe', Path('D:/Personal/shin-gundam-musou-en/tools/bin/xdelta3.exe')):
        if p.exists():
            return p
    for name in ('xdelta3', 'xdelta'):
        p = shutil.which(name)
        if p:
            return Path(p)
    sys.exit('xdelta3 not found: put xdelta3.exe in tools/bin/ or on PATH')


def original(rel):
    for origin, d in ORIG:
        if (d / rel).is_file():
            return origin, d / rel
    raise FileNotFoundError(f'no original for {rel} in decrypted/patch or decrypted/app')


def zip_dir(src, zpath, arc_root):
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob('*')):
            if p.is_file():
                z.write(p, p.relative_to(arc_root))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('version')
    ap.add_argument('--no-build', action='store_true', help='package build/ as it is')
    a = ap.parse_args()
    xdelta = find_xdelta()

    # 1. build from the pristine game files
    if not a.no_build:
        if BUILD.exists():
            shutil.rmtree(BUILD)
        run(sys.executable, '-P', '-X', 'utf8', ROOT / 'tools/build_text.py', 'build', '--out', BUILD)
        run(sys.executable, '-P', ROOT / 'tools/build_images.py', '--out', BUILD)
        sys.path.insert(0, str(ROOT / 'tools'))
        from build_movies import FFMPEG
        ff = os.environ.get('FFMPEG', FFMPEG)
        if Path(ff).is_file() or shutil.which(ff):
            run(sys.executable, '-P', ROOT / 'tools/build_movies.py', '--out', BUILD, '--ffmpeg', ff)
        else:
            print(f'skipping movie subtitles: ffmpeg not found ({ff}); set FFMPEG=<path to ffmpeg.exe>')
    files = sorted(p for p in BUILD.rglob('*') if p.is_file())
    if not files:
        sys.exit(f'nothing built in {BUILD}')

    # 2. xdelta: original -> patched, one patch per changed file
    out = ROOT / 'release' / f'{NAME}-{a.version}'
    if out.exists():
        shutil.rmtree(out)
    (out / 'patches').mkdir(parents=True)
    lines, manifest, skipped = [], [], []
    for dst in files:
        rel = dst.relative_to(BUILD).as_posix()
        origin, src = original(rel)
        src_sha, dst_sha = sha1(src), sha1(dst)
        if src_sha == dst_sha:
            skipped.append(rel)
            continue
        patch = out / 'patches' / (rel + '.xdelta')
        patch.parent.mkdir(parents=True, exist_ok=True)
        # -S none: no secondary (LZMA) compression and -A: no app header, so the web patcher's small VCDIFF
        # decoder (docs/patcher/vcdiff.js) reads the same files that desktop xdelta tools apply
        run(xdelta, '-e', '-9', '-S', 'none', '-A', '-f', '-s', src, dst, patch)
        check = out / 'verify.tmp'      # round trip: the patch must recreate our file exactly
        run(xdelta, '-d', '-f', '-s', src, patch, check)
        ok = sha1(check) == dst_sha
        check.unlink()
        assert ok, f'{rel}: applying the patch does not reproduce {dst}'
        target = f'rePatch/{TID}/{rel}'
        lines.append(f'{rel}  [{origin}] {src_sha} -> ux0:{target} {dst_sha}')
        manifest.append({'patch': rel + '.xdelta',
                         'source': {'path': rel, 'origin': origin, 'size': src.stat().st_size, 'sha1': src_sha},
                         'target': {'path': target, 'size': dst.stat().st_size, 'sha1': dst_sha}})
    man = {'version': a.version, 'titleId': TID, 'gameVersion': '1.02', 'files': manifest}
    (out / 'patches/manifest.json').write_text(json.dumps(man, indent=1) + '\n', encoding='utf-8')
    (out / 'checksums.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (out / 'tools').mkdir()
    for p in PLAYER_TOOLS:
        shutil.copy(p, out / 'tools' / p.name)
    shutil.copy(ROOT / 'README.md', out / 'README.md')

    # 3. web patcher copy
    if WEB.exists():
        shutil.rmtree(WEB)
    shutil.copytree(out / 'patches', WEB)

    # 4. zips
    zpath = out.parent / (out.name + '.zip')
    zip_dir(out, zpath, out.parent)
    local = out.parent / f'{out.name}-rePatch-LOCAL-ONLY.zip'
    zip_dir(BUILD, local, BUILD.parent.parent)          # rePatch/PCSG00675/...

    psize = sum(p.stat().st_size for p in (out / 'patches').rglob('*.xdelta'))
    print(f'\n{len(manifest)} patches ({psize:,} bytes), {len(skipped)} unchanged files skipped')
    for s in skipped:
        print('  unchanged:', s)
    print(f'wrote {zpath} ({zpath.stat().st_size:,} bytes)')
    print(f'wrote {local} ({local.stat().st_size:,} bytes)  <- game data, for local testing only')
    print(f'web patcher files in {WEB.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
