"""The game font (nativeVITA/font/FOT-NewRodinPro-DB.fnt): glyph metrics, and a patched copy for English.

    0x00 "FNT\\0", u32 version, u32 glyph count, u32 texture pages, f32 size (16), f32 line height (21), ...
    0x1c glyph records, 48 bytes each:
         u32 code (Unicode), u32 page, f32 u0, v0, u1, v1, f32 ?, width, height, x offset, y offset, advance

The font already has proportional ASCII. For English, the ASCII glyphs are drawn at ASCII_SCALE (quad size, offsets
and advance scaled; the texture stays the same) so more English fits in the game's text boxes, and the space is
narrowed. Tested in Vita3K: 0.85 stays legible.
"""
import struct

REC = 0x1c
ASCII_SCALE = 0.85
SPACE_ADVANCE = 4.5       # original 10.0 (before scaling): far too wide next to ~8 px letters


class Font:
    def __init__(self, data):
        if data[:4] != b'FNT\0':
            raise ValueError('not an FNT font')
        self.data = bytearray(data)
        self.count = struct.unpack_from('<I', data, 8)[0]
        self.index = {struct.unpack_from('<I', data, REC + i * 48)[0]: i for i in range(self.count)}

    def advance(self, ch):
        i = self.index.get(ord(ch))
        return None if i is None else struct.unpack_from('<f', self.data, REC + i * 48 + 44)[0]

    def set_advance(self, ch, value):
        struct.pack_into('<f', self.data, REC + self.index[ord(ch)] * 48 + 44, value)

    def width(self, text):
        """Pixel width of one line. Characters the font lacks count as a full-width glyph."""
        return sum(self.advance(c) or 13.0 for c in text)

    def missing(self, text):
        return sorted({c for c in text if c != '\n' and ord(c) not in self.index})


def english(data):
    f = Font(data)
    for c in range(0x21, 0x7f):
        o = REC + f.index[c] * 48 + 28            # width, height, x offset, y offset, advance
        struct.pack_into('<5f', f.data, o, *(v * ASCII_SCALE for v in struct.unpack_from('<5f', f.data, o)))
    f.set_advance(' ', SPACE_ADVANCE)
    return f
