"""Apply the English translations to every STA string table in the game's FPK2 archives.

    python -P tools/build_text.py build [--out build/rePatch/PCSG00675]
    python -P tools/build_text.py todo <table> [<table> ...]   untranslated lines of string.fpk tables (local use)
    python -P tools/build_text.py stats

Translations live in text/**/*.json as {sha1(Japanese UTF-8)[:10]: English}. No Japanese game text is stored in the
repository. One Japanese line has one English line, wherever it appears (string.fpk, story scenes, battle lines).

English is word-wrapped to the pixel width of the longest line of the Japanese original (font metrics), unless the
translation already has its own line breaks. The build reports lines that may overflow:
  WIDE   a one-line label is wider than the Japanese (fixed-size field: shorten if it overflows on screen)
  LINES  the wrapped English has more lines than the Japanese (box may be too small)
"""
import argparse, hashlib, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fpk, sta, font

ROOT = Path(__file__).resolve().parent.parent
GAME = [ROOT / 'decrypted/patch/PCSG00675', ROOT / 'decrypted/app/PCSG00675']   # 1.02 first
FONT = 'nativeVITA/font/FOT-NewRodinPro-DB.fnt'
JP = re.compile(r'[\u3040-\u30ff\u3400-\u9fff\uff01-\uff5e]')
KEEP = re.compile(r'[\ue000-\ue00f]|%[-+ #0]*\d*(?:\.\d+)?[a-zA-Z]|</?COLOR[^>]*>')   # buttons, printf, colors


def key(text):
    return hashlib.sha1(text.encode('utf8')).hexdigest()[:10]


def game_file(rel):
    for g in GAME:
        if (g / rel).is_file():
            return g / rel
    raise FileNotFoundError(rel)


def archives():
    """Every FPK2 archive (relative path), 1.02 versions replacing 1.00."""
    seen = {}
    for g in reversed(GAME):
        for p in (g / 'nativeVITA').rglob('*.fpk'):
            seen[p.relative_to(g).as_posix()] = p
    return dict(sorted(seen.items()))


def load_translations():
    tr, where = {}, {}
    for p in sorted((ROOT / 'text').rglob('*.json')):
        for k, v in json.loads(p.read_text(encoding='utf8')).items():
            if k in tr and tr[k] != v:
                print(f'warning: {k} has different English in {where[k]} and {p.name}')
                continue
            tr[k], where[k] = v, p.name
    return tr


TAG = re.compile(r'</?COLOR[^>]*>')
FIRST_MISSION_TABLE = 55          # string.fpk tables from here on are mission dialogue and banners
DIALOG_WIDTH, DIALOG_LINES = 325, 2
SPOKEN = re.compile('[。！？…」）]')   # spoken lines end like 。！？…」） ; banners don't


def width(fnt, line):
    return fnt.width(TAG.sub('', line))


def wrap(text, limit, fnt):
    """Greedy word wrap of each paragraph to `limit` pixels."""
    out = []
    for para in text.split('\n'):
        indent = para[:len(para) - len(para.lstrip('　'))]   # continuation lines keep a full-width indent
        line = ''
        for word in para.split(' '):
            cand = word if not line else line + ' ' + word
            if line and width(fnt, cand) > limit:
                out.append(line)
                line = indent + word
            else:
                line = cand
        out.append(line)
    return '\n'.join(out)


class Builder:
    def __init__(self, tr, fnt):
        self.tr, self.fnt = tr, fnt
        self.used, self.issues, self.done, self.total = set(), {}, set(), set()
        self.brief = None     # (width, lines) of the mission briefing box, set by build()

    def measure_briefings(self, string_fpk):
        """Mission briefings: strings of 3+ lines in the mission tables of string.fpk."""
        f = fpk.Fpk(string_fpk.read_bytes())
        briefs = [s.rstrip('\n').split('\n') for e in f.entries[FIRST_MISSION_TABLE:] for s in sta.read(e.content())
                  if JP.search(s) and s.count('\n') >= DIALOG_LINES]
        if briefs:
            self.brief = (max(width(self.fnt, l) for b in briefs for l in b), max(len(b) for b in briefs))

    def english(self, jp, where, box=0, box_lines=0, dialog=False):
        if not JP.search(jp):
            return jp
        self.total.add(jp)
        en = self.tr.get(key(jp))
        if en is None:
            return jp
        self.used.add(key(jp))
        self.done.add(jp)
        if '%' not in jp:
            en = en.replace('%', '％')   # the string may go through printf; the Japanese uses full-width too
        if sorted(KEEP.findall(en)) != sorted(KEEP.findall(jp)):
            self.issues.setdefault(jp, (where, 'CODES', f'icons/format codes differ: {KEEP.findall(jp)} -> {KEEP.findall(en)}'))
        if miss := [c for c in self.fnt.missing(en) if c not in jp]:
            self.issues.setdefault(jp, (where, 'GLYPH', f'not in font: {miss}'))
        jp_lines = jp.split('\n')
        limit = max([width(self.fnt, l) for l in jp_lines] + [box if len(jp_lines) > 1 else 0])
        max_lines = max(len(jp_lines), box_lines if len(jp_lines) > 1 else 0)
        if dialog and SPOKEN.search(jp) and len(jp_lines) <= DIALOG_LINES:
            # mission dialogue box (verified in Vita3K): 2 lines of up to ~340 px, whatever the Japanese used
            limit, max_lines = max(limit, DIALOG_WIDTH), DIALOG_LINES
        elif dialog and len(jp_lines) > DIALOG_LINES and self.brief:
            # mission briefings share one box: as wide and tall as the largest Japanese briefing
            limit = max(limit, self.brief[0])
            if '\n\n' in jp:      # only real briefings (paragraphs); other 3+ line texts keep their line count
                max_lines = max(max_lines, self.brief[1])
        if len(jp_lines) > 1 or max_lines > 1:
            en = wrap(en, limit, self.fnt)   # keeps the translation's own line breaks, adds more where too wide
        en_lines = en.split('\n')
        widest = max(width(self.fnt, l) for l in en_lines)
        if max_lines == 1 and len(en_lines) == 1 and widest > limit * 1.05 and widest - limit > 8:
            self.issues.setdefault(jp, (where, 'WIDE', f'{widest:.0f}px vs {limit:.0f}px: {en}'))
        elif len(en_lines) > max_lines:
            self.issues.setdefault(jp, (where, 'LINES', f'{len(en_lines)} lines vs {len(jp_lines)}: {en!r}'))
        return en

    def archive(self, rel, path):
        f = fpk.Fpk(path.read_bytes())
        changed = False
        for i, e in enumerate(f.entries):
            data = e.content()
            if not sta.is_sta(data):
                continue
            strings = sta.read(data)
            # a text box is as wide as the widest line of any multi-line string in the same table
            multi = [s for s in strings if '\n' in s.strip('\n')]
            box = max([width(self.fnt, l) for s in multi for l in s.split('\n')] or [0])
            # large tables of one kind of text (e.g. move descriptions) share one box: its height is the most lines
            box_lines = max(len(s.rstrip('\n').split('\n')) for s in multi) if len(multi) >= 20 else 0
            # mission tables of string.fpk, and the per-character battle line archives (same dialogue box)
            dialog = (rel.endswith('_fpk/string.fpk') and i >= FIRST_MISSION_TABLE) or '/_fpk/chr/' in rel
            new = [self.english(s, f'{rel}#{i}.{j}', box, box_lines, dialog) for j, s in enumerate(strings)]
            if new != strings:
                f.set_content(i, sta.write(new, *[int.from_bytes(data[4:8], 'little')]))
                changed = True
        return f.build() if changed else None


def build(out):
    tr = load_translations()
    fnt = font.english(game_file(FONT).read_bytes())
    b = Builder(tr, fnt)
    b.measure_briefings(game_file('nativeVITA/_fpk/string.fpk'))
    print(f'mission briefing box: {b.brief[0]:.0f} px, {b.brief[1]} lines')
    n = 0
    for rel, path in archives().items():
        data = b.archive(rel, path)
        if data is not None:
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            n += 1
    (out / FONT).parent.mkdir(parents=True, exist_ok=True)
    (out / FONT).write_bytes(bytes(fnt.data))
    unused = set(tr) - b.used
    report = ROOT / 'build/text_report.txt'
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open('w', encoding='utf8') as r:
        for jp, (where, kind, msg) in sorted(b.issues.items(), key=lambda x: (x[1][1], x[1][0])):
            r.write(f'{kind:5s} {key(jp)} {where}: {msg}\n')
    kinds = {}
    for _, kind, _ in b.issues.values():
        kinds[kind] = kinds.get(kind, 0) + 1
    print(f'{n} archives written to {out}')
    print(f'translated {len(b.done)}/{len(b.total)} unique Japanese lines; issues {kinds or "none"} '
          f'(see {report.relative_to(ROOT)})')
    if unused:
        print(f'warning: {len(unused)} translations match no line: {sorted(unused)[:5]}')


def string_tables():
    f = fpk.Fpk(game_file('nativeVITA/_fpk/string.fpk').read_bytes())
    return [sta.read(e.content()) for e in f.entries]


def todo(tables):
    tr = load_translations()
    esc = lambda s: re.sub('[-]', lambda m: f'<{ord(m.group()):04X}>', s).replace('\n', '\\n')
    tabs = string_tables()
    seen = set()
    for t in tables:
        for j, s in enumerate(tabs[t]):
            if JP.search(s) and key(s) not in tr and s not in seen:
                seen.add(s)
                print(f'{t:04d}.{j:03d} {key(s)} {esc(s)}')


def stats():
    tr = load_translations()
    tabs = string_tables()
    total = done = 0
    for t, strings in enumerate(tabs):
        u = {s for s in strings if JP.search(s)}
        d = sum(1 for s in u if key(s) in tr)
        total += len(u); done += d
        if u and d < len(u):
            print(f'{t:04d}: {d}/{len(u)}  {next(iter(u))[:30]!r}'.replace('\n', ' '))
    print(f'string.fpk: {done}/{total} (per-table unique; overlaps counted per table)')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('build'); s.add_argument('--out', type=Path, default=ROOT / 'build/rePatch/PCSG00675')
    s = sub.add_parser('todo'); s.add_argument('tables', type=int, nargs='+')
    sub.add_parser('stats')
    a = ap.parse_args()
    if a.cmd == 'build':
        build(a.out)
    elif a.cmd == 'todo':
        todo(a.tables)
    else:
        stats()


if __name__ == '__main__':
    main()
