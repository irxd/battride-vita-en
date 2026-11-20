"""Replace Japanese text in UI textures with English.

Usage: python -P tools/build_images.py [--out build/rePatch/PCSG00675] [--preview DIR]

Archives are always read from the game (1.02 first), so the script can be rerun; build_text.py does not write
any of these archives. Each edit clears a sprite rectangle and draws the English text into it; only the DXT blocks
touching edited rectangles are re-encoded. Rectangles come from the SpriteStudio layouts (SSAD part AREAs) or,
where several sprites share a grid, from the measured glyph rows.
"""
import argparse
import sys
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import fpk
import gxt
from build_text import ROOT, game_file

FONTS = Path('C:/Windows/Fonts')
MIN_SQUEEZE = 0.7      # narrowest horizontal squeeze before text is scaled down instead


# ---------------------------------------------------------------- text rendering
@dataclass(frozen=True)
class Style:
    font: str = 'arialbd.ttf'
    size: int = 14
    fill: tuple = (255, 255, 255)          # colour, or (top, bottom) gradient
    outline: tuple = None                  # colour
    ow: int = 0                            # outline width
    outline2: tuple = None                 # second (outer) outline colour
    ow2: int = 0
    glow: tuple = None                     # colour
    gr: float = 0                          # glow radius
    glow_alpha: float = 1.0
    shadow: tuple = None                   # (dx, dy, colour)
    slant: float = 0.0
    align: str = 'center'                  # center | left
    indent: int = 2
    bg: tuple = None                       # fill the region with this colour instead of clearing it
    spacing: int = 0                       # extra line spacing for multi-line text
    smallcaps: float = 0                   # >0: lowercase letters drawn as capitals at this scale


def _runs(line, st):
    """[(text, font)] for one line (small caps split into big/small runs)."""
    big = ImageFont.truetype(str(FONTS / st.font), st.size)
    if not st.smallcaps:
        return [(line, big)]
    small = ImageFont.truetype(str(FONTS / st.font), round(st.size * st.smallcaps))
    out = []
    for ch in line:
        f = small if ch.islower() else big
        c = ch.upper()
        if out and out[-1][1] is f:
            out[-1] = (out[-1][0] + c, f)
        else:
            out.append((c, f))
    return out


def _gradient(size, top, bottom, y0=0.25, y1=0.75):
    w, h = size
    g = Image.new('RGBA', size)
    d = ImageDraw.Draw(g)
    for y in range(h):
        k = min(1.0, max(0.0, (y / max(1, h - 1) - y0) / (y1 - y0)))
        d.line([(0, y), (w, y)], fill=tuple(int(a + (c - a) * k) for a, c in zip(top, bottom)) + (255,))
    return g


def render(text, st):
    f = ImageFont.truetype(str(FONTS / st.font), st.size)
    pad = max(st.ow, st.ow2) + int(st.gr * 2) + 4
    lines = [_runs(l, st) for l in text.split('\n')]
    asc, desc = f.getmetrics()
    lh = asc + desc + st.spacing
    widths = [sum(fo.getlength(t) for t, fo in runs) for runs in lines]
    w = int(max(widths)) + 2 * pad + int(st.size * st.slant) + 2
    h = lh * len(lines) + 2 * pad
    mask = Image.new('L', (w, h))
    d = ImageDraw.Draw(mask)
    for i, (runs, lw) in enumerate(zip(lines, widths)):
        x = pad if st.align == 'left' else pad + (max(widths) - lw) / 2
        for t, fo in runs:
            d.text((x, pad + i * lh + asc), t, font=fo, fill=255, anchor='ls')
            x += fo.getlength(t)
    if st.slant:
        mask = mask.transform(mask.size, Image.AFFINE, (1, st.slant, -st.slant * h / 2, 0, 1, 0), Image.BICUBIC)
    img = Image.new('RGBA', (w, h))
    if st.glow:
        g = mask.filter(ImageFilter.MaxFilter(2 * st.ow + 1)) if st.ow else mask
        g = g.filter(ImageFilter.GaussianBlur(st.gr)).point(lambda v: min(255, int(v * 2 * st.glow_alpha)))
        img.paste(st.glow + (255,), (0, 0), g)
    if st.shadow:
        dx, dy, col = st.shadow
        sh = Image.new('L', (w, h))
        sh.paste(mask, (dx, dy))
        img.paste(col + (255,), (0, 0), sh)
    if st.outline2 and st.ow2:
        img.paste(st.outline2 + (255,), (0, 0), mask.filter(ImageFilter.MaxFilter(2 * st.ow2 + 1)))
    if st.outline and st.ow:
        img.paste(st.outline + (255,), (0, 0), mask.filter(ImageFilter.MaxFilter(2 * st.ow + 1)))
    if isinstance(st.fill[0], tuple):
        top = mask.getbbox() or (0, 0, w, h)
        grad = Image.new('RGBA', (w, h))
        grad.paste(_gradient((w, top[3] - top[1]), *st.fill), (0, top[1]))
        img.paste(grad, (0, 0), mask)
    else:
        img.paste(st.fill + (255,), (0, 0), mask)
    bb = img.getchannel('A').getbbox()
    return img.crop(bb) if bb else img


def place(img, region, text, st, valign=None):
    """Clear region and draw text into it (squeezed horizontally to fit)."""
    x0, y0, x1, y1 = region
    if st.bg:
        img.paste(st.bg + (255,), region)
    else:
        img.paste((0, 0, 0, 0), region)
    s = render(text, st)
    maxw, maxh = x1 - x0, y1 - y0
    if s.width > maxw:
        r = maxw / s.width
        if r < MIN_SQUEEZE:     # too long: shrink uniformly first, then squeeze
            k = r / MIN_SQUEEZE
            s = s.resize((max(1, round(s.width * k)), max(1, round(s.height * k))), Image.LANCZOS)
        s = s.resize((maxw, s.height), Image.LANCZOS)
    if s.height > maxh:
        s = s.crop((0, (s.height - maxh) // 2, s.width, (s.height - maxh) // 2 + maxh))
    x = x0 + st.indent if st.align == 'left' else x0 + (maxw - s.width) // 2
    x = min(x, x1 - s.width)
    y = y0 + (maxh - s.height) // 2 if valign is None else y0 + valign
    layer = Image.new('RGBA', img.size)
    layer.paste(s, (x, y))
    img.alpha_composite(layer.crop(region), region[:2])


# ---------------------------------------------------------------- styles
FIRE = Style(font='impact.ttf', size=34, fill=((255, 250, 150), (255, 110, 10)), outline=(120, 10, 0), ow=1,
             glow=(255, 90, 0), gr=3, glow_alpha=0.85, slant=0.18)
HEADER = Style(font='arialbi.ttf', size=17, fill=(255, 255, 255), outline=(110, 0, 0), ow=2, glow=(220, 0, 0),
               gr=2, glow_alpha=0.7, align='left', indent=4)
MENU_SEL = Style(font='arialbd.ttf', size=14, fill=(255, 255, 255), outline=(110, 0, 0), ow=1, glow=(220, 0, 0),
                 gr=2, glow_alpha=0.4)
MENU = Style(font='arialbd.ttf', size=14, fill=(255, 255, 255), shadow=(1, 1, (0, 0, 0)))
BIG_SEL = replace(MENU_SEL, size=19)
BIG = replace(MENU, size=19)
OPTION = Style(font='arialbd.ttf', size=15, fill=((255, 240, 150), (215, 160, 40)), outline=(10, 10, 10), ow=1,
               align='left', indent=1, slant=0.12)
ORANGE_TAG = Style(font='arialbd.ttf', size=12, fill=(255, 150, 40), outline=(120, 0, 0), ow=1, glow=(220, 30, 0),
                   gr=1, glow_alpha=0.6)
YES_GLOW = Style(font='arialbd.ttf', size=21, fill=(255, 255, 255), glow=(230, 0, 0), gr=2.5, glow_alpha=0.6,
                 align='left', indent=4)
YES_RED = Style(font='arialbd.ttf', size=21, fill=(255, 255, 255), outline=(235, 0, 0), ow=1, glow=(255, 0, 0),
                gr=2.5, glow_alpha=0.35, align='left', indent=4)


# ---------------------------------------------------------------- edits
# mission cut-ins (ui/action.fpk): the objective is one 564x48 strip drawn as two sprites (SSAD 0063): text_L
# (220,4)-(504,52), then text_R (216,56)-(496,104) of each 512x256 cut-in texture.
CUTIN_L, CUTIN_R = (220, 4, 504, 52), (216, 56, 496, 104)
CUTINS = {
    64: 'Race Through the Battlefield and Face G3-X',
    65: 'Defeat the Knight Clones',
    66: 'Smoke Out Kaixa',
    67: 'Pursue Garren',
    68: 'Find Ibuki',
    69: 'Overcome Clock Up',
    70: 'Rush to Where Zeronos Appears',
    71: 'Advance to IXA',
    72: 'Corner Diend',
    73: 'Pursue Accel',
    74: "Stop Birth's Medal Hunt",
    75: 'Drag Out Meteor',
    76: 'Beast: Charging Magic',
    77: 'Advance to Baron',
    78: 'Defeat the Leader and Drag Out Zangetsu Shin',
    79: 'Prepare to Fight Kuuga',
    80: "Overcome Agito's Trial",
    81: "Beware Ryuki's Ambush",
    82: 'Defeat the Enemies and Fight Faiz',
    83: 'Pursue Blade',
    84: 'Find Hibiki',
    85: 'Reach Kabuto!',
    86: 'Defeat the Ever-Changing Den-O',
    87: 'Beware the Fangire Souls',
    88: 'Advance to Decade',
    89: 'Pursue Joker',
    90: "Defeat All of OOO's Combos",
    91: 'Fight Fourze',
    92: 'Defeat Every Wizard',
    93: "Wear Down Baron's Forces",
    94: 'Beat Down Shocker',
    95: 'Rescue No. 1',
    96: 'Defeat the Destron Army',
    97: "Go to V3's Aid",
    98: 'Defeat All the Spider Kaijin',
    99: "Go to BLACK's Aid",
    100: 'Defeat Zu-Gooma-Gu',
    101: "Go to Kuuga's Aid",
    102: 'Defeat Jaguar Lord',
    103: "Go to Agito's Aid",
    104: 'Defeat the Attacking Enemies',
    105: "Go to Decade's Aid",
    106: 'Escape the Research Facility',
    107: "Go to W's Aid",
    108: 'Defeat All the Roidmudes',
    109: "Go to Drive's Aid",
    110: 'Repel Shadow Moon',
    111: 'Defeat R Nasca Dopant',
    112: 'Defeat Kazari',
    113: 'Defeat Libra Zodiarts',
    114: 'Defeat the White Wizard',
    115: 'Defeat Lord Baron',
    116: 'Defeat Heart Roidmude',
    117: 'Defeat Red Shadow Moon',
}


def cutin(text):
    def edit(img):
        total = (CUTIN_L[2] - CUTIN_L[0]) + (CUTIN_R[2] - CUTIN_R[0])
        strip = Image.new('RGBA', (total, 48))
        place(strip, (4, 0, total - 4, 48), text, FIRE)
        lw = CUTIN_L[2] - CUTIN_L[0]
        for box, part in ((CUTIN_L, strip.crop((0, 0, lw, 48))), (CUTIN_R, strip.crop((lw, 0, total, 48)))):
            img.paste((0, 0, 0, 0), box)
            img.alpha_composite(part, box[:2])
        return [CUTIN_L, CUTIN_R]
    return edit


def labels(*items):
    """items: (region, text, style)"""
    def edit(img):
        for region, text, st in items:
            place(img, region, text, st)
        return [r for r, _, _ in items]
    return edit


NOTICE_TITLE = Style(font='arialbd.ttf', size=19, fill=(205, 45, 25), bg=(239, 239, 239))
NOTICE_BODY = Style(font='arial.ttf', size=14, fill=(70, 70, 70), bg=(239, 239, 239), align='left', indent=0,
                    spacing=3)


def notice(img):
    place(img, (96, 144, 416, 176), 'Notice', NOTICE_TITLE)
    place(img, (104, 180, 412, 368),
          'Distributing this game software over the\n'
          'internet without permission from the\n'
          'copyright holder, or knowingly downloading\n'
          'an illegally distributed copy, is strictly\n'
          'prohibited by law.\n'
          '\n'
          'Thank you for your understanding\n'
          'and cooperation.', NOTICE_BODY)
    return [(96, 144, 416, 368)]


def grid(x0, y0, w, h, names, st):
    """names: rows of column texts (None = leave)."""
    out = []
    for r, row in enumerate(names):
        for c, text in enumerate(row):
            if text:
                out.append(((x0 + c * w, y0 + r * h, x0 + (c + 1) * w, y0 + (r + 1) * h), text, st))
    return out


# rider name plates (ui/menu.fpk 0091-0151, 256x128): name sprite (0,0)-(256,52) (SSAD menu/0071 'name')
PLATE = Style(font='timesbi.ttf', size=40, fill=((70, 70, 70), (20, 20, 20)), outline=(235, 235, 225), ow=2,
              outline2=(30, 30, 30), ow2=3, smallcaps=0.78)
PLATES = {
    91: 'Accel', 92: 'Agito', 93: 'Amazon', 94: 'Autovajin', 95: 'Birth', 96: 'Blade', 98: 'Baron', 100: 'Beast',
    101: 'Chaser', 102: 'Chaser', 103: 'Decade', 104: 'Decade Violent Emotion', 105: 'Diend', 106: 'Den-O',
    107: 'Dark Kiva', 108: 'Drive', 109: 'Eternal', 110: 'Faiz', 111: 'FangJoker', 112: 'Fourze', 114: 'Gaim',
    115: 'Gatack', 116: 'Toucon Boost', 117: 'Ghost', 118: 'Garren', 119: 'Hibiki', 120: 'Ibuki',
    121: 'IXA (Nago)', 122: 'IXA', 123: 'Kabuto', 124: 'Kuuga (Yusuke)', 125: 'Kiva', 126: 'Kaixa', 127: 'Knight',
    128: 'No. 1', 129: 'No. 2', 132: 'Kuuga', 134: 'Mach', 135: 'Meteor', 136: 'New Den-O', 137: 'OOO',
    138: 'Ryugen', 139: 'Riderman', 140: 'Ryuki', 141: 'Skull', 142: 'Skyrider', 143: 'Specter', 144: 'Super-1',
    145: 'Stronger', 146: 'Takeshi Hongo (Disguised)', 148: 'Wizard', 149: 'Joker', 150: 'Zeronos',
    151: 'Zangetsu Shin',
}

# battle HUD (ui/action.fpk): boxes are the measured glyph boxes (or SSAD rows where known)
KO_BIG = Style(font='impact.ttf', size=40, fill=((255, 245, 230), (240, 130, 80)), outline=(60, 20, 10), ow=2,
               slant=0.12)
KO_GOLD = Style(font='impact.ttf', size=40, fill=((255, 250, 180), (230, 170, 30)), outline=(90, 50, 0), ow=1,
                glow=(255, 220, 60), gr=2.5, glow_alpha=0.6, slant=0.12)
CLEAR_RED = Style(font='impact.ttf', size=38, fill=((255, 210, 60), (230, 40, 10)), outline=(255, 230, 120), ow=1,
                  slant=0.12)
HUD = Style(font='arialbd.ttf', size=13, fill=((255, 255, 255), (200, 200, 200)), outline=(30, 20, 10), ow=1)
HUD_GOLD = replace(HUD, fill=((255, 255, 230), (240, 200, 90)), slant=0.1)
STAT = Style(font='arialbd.ttf', size=13, fill=(240, 160, 40), outline=(40, 15, 0), ow=1)
STAT_OFF = replace(STAT, fill=(115, 95, 65))
SKILL = Style(font='arialbd.ttf', size=12, fill=(255, 130, 235), outline=(70, 0, 60), ow=1)
SKILL_OFF = replace(SKILL, fill=(125, 125, 125), outline=(35, 35, 35))
HUD_ROWS = ['Side Basshaa', 'Riders Defeated', 'Transcend!', 'Crimson Gauge', 'Beast Magic', 'Mirror World Gate',
            'Collecting Cell Medals', 'Key Item', 'Restricted']
HUD_EDITS = {
    153: labels(((0, 0, 134, 50), 'Defeated!', KO_BIG), ((0, 50, 134, 100), 'Defeated!', KO_GOLD)),
    154: labels(((0, 112, 118, 160), 'Clear!', CLEAR_RED), ((0, 162, 118, 210), 'Clear!', KO_GOLD),
                ((176, 188, 206, 206), 'Now', HUD_GOLD), ((144, 210, 206, 231), 'to go!!', HUD_GOLD),
                ((144, 232, 206, 255), 'down!', HUD_GOLD)),
    155: labels(*grid(0, 276, 116, 20, [[t] for t in HUD_ROWS], HUD),
                ((200, 224, 236, 244), 'Now', HUD), ((200, 244, 236, 264), 'Left', HUD),
                ((1, 256, 31, 275), 'Body', STAT), ((33, 256, 62, 275), 'Body', STAT_OFF),
                ((63, 256, 95, 275), 'Mind', STAT), ((97, 256, 126, 275), 'Mind', STAT_OFF),
                ((128, 256, 159, 275), 'Sense', STAT), ((161, 256, 190, 275), 'Sense', STAT_OFF),
                *grid(145, 348, 31, 16, [['SPD', 'SP'], ['FIN', 'GRD']], SKILL),
                *grid(145, 380, 31, 16, [['SPD', 'SP'], ['FIN', 'GRD']], SKILL_OFF)),
    157: labels(((126, 35, 252, 56), 'Shop Points Earned', HUD)),
}

# main menu (ui/menu.fpk 0352): two columns of items (plain / highlighted), header 'Title' (408,536)-(560,568)
MAIN = Style(font='arialbd.ttf', size=16, fill=(255, 255, 255), shadow=(2, 2, (120, 0, 10)), outline=(60, 0, 0),
             ow=1)
MAIN_SEL = Style(font='arialbd.ttf', size=16, fill=(255, 255, 255), glow=(255, 255, 255), gr=1.5, glow_alpha=0.45)
MAIN_TITLE = Style(font='arialbi.ttf', size=24, fill=(255, 255, 255), shadow=(2, 2, (150, 0, 0)), outline=(90, 0, 0),
                   ow=1, glow=(230, 0, 0), gr=2.5, glow_alpha=0.6)
MAIN_ITEMS = ['Story Mode', 'Time Survival', 'Free Mission', 'Custom Soundtrack', 'Contents', 'Options']

PAUSE = [['Bonus Settings', 'Shop'], ['Custom Soundtrack', 'View Cards'], ['Skills', 'Move List'],
         ['Forms', 'View Skills'], ['Cards', 'Game Settings'], ['Change Figure', 'Buy Voices'], ['Buy BGM', None]]

EDITS = {
    'nativeVITA/_fpk/ui/action.fpk': {**{i: cutin(t) for i, t in CUTINS.items()}, **HUD_EDITS},
    'nativeVITA/_fpk/ui/title.fpk': {4: notice},
    'nativeVITA/_fpk/ui/common.fpk': {
        # yes/no: highlighted (glow) and plain (outline) versions; SSAD 0011 Yes (0,40,60,68), 0010 No (0,112,80,144)
        16: labels(((0, 0, 64, 36), 'Yes', YES_GLOW), ((0, 36, 64, 72), 'Yes', YES_RED),
                   ((0, 72, 84, 108), 'No', YES_GLOW), ((0, 108, 84, 146), 'No', YES_RED)),
        # screen headers: two columns of 144x24 cells (SSAD Mess_1 (0,44,144,68) ...)
        83: labels(*grid(0, 44, 144, 24, [['Story Mode', 'Sound Gallery'], ['Time Survival', 'Rankings'],
                                          ['Free Mission', 'Custom Soundtrack'], ['Rider Select', 'Settings'],
                                          ['Tag Select', 'Move List'], ['Shop', 'Skills']], HEADER),
                   *grid(0, 212, 144, 24, [['Change Figure', 'Forms'], ['Buy BGM', 'Card Set'],
                                           ['Buy Voices', 'Pause Menu']], HEADER),
                   ((0, 308, 144, 334), 'Figure Viewer', HEADER)),
    },
    'nativeVITA/_fpk/ui/menu.fpk': {
        **{i: labels(((0, 0, 256, 52), t, PLATE)) for i, t in PLATES.items()},
        # ranking record labels: 72x20 rows from (160,176) (SSAD menu/0299 TxMaxG)
        306: labels(*grid(160, 176, 72, 20, [['Total KOs'], ['Total Combos'], ['Total Sorties'], ['Level']],
                          replace(HUD, size=14, fill=((255, 255, 255), (170, 170, 175)), outline=(20, 20, 25)))),
        352: labels(*grid(410, 379, 132, 20, [[t, None] for t in MAIN_ITEMS], MAIN),
                    *grid(542, 379, 132, 20, [[t] for t in MAIN_ITEMS], MAIN_SEL),
                    ((408, 536, 560, 568), 'Main Menu', MAIN_TITLE)),
        # options menu labels (measured glyph boxes; icons sit right of the first two)
        369: labels(((0, 0, 100, 22), 'Difficulty', OPTION), ((0, 22, 100, 40), 'Save/Load', OPTION),
                    ((0, 42, 145, 60), 'Custom Soundtrack', OPTION), ((146, 42, 220, 60), 'Options', OPTION),
                    ((0, 62, 59, 80), 'Controls', OPTION), ((60, 62, 133, 80), 'Camera', OPTION),
                    ((134, 62, 216, 80), 'Sound', OPTION),
                    ((0, 82, 70, 100), 'Game Settings', OPTION), ((71, 82, 144, 100), 'Gallery', OPTION)),
    },
    'nativeVITA/_fpk/ui/texture/menu.fpk': {
        5: labels(((232, 52, 380, 76), 'Quit Mission', BIG_SEL), ((232, 76, 380, 100), 'Quit Mission', BIG),
                  ((232, 160, 380, 184), 'Start Mission', BIG_SEL), ((232, 184, 380, 208), 'Start Mission', BIG),
                  ((444, 280, 512, 296), 'Voice/BGM', MENU), ((444, 296, 512, 312), 'Figures', MENU),
                  ((444, 312, 512, 328), 'All Items', MENU),
                  ((452, 112, 512, 134), 'Changeable', ORANGE_TAG), ((452, 136, 512, 158), 'New Items', ORANGE_TAG),
                  *grid(0, 364, 120, 20, PAUSE, MENU_SEL), *grid(242, 364, 120, 20, PAUSE, MENU)),
    },
}


# ---------------------------------------------------------------- texture patching
def encode_blocks(img, t, raw, boxes):
    """Re-encode the 4x4 blocks covering boxes; returns new raw (swizzled) texture data."""
    from dxt import encode_dxt5_block, encode_dxt1_block
    bw, bh, unit, _ = gxt.layout(t)
    lin = bytearray(gxt.unswizzle(raw, bw, bh, unit))
    px = img.load()
    enc = encode_dxt5_block if gxt.fmt_name(t) == 'UBC3' else encode_dxt1_block
    done = set()
    for box in boxes:
        for by in range(max(0, box[1] // 4), min(bh, (box[3] + 3) // 4)):
            for bx in range(max(0, box[0] // 4), min(bw, (box[2] + 3) // 4)):
                if (bx, by) in done:
                    continue
                done.add((bx, by))
                blk = [px[bx * 4 + i % 4, by * 4 + i // 4] for i in range(16)]
                lin[(by * bw + bx) * unit:(by * bw + bx + 1) * unit] = enc(blk)
    return gxt.swizzle(lin, bw, bh, unit, len(raw))


def patch_gxt(data, edit):
    """edit(img) -> list of changed boxes. Single-texture GXT only."""
    g = gxt.parse(data)
    t = g['texs'][0]
    img = gxt.decode(data, t, g)
    boxes = edit(img)
    raw = data[t['off']:t['off'] + t['size']]
    out = bytearray(data)
    out[t['off']:t['off'] + t['size']] = encode_blocks(img, t, raw, boxes)
    return bytes(out), img


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, default=ROOT / 'build/rePatch/PCSG00675')
    ap.add_argument('--preview', type=Path, help='also save edited textures as PNG here')
    ap.add_argument('--only', help='only this archive (substring)')
    a = ap.parse_args()
    for rel, edits in EDITS.items():
        if a.only and a.only not in rel:
            continue
        dst = a.out / rel
        f = fpk.Fpk(game_file(rel).read_bytes())
        for i, edit in edits.items():
            data, img = patch_gxt(f.entries[i].content(), edit)
            f.set_content(i, data)
            if a.preview:
                a.preview.mkdir(parents=True, exist_ok=True)
                img.save(a.preview / f"{rel.split('_fpk/')[1].replace('/', '_')[:-4]}_{i:04d}.png")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(f.build())
        print(f'{rel}: {len(edits)} textures')


if __name__ == '__main__':
    main()
