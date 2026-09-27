"""sRGB hex <-> CIE Lab (D65) and LCh, CIEDE2000, and the colors.json lookup.

Pure python, no dependencies. Used by schemas.py, the fixture generator, and the contract check.
"""
import json
import math
from functools import lru_cache
from pathlib import Path

_WHITE = (95.047, 100.0, 108.883)  # D65 reference white
COLORS_JSON = Path(__file__).resolve().parents[1] / "colors.json"


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_lab(hex_: str):
    r, g, b = (_lin(int(hex_[i:i + 2], 16) / 255) for i in (1, 3, 5))
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) * 100
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) * 100
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) * 100

    def f(t):
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

    fx, fy, fz = (f(v / w) for v, w in zip((x, y, z), _WHITE))
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def lab_to_lch(lab):
    L, a, b = lab
    return (L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360)


def delta_e76(lab1, lab2) -> float:
    return math.dist(lab1, lab2)


def delta_e2000(lab1, lab2) -> float:
    """CIEDE2000 (Sharma, Wu, Dalal 2005), kL = kC = kH = 1."""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cbar = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cbar ** 7 / (Cbar ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if C1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if C2p else 0.0

    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    else:
        dhp = h2p - h1p
        if dhp > 180:
            dhp -= 360
        elif dhp < -180:
            dhp += 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp / 2))

    Lbarp = (L1 + L2) / 2
    Cbarp = (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbarp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbarp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbarp = (h1p + h2p + 360) / 2
    else:
        hbarp = (h1p + h2p - 360) / 2

    T = (1 - 0.17 * math.cos(math.radians(hbarp - 30)) + 0.24 * math.cos(math.radians(2 * hbarp))
         + 0.32 * math.cos(math.radians(3 * hbarp + 6)) - 0.20 * math.cos(math.radians(4 * hbarp - 63)))
    dtheta = 30 * math.exp(-(((hbarp - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cbarp ** 7 / (Cbarp ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lbarp - 50) ** 2 / math.sqrt(20 + (Lbarp - 50) ** 2)
    Sc = 1 + 0.045 * Cbarp
    Sh = 1 + 0.015 * Cbarp * T
    Rt = -math.sin(math.radians(2 * dtheta)) * Rc
    return math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2
                     + Rt * (dCp / Sc) * (dHp / Sh))


@lru_cache(maxsize=1)
def color_table():
    """(max_assignment_delta_e, {name: {"lab", "family", "everyday_neutral"}}) from colors.json."""
    data = json.loads(COLORS_JSON.read_text(encoding="utf-8"))
    table = {c["name"]: c for c in data["colors"]}
    return float(data["_meta"]["max_assignment_delta_e"]), table


def nearest_color(lab):
    """V-C4: (name, family, everyday_neutral) of the nearest center, or unmapped beyond the limit."""
    limit, table = color_table()
    name, entry = min(table.items(), key=lambda kv: delta_e2000(lab, kv[1]["lab"]))
    if delta_e2000(lab, entry["lab"]) > limit:
        return "unmapped", "unmapped", False
    return name, entry["family"], bool(entry["everyday_neutral"])


@lru_cache(maxsize=1)
def _display_names():
    data = json.loads((Path(__file__).resolve().parents[1] / "color_names.json").read_text(encoding="utf-8"))
    return [(c["name"], tuple(c["lab"])) for c in data["colors"]]


def display_name(lab) -> str:
    """Human-friendly name for a measured color: nearest xkcd color-survey entry by CIEDE2000.
    Display only; styling uses colors.json families (nearest_color)."""
    return min(_display_names(), key=lambda nl: delta_e2000(lab, nl[1]))[0]
