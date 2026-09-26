"""A2: 33 landmarks -> shoulder/torso/hip/leg geometry, the placement rig (A-B1, A-B2).

Anchors are normalized to landmarks, never absolute pixels -- there is no fixed body template.
The rig is just the subset of landmark geometry needed to draw the avatar (A3) and to place
garments (A4); it lives in whatever pixel canvas it was computed for (see canvas_bbox/translate).
"""
from dataclasses import dataclass

Point = tuple[float, float]


@dataclass
class Rig:
    landmarks: dict[str, Point]        # pixel coords in this rig's own canvas
    shoulder_mid: Point
    hip_mid: Point
    shoulder_width: float
    hip_width: float
    neck: Point
    head_center: Point
    head_radius: float


def _mid(a: Point, b: Point) -> Point:
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def _dist(a: Point, b: Point) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def compute_rig(landmarks_px: dict[str, tuple[float, float, float]]) -> Rig:
    """landmarks_px: {name: (x, y, visibility)} in some canvas's pixel coordinates."""
    pts = {name: (x, y) for name, (x, y, _v) in landmarks_px.items()}
    shoulder_mid = _mid(pts["left_shoulder"], pts["right_shoulder"])
    hip_mid = _mid(pts["left_hip"], pts["right_hip"])
    shoulder_width = _dist(pts["left_shoulder"], pts["right_shoulder"])
    hip_width = _dist(pts["left_hip"], pts["right_hip"])

    head_radius = max(shoulder_width * 0.32, 1.0)
    neck = (shoulder_mid[0], shoulder_mid[1] - head_radius * 0.3)
    nose = pts.get("nose", (shoulder_mid[0], shoulder_mid[1] - head_radius * 2))
    head_center = (nose[0], min(nose[1], neck[1] - head_radius * 0.6))

    return Rig(
        landmarks=pts,
        shoulder_mid=shoulder_mid,
        hip_mid=hip_mid,
        shoulder_width=shoulder_width,
        hip_width=hip_width,
        neck=neck,
        head_center=head_center,
        head_radius=head_radius,
    )


def canvas_bbox(rig: Rig, pad_fraction: float = 0.18) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) around every rig point, padded, with room for the head."""
    xs = [p[0] for p in rig.landmarks.values()]
    xs += [rig.head_center[0] - rig.head_radius, rig.head_center[0] + rig.head_radius]
    ys = [p[1] for p in rig.landmarks.values()]
    ys += [rig.head_center[1] - rig.head_radius * 1.3]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    pad_x = (x1 - x0) * pad_fraction
    pad_y = (y1 - y0) * pad_fraction
    return (x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y)


def translate(rig: Rig, dx: float, dy: float) -> Rig:
    def t(p: Point) -> Point:
        return (p[0] + dx, p[1] + dy)

    return Rig(
        landmarks={k: t(v) for k, v in rig.landmarks.items()},
        shoulder_mid=t(rig.shoulder_mid), hip_mid=t(rig.hip_mid),
        shoulder_width=rig.shoulder_width, hip_width=rig.hip_width,
        neck=t(rig.neck), head_center=t(rig.head_center), head_radius=rig.head_radius,
    )


def rig_to_dict(rig: Rig) -> dict:
    return {
        "landmarks": {k: list(v) for k, v in rig.landmarks.items()},
        "shoulder_mid": list(rig.shoulder_mid), "hip_mid": list(rig.hip_mid),
        "shoulder_width": rig.shoulder_width, "hip_width": rig.hip_width,
        "neck": list(rig.neck), "head_center": list(rig.head_center), "head_radius": rig.head_radius,
    }


def rig_from_dict(d: dict) -> Rig:
    return Rig(
        landmarks={k: tuple(v) for k, v in d["landmarks"].items()},
        shoulder_mid=tuple(d["shoulder_mid"]), hip_mid=tuple(d["hip_mid"]),
        shoulder_width=d["shoulder_width"], hip_width=d["hip_width"],
        neck=tuple(d["neck"]), head_center=tuple(d["head_center"]), head_radius=d["head_radius"],
    )
