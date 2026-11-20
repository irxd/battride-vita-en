"""The game font (nativeVITA/font/FOT-NewRodinPro-DB.fnt): glyph metrics, and a patched copy for English.

    0x00 "FNT\\0", u32 version, u32 glyph count, u32 texture pages, f32 size (16), f32 line height (21), ...
    0x1c glyph records, 48 bytes each:
         u32 code (Unicode), u32 page, f32 u0, v0, u1, v1, f32 ?, width, height, x offset, y offset, advance

The font already has proportional ASCII. For English only the space is narrowed.
"""
import struct

REC = 0x1c
SPACE_ADVANCE = 5.0       # original 10.0: twice as wide as an English space should be next to 9 px letters


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
    f.set_advance(' ', SPACE_ADVANCE)
    return f
