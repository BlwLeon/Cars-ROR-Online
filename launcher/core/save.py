"""Cars Race-O-Rama Spielstand (512 Byte EEPROM).

Aufbau (selbst ermittelt):
  0x000  "CARSMNAT" + Kopf
  0x010  Profil 1 (0x9C Byte, beginnt mit 0x12345678)   Name: +0x78, UTF-16LE
  0x0AC  Profil 2
  0x148  Profil 3
  0x1F0  MD5 über 0x010..0x1EF
"""
import hashlib, os, struct
from . import paths
from .i18n import T

PROFILES = (0x010, 0x0AC, 0x148)
NAME_OFF, NAME_MAX = 0x78, 9       # bewusst begrenzt: 9 Zeichen, nur Buchstaben und Ziffern
ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")


def _read():
    with open(paths.SAVE, "rb") as f:
        d = bytearray(f.read())
    if len(d) < 0x200 or d[:8] != b"CARSMNAT":
        raise ValueError(T("save_format"))
    return d


def valid(d):
    return hashlib.md5(bytes(d[0x10:0x1F0])).digest() == bytes(d[0x1F0:0x200])


def profiles():
    """-> [{slot, name, used}] oder [] wenn noch kein Spielstand existiert."""
    if not os.path.exists(paths.SAVE):
        return []
    d = _read()
    res = []
    for i, base in enumerate(PROFILES):
        raw = bytes(d[base + NAME_OFF: base + NAME_OFF + 2 * (NAME_MAX + 1)])
        name = raw.decode("utf-16le", "ignore").split("\0")[0]
        used = d[base:base + 4] == b"\x78\x56\x34\x12" and bool(name)
        res.append({"slot": i, "name": name, "used": used, "online": i == ONLINE_SLOT and used and is_unlocked(d, base)})
    return res


def set_name(slot, name):
    name = name.strip()
    if not name or len(name) > NAME_MAX:
        raise ValueError(T("name_len", n=NAME_MAX))
    if any(c not in ALLOWED for c in name):
        raise ValueError(T("name_chars"))
    d = _read()
    if not valid(d):
        raise ValueError(T("save_checksum"))
    base = PROFILES[slot] + NAME_OFF
    field = (name.encode("utf-16le") + b"\0" * 64)[:2 * (NAME_MAX + 1)]
    d[base:base + len(field)] = field
    d[0x1F0:0x200] = hashlib.md5(bytes(d[0x10:0x1F0])).digest()
    bak = paths.SAVE + ".bak"
    if not os.path.exists(bak):
        with open(bak, "wb") as f:
            f.write(_read())
    with open(paths.SAVE, "wb") as f:
        f.write(d)


# ---------------- Online-Profil mit allem freigeschaltet ----------------
# Freischaltungen (selbst ermittelt, IsUnlocked 0x02038F28, Tabelle 0x020B75B8):
#   Fortschritt = Summe der Medaillen der 21 Story-Ereignisse (+0x06+i: 1 Gold=6P, 2 Silber=4P, 3 Bronze=2P)
#   +0x1B+gruppe*3+eintrag: Postkarten-Aufgaben, 4 x 2 Bit (3 = erfüllt)
#   +0x30/+0x34/+0x38/+0x3C: abgeschlossene Ereignisse je Typ (Bit = Ereignis-Nr.)
#   +0x40: Bonus-Freischaltungen (Bits 1,2,4,8)   +0x44: 17 Strecken-Bits
PROFILE_MAGIC, PROFILE_VER = 0x12345678, 0x1A7
ONLINE_SLOT = 2          # dritter Profilplatz: Story-Profile auf Platz 1/2 bleiben unberührt


def _empty_save():
    d = bytearray(0x200)
    d[0:8] = b"CARSMNAT"
    struct.pack_into("<II", d, 8, 0x1D4, 3)
    for base in PROFILES:
        struct.pack_into("<II", d, base, PROFILE_MAGIC, PROFILE_VER)
    return d


def _fill_unlocked(d, base):
    struct.pack_into("<II", d, base, PROFILE_MAGIC, PROFILE_VER)
    for i in range(21):
        d[base + 0x06 + i] = 1                       # Gold in allen Story-Ereignissen
    for i in range(21):
        d[base + 0x1B + i] = 0xFF                    # alle Postkarten-Aufgaben erfüllt
    for off in (0x30, 0x34, 0x38, 0x3C):
        struct.pack_into("<I", d, base + off, (1 << 21) - 1)
    d[base + 0x40] |= 0x0F
    struct.pack_into("<I", d, base + 0x44, (1 << 17) - 1)


def is_unlocked(d, base):
    return (all(d[base + 0x06 + i] == 1 for i in range(21)) and d[base + 0x40] & 0x0F == 0x0F
            and struct.unpack_from("<I", d, base + 0x44)[0] & 0x1FFFF == 0x1FFFF)


def ensure_online_profile(name):
    """Sorgt für ein Online-Profil (Platz 3) mit allem freigeschaltet. Gibt den Platz zurück.
    Legt bei Bedarf einen neuen Spielstand an. Ein fremdes Story-Profil auf Platz 3 wird nicht überschrieben."""
    name = "".join(c for c in (name or "") if c in ALLOWED)[:NAME_MAX] or "Player"
    if os.path.exists(paths.SAVE):
        d = _read()
        if not valid(d):
            raise ValueError(T("save_checksum"))
    else:
        d = _empty_save()
    base = PROFILES[ONLINE_SLOT]
    cur = bytes(d[base + NAME_OFF: base + NAME_OFF + 2 * (NAME_MAX + 1)]).decode("utf-16le", "ignore").split("\0")[0]
    if cur and not is_unlocked(d, base):
        raise ValueError(T("slot3_used"))
    if cur == name and is_unlocked(d, base):
        return ONLINE_SLOT
    if os.path.exists(paths.SAVE) and not os.path.exists(paths.SAVE + ".bak"):
        with open(paths.SAVE + ".bak", "wb") as f:
            f.write(_read())
    _fill_unlocked(d, base)
    field = (name.encode("utf-16le") + b"\0" * 64)[:2 * (NAME_MAX + 1)]
    d[base + NAME_OFF: base + NAME_OFF + len(field)] = field
    d[0x1F0:0x200] = hashlib.md5(bytes(d[0x10:0x1F0])).digest()
    with open(paths.SAVE, "wb") as f:
        f.write(d)
    return ONLINE_SLOT
