"""English subtitles for the movies with burned-in Japanese subtitles.

Usage: python -P tools/build_movies.py [--out build/rePatch/PCSG00675] [--ffmpeg PATH] [--only ID] [--preview DIR]

Cues are in text/movies/<group>_<name>.json (e.g. etc_CHP_000_000.json for nativeVITA/movie/etc/CHP_000_000):

    {"style": "bar" | "msn", "cues": [{"start": s, "end": s, "en": "...", "box": [x0, y0, x1, y1]}, ...]}

"bar" (story chapters): the original draws 'Speaker「line」' on a black bar (solid between y 341-361). Each cue
is a black rectangle with the English over the bar. "msn" (mission movies): small white text with a dark
outline over the picture; "box" is the measured box of the Japanese text, which is covered by a dark rounded
box with the English centred on it. The cue images are overlaid with ffmpeg and the video is re-encoded with
h264_nvenc (the only H.264 encoder that works in the bundled ffmpeg here) to match the originals: Main@3.1,
B-frames, GOP 30, ~1 Mbps, moov first; the audio stream is copied.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from PIL import Image, ImageDraw, ImageFont
from build_text import ROOT, game_file

FFMPEG = r'C:/Users/krism/AppData/Local/CapCut/Apps/7.1.8.2957/ffmpeg.exe'
FONTS = Path('C:/Windows/Fonts')
CUES = ROOT / 'text/movies'
W, H = 720, 408
BAR = (40, 339, 680, 364)          # inside the solid part of the original subtitle bar
PAD = 0.15                          # seconds added before/after each detected cue (fades)
MSN_CX = 358                        # horizontal centre of the mission-movie subtitles
ENCODE = ['-c:v', 'h264_nvenc', '-preset', 'p7', '-profile:v', 'main', '-level', '3.1', '-rc', 'vbr',
          '-b:v', '1000k', '-maxrate', '2500k', '-bufsize', '2500k', '-g', '30', '-bf', '2', '-pix_fmt', 'yuv420p',
          '-c:a', 'copy', '-movflags', '+faststart', '-brand', 'mp42', '-video_track_timescale', '30000']


def font(size, bold=True):
    return ImageFont.truetype(str(FONTS / ('arialbd.ttf' if bold else 'arial.ttf')), size)


def text_layer(lines, size, outline=1):
    f = font(size)
    asc, desc = f.getmetrics()
    lh = asc + desc - 1
    w = int(max(f.getlength(l) for l in lines)) + 2 * outline + 2
    h = lh * len(lines) + 2 * outline
    img = Image.new('RGBA', (w, h))
    d = ImageDraw.Draw(img)
    for i, l in enumerate(lines):
        x = (w - f.getlength(l)) / 2
        d.text((x, outline + i * lh), l, font=f, fill=(255, 255, 255, 255), stroke_width=outline,
               stroke_fill=(0, 0, 0, 255))
    return img


def fit(text, maxw, size, minsize):
    lines = text.split('\n')
    while size > minsize:
        t = text_layer(lines, size)
        if t.width <= maxw:
            return t
        size -= 1
    t = text_layer(lines, minsize)
    return t.resize((maxw, t.height), Image.LANCZOS) if t.width > maxw else t


def cue_image(style, cue):
    """Returns (image, x, y)."""
    if style == 'bar':
        x0, y0, x1, y1 = BAR
        img = Image.new('RGBA', (x1 - x0, y1 - y0), (0, 0, 0, 255))
        t = fit(cue['en'], img.width - 8, 16, 11)
        img.alpha_composite(t, ((img.width - t.width) // 2, (img.height - t.height) // 2))
        return img, x0, y0
    bx0, by0, bx1, by1 = cue['box']
    t = fit(cue['en'], W - 40, 15, 11)
    # the mission subtitles are centred on x ~358: mirror the measured box around it so a box that only caught
    # part of the line still covers all of it
    half = max(MSN_CX - bx0, bx1 - MSN_CX)
    cx, cy = MSN_CX, (by0 + by1) / 2
    w = max(2 * half + 10, t.width + 14)
    h = max(by1 - by0 + 8, t.height + 8)
    x = int(min(max(4, cx - w / 2), W - 4 - w))
    y = int(min(max(4, cy - h / 2), H - 4 - h))
    img = Image.new('RGBA', (int(w), int(h)))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=5,
                                          fill=(10, 10, 14, 238))
    img.alpha_composite(t, ((img.width - t.width) // 2, (img.height - t.height) // 2))
    return img, x, y


def build(movie_id, spec, out, ffmpeg, preview=None):
    rel = f'nativeVITA/movie/{movie_id}/movie_00.mp4'
    src = game_file(rel)
    dst = out / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    cues = sorted(spec['cues'], key=lambda c: c['start'])
    with tempfile.TemporaryDirectory() as tmp:
        args = [ffmpeg, '-loglevel', 'error', '-y', '-i', str(src)]
        chain, last = [], '0:v'
        for i, c in enumerate(cues):
            img, x, y = cue_image(spec['style'], c)
            p = Path(tmp) / f'{i:03d}.png'
            img.save(p)
            if preview:
                preview.mkdir(parents=True, exist_ok=True)
                img.save(preview / f"{movie_id.replace('/', '_')}_{i:03d}.png")
            a = max(0.0, c['start'] - PAD)
            b = c['end'] + PAD
            if spec['style'] == 'msn':      # boxes differ per cue: never show two at once
                if i > 0:
                    a = max(a, cues[i - 1]['end'])
                if i + 1 < len(cues):
                    b = min(b, cues[i + 1]['start'] - 0.01)
            args += ['-i', str(p)]
            tag = f'v{i}'
            chain.append(f"[{last}][{i + 1}:v]overlay={x}:{y}:enable='between(t,{a:.3f},{b:.3f})'[{tag}]")
            last = tag
        script = Path(tmp) / 'filter.txt'
        script.write_text(';'.join(chain))
        args += ['-filter_complex_script', str(script), '-map', f'[{last}]', '-map', '0:a?', *ENCODE, str(dst)]
        subprocess.run(args, check=True)
    return dst


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, default=ROOT / 'build/rePatch/PCSG00675')
    ap.add_argument('--ffmpeg', default=FFMPEG)
    ap.add_argument('--only', help='movie id substring, e.g. CHP_000_000')
    ap.add_argument('--preview', type=Path, help='also save the cue images here')
    a = ap.parse_args()
    if not (Path(a.ffmpeg).is_file() or shutil.which(a.ffmpeg)):
        sys.exit(f'ffmpeg not found: {a.ffmpeg} (use --ffmpeg)')
    n = 0
    for f in sorted(CUES.glob('*.json')):
        group, name = f.stem.split('_', 1)
        movie_id = f'{group}/{name}'
        if a.only and a.only not in movie_id:
            continue
        spec = json.loads(f.read_text(encoding='utf8'))
        if not spec['cues']:
            continue
        build(movie_id, spec, a.out, a.ffmpeg, a.preview)
        n += 1
        print(f'{movie_id}: {len(spec["cues"])} cues')
    print(f'{n} movies written to {a.out}')


if __name__ == '__main__':
    main()
