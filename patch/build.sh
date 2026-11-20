#!/bin/sh
# Baut den Online-Patch (patch/net.elf) aus patch/src.  Benötigt: clang + ld.lld (LLVM)
#   ./patch/build.sh                      -> patch/net.elf
#   ./patch/build.sh <rom.nds> <out.nds>  -> zusätzlich eine eigene ROM patchen (zum Testen)
set -e
cd "$(dirname "$0")"
CF="--target=armv5te-none-eabi -marm -mfloat-abi=soft -Os -ffreestanding -fno-builtin -nostdlib -fno-common -ffunction-sections -Wall"
mkdir -p build
for f in net vwm qol; do clang $CF -c src/$f.c -o build/$f.o; done
HOOKS=$(grep -ohE "vwm_(hook|call)_[0-9A-F]{8}" src/vwm.c src/qol.c | sort -u | sed 's/^/--undefined=/' | tr '\n' ' ')
ld.lld -T src/link.ld build/net.o build/vwm.o build/qol.o -o net.elf --gc-sections --undefined=hook_pad_read --undefined=g_q $HOOKS
echo "patch/net.elf gebaut"
if [ -n "$1" ]; then python3 ../launcher/core/patch_rom.py "$1" net.elf "${2:-Cars_RORM_Online.nds}"; fi
