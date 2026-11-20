"""Replace Japanese text in UI textures with English.

Usage: python -P tools/build_images.py [--out build/rePatch/PCSG00675] [--preview DIR]

Run after build_text.py: archives already in the output folder are patched further, others are read from the
game (1.02 first). Only the DXT blocks inside the edited rectangles are re-encoded.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
import fpk
import gxt
from build_text import ROOT, game_file

FONTS = Path('C:/Windows/Fonts')

# ---------------------------------------------------------------- mission cut-ins (ui/action.fpk)
# The objective is one 564x48 strip drawn as two sprites (SSAD 0063): text_L (220,4)-(504,52), then
# text_R (216,56)-(496,104) of each 512x256 cut-in texture.
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


def fire_text(text, size, height=48, max_width=None, font='impact.ttf', slant=0.18):
    """Bold italic text with a yellow-orange gradient, dark red outline and orange glow (cut-in style)."""
    f = ImageFont.truetype(str(FONTS / font), size)
    pad = 10
    l, t, r, b = f.getbbox(text)
    w, h = r - l + 2 * pad + int(size * slant), height
    mask = Image.new('L', (w, h))
    ImageDraw.Draw(mask).text((pad - l, (h - (b - t)) // 2 - t), text, font=f, fill=255)
    # slant (italic)
    mask = mask.transform(mask.size, Image.AFFINE, (1, slant, -slant * h / 2 - 2, 0, 1, 0), Image.BICUBIC)
    stroke = mask.filter(ImageFilter.MaxFilter(3))
    glow = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(3))
    grad = Image.new('RGBA', (w, h))
    gd = ImageDraw.Draw(grad)
    top, bot = (255, 250, 150), (255, 110, 10)
    for y in range(h):
        k = min(1.0, max(0.0, (y - h * 0.25) / (h * 0.5)))
        gd.line([(0, y), (w, y)], fill=tuple(int(a + (c - a) * k) for a, c in zip(top, bot)) + (255,))
    img = Image.new('RGBA', (w, h))
    img.paste((255, 90, 0, 255), (0, 0), glow.point(lambda v: int(v * 0.85)))
    img.paste((120, 10, 0, 255), (0, 0), stroke)
    img.paste(grad, (0, 0), mask)
    bbox = img.getchannel('A').getbbox()
    img = img.crop((bbox[0], 0, bbox[2], h))
    if max_width and img.width > max_width:
        img = img.resize((max_width, h), Image.LANCZOS)
    return img


def cutin_strip(text):
    total = (CUTIN_L[2] - CUTIN_L[0]) + (CUTIN_R[2] - CUTIN_R[0])
    t = fire_text(text, 34, 48, max_width=total - 8)
    strip = Image.new('RGBA', (total, 48))
    strip.alpha_composite(t, ((total - t.width) // 2, 0))
    return strip


def paste_cutin(img, text):
    strip = cutin_strip(text)
    lw = CUTIN_L[2] - CUTIN_L[0]
    for box, part in ((CUTIN_L, strip.crop((0, 0, lw, 48))), (CUTIN_R, strip.crop((lw, 0, strip.width, 48)))):
        img.paste((0, 0, 0, 0), box)
        img.alpha_composite(part, box[:2])
    return [CUTIN_L, CUTIN_R]


# ---------------------------------------------------------------- texture patching
def encode_blocks(img, t, raw, boxes):
    """Re-encode the 4x4 blocks covering boxes; returns new raw (swizzled) texture data."""
    from dxt import encode_dxt5_block, encode_dxt1_block
    f = gxt.fmt_name(t)
    bw, bh, unit, _ = gxt.layout(t)
    lin = bytearray(gxt.unswizzle(raw, bw, bh, unit))
    px = img.load()
    enc = encode_dxt5_block if f == 'UBC3' else encode_dxt1_block
    for box in boxes:
        for by in range(box[1] // 4, (box[3] + 3) // 4):
            for bx in range(box[0] // 4, (box[2] + 3) // 4):
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
    new = encode_blocks(img, t, raw, boxes)
    out = bytearray(data)
    out[t['off']:t['off'] + t['size']] = new
    return bytes(out), img


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, default=ROOT / 'build/rePatch/PCSG00675')
    ap.add_argument('--preview', type=Path, help='also save edited textures as PNG here')
    a = ap.parse_args()
    rel = 'nativeVITA/_fpk/ui/action.fpk'
    dst = a.out / rel
    f = fpk.Fpk((dst if dst.is_file() else game_file(rel)).read_bytes())
    for i, text in CUTINS.items():
        data, img = patch_gxt(f.entries[i].content(), lambda im, text=text: paste_cutin(im, text))
        f.set_content(i, data)
        if a.preview:
            a.preview.mkdir(parents=True, exist_ok=True)
            img.save(a.preview / f'action_{i:04d}.png')
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(f.build())
    print(f'{rel}: {len(CUTINS)} mission cut-ins')


if __name__ == '__main__':
    main()
