"""Show the game's name in English on the home screen (optional).

Usage: rename_title.py <app.db | param.sfo> [--restore]

Real Vita: the home screen and LiveArea take the name from the system's app database, ur0:shell/db/app.db,
which is filled in when the game is installed (param.sfo is not read again, and rePatch does not apply to
the system software). Copy app.db to the PC, run this on it, copy it back and restart the Vita.
Changed: the tbl_appinfo rows and tbl_appinfo_icon.title of PCSG00675 that still hold the Japanese title
(仮面ライダー バトライド・ウォー 創生) or short title (バトライド 創生). Nothing else in the database is touched.

A param.sfo (sce_sys/param.sfo) is also accepted: its TITLE/STITLE fields are changed.

A copy of the original is kept next to the file (<name>.orig) on the first run; --restore puts it back.
"""
import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_sfo import set_strings, VALUES, TITLE, STITLE

TITLE_ID = 'PCSG00675'
JA = {'仮面ライダー バトライド・ウォー 創生': TITLE, 'バトライド 創生': STITLE}


def rename_db(path):
    db = sqlite3.connect(path)
    n = 0
    try:
        with db:
            for old, new in JA.items():
                n += db.execute('UPDATE tbl_appinfo SET val=? WHERE titleId=? AND val=?',
                                (new, TITLE_ID, old)).rowcount
                n += db.execute('UPDATE tbl_appinfo_icon SET title=? WHERE titleId=? AND title=?',
                                (new, TITLE_ID, old)).rowcount
        ok = db.execute('pragma integrity_check').fetchone()[0]
    finally:
        db.close()
    assert ok == 'ok', f'database check failed: {ok}'
    return n


def rename_sfo(path):
    p = Path(path)
    old = p.read_bytes()
    out = set_strings(old, VALUES)
    p.write_bytes(out)
    return int(out != old)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('file', help='app.db (ur0:shell/db/app.db) or param.sfo')
    ap.add_argument('--restore', action='store_true', help='put back the original file saved on the first run')
    a = ap.parse_args()
    p = Path(a.file)
    orig = p.with_name(p.name + '.orig')
    if a.restore:
        if not orig.exists():
            sys.exit(f'no {orig.name} next to {p.name}: nothing to restore')
        shutil.copyfile(orig, p)
        print(f'restored {p} from {orig.name}')
        return
    head = p.read_bytes()[:16]
    is_db = head == b'SQLite format 3\0'
    if not is_db and head[:4] != b'\0PSF':
        sys.exit(f'{p.name} is neither app.db nor param.sfo')
    if not orig.exists():
        shutil.copyfile(p, orig)
        print(f'saved the original as {orig.name}')
    n = rename_db(p) if is_db else rename_sfo(p)
    if n:
        print(f'{p.name}: game name set to "{TITLE}" ({n} {"entries" if is_db else "file"} changed)')
    else:
        print(f'{p.name}: nothing to change (already English, or {TITLE_ID} is not in this file)')


if __name__ == '__main__':
    main()
