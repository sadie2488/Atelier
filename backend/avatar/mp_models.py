"""Lazy-loaded MediaPipe Tasks models for the avatar lane: pose landmarker + face detector.

Model files are not checked in (backend/avatar/models/.gitignore); they download once on first
use and are cached under backend/avatar/models/.

Windows note: this mediapipe build (1.0.1) hard-crashes inside PoseLandmarker's own
`.numpy_view()` when a segmentation mask is requested (confirmed by the vision lane's probe).
This module never requests one -- landmarks alone are enough for pose validation, the
wireframe rig, and placement anchors (A1/A2). Skin tone is sampled directly from the photo
near landmark-derived points (see skin.py) rather than through a segmentation category mask,
so this lane has no dependency on the selfie_multiclass segmenter.
"""
import urllib.request
from functools import lru_cache
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

POSE_MODEL_PATH = MODELS_DIR / "pose_landmarker_lite.task"
POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
)

FACE_MODEL_PATH = MODELS_DIR / "blaze_face_short_range.tflite"
FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"
)


def _ensure(path: Path, url: str) -> Path:
    if path.exists() and path.stat().st_size > 0:
        return path
    try:
        urllib.request.urlretrieve(url, path)
    except Exception as e:
        raise RuntimeError(
            f"Could not download required MediaPipe model {path.name} from {url}: {e}"
        ) from e
    return path


@lru_cache(maxsize=1)
def pose_landmarker():
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    _ensure(POSE_MODEL_PATH, POSE_MODEL_URL)
    base = mp_python.BaseOptions(model_asset_path=str(POSE_MODEL_PATH))
    opts = mp_vision.PoseLandmarkerOptions(
        base_options=base,
        running_mode=mp_vision.RunningMode.IMAGE,
        num_poses=1,
        output_segmentation_masks=False,  # never True here -- see module docstring
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
    )
    return mp_vision.PoseLandmarker.create_from_options(opts)


@lru_cache(maxsize=1)
def face_detector():
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    _ensure(FACE_MODEL_PATH, FACE_MODEL_URL)
    base = mp_python.BaseOptions(model_asset_path=str(FACE_MODEL_PATH))
    opts = mp_vision.FaceDetectorOptions(base_options=base, running_mode=mp_vision.RunningMode.IMAGE)
    return mp_vision.FaceDetector.create_from_options(opts)
