"""STA string tables (the game's text files, inside FPK2 archives).

    "STA\\0", u32 version (0x20120313), u32 count, u32 0
    count x (u32 byte length, UTF-8 bytes)          no NUL terminator, no padding

Lines inside a string are separated by "\\n".
"""
import struct

MAGIC = b'STA\0'


def is_sta(data):
    return data[:4] == MAGIC


def read(data):
    if not is_sta(data):
        raise ValueError('not an STA table')
    count = struct.unpack_from('<I', data, 8)[0]
    pos, out = 16, []
    for _ in range(count):
        n = struct.unpack_from('<I', data, pos)[0]
        out.append(data[pos + 4:pos + 4 + n].decode('utf8'))
        pos += 4 + n
    if pos != len(data):
        raise ValueError(f'STA: {len(data) - pos} trailing bytes')
    return out


def write(strings, version=0x20120313):
    out = bytearray(MAGIC + struct.pack('<III', version, len(strings), 0))
    for s in strings:
        b = s.encode('utf8')
        out += struct.pack('<I', len(b)) + b
    return bytes(out)
