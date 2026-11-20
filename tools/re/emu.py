"""Call functions of the Vita eboot under Unicorn (Thumb). Used to check our Python ports against the game code.

    emu = Emu('eboot/patch/PCSG00675/eboot.bin.elf')
    p = emu.alloc(b'...'); emu.call(0x81213218, ctx, p, 0x20); emu.read(p, 0x20)
"""
import struct, sys, os
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR
sys.path.insert(0, os.path.dirname(__file__))
from velf import VitaElf

PAGE = 0x1000
HEAP, HEAP_SIZE = 0x90000000, 0x04000000
STACK, STACK_SIZE = 0x9f000000, 0x00100000
RET = 0x9ff00000                  # return address: hitting it stops the emulation


def _up(x):
    return (x + PAGE - 1) & ~(PAGE - 1)


class Emu:
    def __init__(self, elf):
        self.e = VitaElf(elf)
        self.uc = uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        for v, o, fs, ms, _ in self.e.segs:
            base = v & ~(PAGE - 1)
            uc.mem_map(base, _up(v + ms) - base)
            uc.mem_write(v, self.e.data[o:o + fs])
        uc.mem_map(HEAP, HEAP_SIZE)
        uc.mem_map(STACK, STACK_SIZE)
        uc.mem_map(RET, PAGE)
        self.brk = HEAP

    def alloc(self, data=b'', size=None):
        size = size or len(data) or 4
        p = self.brk
        self.brk = (self.brk + size + 15) & ~15
        if data:
            self.uc.mem_write(p, bytes(data))
        return p

    def reset_heap(self):
        self.brk = HEAP

    def read(self, p, n):
        return bytes(self.uc.mem_read(p, n))

    def write(self, p, data):
        self.uc.mem_write(p, bytes(data))

    def call(self, fn, *args, stack=(), max_insns=0):
        uc = self.uc
        sp = STACK + STACK_SIZE - 0x1000 - 4 * len(stack)
        for i, a in enumerate(stack):
            uc.mem_write(sp + 4 * i, struct.pack('<I', a & 0xffffffff))
        for reg, a in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            uc.reg_write(reg, a & 0xffffffff)
        uc.reg_write(UC_ARM_REG_SP, sp)
        uc.reg_write(UC_ARM_REG_LR, RET | 1)
        uc.emu_start(fn | 1, RET, count=max_insns)
        return uc.reg_read(UC_ARM_REG_R0)
