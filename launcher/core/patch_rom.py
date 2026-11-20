#!/usr/bin/env python3
"""Cars Race-O-Rama Online - ROM-Patcher (Milestone 0).
Nutzung: patch_rom.py <original.nds> <net.elf> <ausgabe.nds>"""
import struct, sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blzlib import blz

BASE = 0x02000000
src, elf, out = sys.argv[1:4]
rom = bytearray(open(src, 'rb').read())
assert rom[0x0C:0x10] == b'B6OP', "Falsche ROM (erwartet Cars Race-O-Rama EU, B6OP)"
rd = lambda b, o: struct.unpack_from('<I', b, o)[0]

a9off, a9size = rd(rom, 0x20), rd(rom, 0x2C)
a9 = bytearray(blz(bytes(rom[a9off:a9off + a9size])))
A = lambda addr: addr - BASE

def w32(addr, val): struct.pack_into('<I', a9, A(addr), val)
def bl(frm, to): return 0xEB000000 | (((to - frm - 8) >> 2) & 0xFFFFFF)

# Symbole und Code aus dem ELF lesen (reines Python, keine LLVM-Tools nötig)
def read_elf(path):
    e = open(path, 'rb').read()
    shoff, = struct.unpack_from('<I', e, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', e, 0x2E)
    secs = [struct.unpack_from('<IIIIIIIIII', e, shoff + i * shentsize) for i in range(shnum)]
    nm = lambda strtab, o: e[strtab + o:e.index(b'\0', strtab + o)].decode()
    shstr = secs[shstrndx][4]
    code, syms = None, {}
    for sh in secs:
        name = nm(shstr, sh[0])
        if name == '.load': code = e[sh[4]:sh[4] + sh[5]]
        if sh[1] == 2:  # SYMTAB
            strtab = secs[sh[6]][4]
            for k in range(sh[5] // 16):
                st_name, st_value = struct.unpack_from('<II', e, sh[4] + k * 16)
                if st_name: syms[nm(strtab, st_name)] = st_value
    return code, syms
code, syms = read_elf(elf)
load_at, bss_end = 0x02114800, syms['__bss_end']
code += b'\0' * (-len(code) % 4)
bss = bss_end - (load_at + len(code))
new_arena = (bss_end + 0xFFF) & ~0xFFF

# 1) WM_SetLifeTime: frame/cam/mp-Lifetime = 0xFFFF (unendlich)
assert rd(a9, A(0x0202D1E8)) == 0xE1D120B2 and rd(a9, A(0x0202D1F0)) == 0xE3A03005
w32(0x0202D1E8, 0xE59F201C); w32(0x0202D1F0, 0xE59F3014)
# 2) Hook: Pad::Update -> hook_pad_read
assert rd(a9, A(0x02019748)) == bl(0x02019748, 0x02019754)
w32(0x02019748, bl(0x02019748, syms['hook_pad_read']))
def b(frm, to): return 0xEA000000 | (((to - frm - 8) >> 2) & 0xFFFFFF)
# 2b) Optional (M1): Logger-Hooks am Anfang von Port::Send / Port-Callback
def b(frm, to): return 0xEA000000 | (((to - frm - 8) >> 2) & 0xFFFFFF)
if 'hook_send_tramp' in syms:
    assert rd(a9, A(0x02032DEC)) == 0xE92D41F8 and rd(a9, A(0x02032EF8)) == 0xE92D4030
    w32(0x02032DEC, b(0x02032DEC, syms['hook_send_tramp']))
    w32(0x02032EF8, b(0x02032EF8, syms['hook_recv_tramp']))
# 2b2) Optional (M1b): Data-Sharing-Aufrufe umleiten
if 'ds_step_wrap' in syms:
    assert rd(a9, A(0x0202E230)) == bl(0x0202E230, 0x020A17AC) and rd(a9, A(0x0202DE7C)) == bl(0x0202DE7C, 0x020A1510)
    w32(0x0202E230, bl(0x0202E230, syms['ds_step_wrap']))
    w32(0x0202DE7C, bl(0x0202DE7C, syms['ds_start_wrap']))
# 2b3) Optional (M2b): WM-Trace - Einsprung-Trampoline "wmt_<ADDR>" und Callback-Hook
for name, addr in syms.items():
    if name.startswith('wmt_cb_'):
        tgt = int(name[7:], 16)
        assert rd(a9, A(tgt)) == 0xE1DA00B0          # ldrh r0,[r10]
        w32(tgt, bl(tgt, addr))
    elif name.startswith('wmt_'):
        tgt = int(name[4:], 16)
        orig = rd(a9, A(tgt))
        o = addr - 0x02114800 + 20                    # kopierter Originalbefehl im Trampolin
        assert struct.unpack_from('<I', code, o)[0] == orig, (name, hex(orig))
        w32(tgt, b(tgt, addr))
# 2b4) M2: Virtuelle WLAN-Schicht - Einsprünge ersetzen (vwm_hook_ADDR) bzw. Aufrufe umleiten (vwm_call_ADDR)
import re
for name, addr in sorted(syms.items()):
    if not re.fullmatch(r'vwm_(hook|call)_[0-9A-F]{8}', name): continue
    if name.startswith('vwm_hook_'):
        tgt = int(name[9:], 16)
        w32(tgt, b(tgt, addr))
    elif name.startswith('vwm_call_'):
        tgt = int(name[9:], 16)
        w = rd(a9, A(tgt)); assert (w & 0xFF000000) == 0xEB000000, name
        w32(tgt, bl(tgt, addr))
# 2c) Originalwerte des Headers für Download Play (Clone Boot) im Code hinterlegen
if 'g_orighdr' in syms:
    o = syms['g_orighdr'] - 0x02114800
    assert code[o:o+4] == b'ORDH'
    code = bytearray(code)
    struct.pack_into('<IIIH', code, o + 4, a9off, a9size, rd(rom, 0x80), struct.unpack_from('<H', rom, 0x15E)[0])
    code = bytes(code)
# 3) Heap-Start nach oben schieben
assert rd(a9, A(0x0209C560)) == 0x021147E0
w32(0x0209C560, new_arena)
# 4) Code als zusätzliche Autoload-Sektion anhängen
mp = rd(a9, A(0x02000928))
al_start, al_end = rd(a9, A(mp)), rd(a9, A(mp + 4))
assert al_end == BASE + len(a9)
entries = bytes(a9[A(al_start):A(al_end)])
a9 = a9[:A(al_start)] + code
new_list = BASE + len(a9)
a9 += entries + struct.pack('<III', load_at, len(code), bss)
struct.pack_into('<III', a9, A(mp), new_list, BASE + len(a9), rd(a9, A(mp + 8)))
struct.pack_into('<I', a9, A(mp + 0x14), 0)  # compressed_end = 0 (unkomprimiert)

# ARM9 ans ROM-Ende legen
new_off = 0x01F00000
footer = bytes(rom[a9off + a9size:a9off + a9size + 12])
assert footer[:4] == bytes.fromhex('2106c0de')
blob = bytes(a9) + footer
assert new_off >= rd(rom, 0x80) + 0x88 and new_off + len(blob) <= len(rom)
rom[new_off:new_off + len(blob)] = blob
struct.pack_into('<I', rom, 0x20, new_off)
struct.pack_into('<I', rom, 0x2C, len(a9))
struct.pack_into('<I', rom, 0x80, new_off + len(blob))

def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc
struct.pack_into('<H', rom, 0x15E, crc16(rom[:0x15E]))
open(out, 'wb').write(rom)
print(f"OK: Code {len(code)} B + BSS {bss} B @ {load_at:#x}, Heap ab {new_arena:#x}, ARM9 {len(a9)} B @ ROM {new_off:#x}")
print(f"Debug-Block @ {syms['g_dbg']:#x}, Config @ {syms['g_cfg']:#x}")
