"""sRGB hex <-> CIE Lab (D65) and LCh. Used by the fixture generator and the contract check."""
import math

_WHITE = (95.047, 100.0, 108.883)  # D65 reference white


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
