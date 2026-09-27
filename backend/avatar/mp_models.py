"""Lazy-loaded MediaPipe Tasks models for the avatar lane: pose landmarker, face detector, and
image segmenter.

Model files are not checked in (backend/avatar/models/.gitignore); they download once on first
use and are cached under backend/avatar/models/.

Windows note: this mediapipe build (1.0.1) hard-crashes inside PoseLandmarker's own
`.numpy_view()` when a segmentation mask is requested from PoseLandmarker itself (confirmed by
the vision lane's probe). This module still never requests one there -- landmarks alone are
enough for pose validation, the wireframe rig, and placement anchors (A1/A2). That crash is
specific to PoseLandmarker's built-in segmentation output, not the standalone ImageSegmenter
task below: probed directly on this machine (selfie_multiclass, real phone photo) with no
crash, so A-B5 skin sampling uses it for exposed-skin detection (see skin.py).
"""
import logging
import os
import threading
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

# selfie_multiclass_256x256 category mask: 0 background, 1 hair, 2 body-skin, 3 face-skin,
# 4 clothes, 5 others/accessories (MediaPipe's published category list for this model).
SEGMENTER_MODEL_PATH = MODELS_DIR / "selfie_multiclass_256x256.tflite"
SEGMENTER_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/image_segmenter/"
    "selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite"
)


def _ensure(path: Path, url: str) -> Path:
    if path.exists() and path.stat().st_size > 0:
        return path
    # Download to a temp file then os.replace (atomic): a crash or a concurrent first use never
    # leaves a truncated model file that later loads as garbage.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.part")
    try:
        urllib.request.urlretrieve(url, tmp)
        os.replace(tmp, path)
    except Exception as e:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
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


@lru_cache(maxsize=1)
def image_segmenter():
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    _ensure(SEGMENTER_MODEL_PATH, SEGMENTER_MODEL_URL)
    base = mp_python.BaseOptions(model_asset_path=str(SEGMENTER_MODEL_PATH))
    opts = mp_vision.ImageSegmenterOptions(
        base_options=base, running_mode=mp_vision.RunningMode.IMAGE, output_category_mask=True,
    )
    return mp_vision.ImageSegmenter.create_from_options(opts)


def warmup(background: bool = True):
    """Load the pose, segmenter and face models once (downloading them if missing) so the first
    scan doesn't pay for it. Called at app startup; runs in a daemon thread by default and never
    raises. -> the thread (or None when run inline)."""
    def _load():
        for name, loader in (("pose", pose_landmarker), ("segmenter", image_segmenter), ("face", face_detector)):
            try:
                loader()
            except Exception:
                logging.getLogger(__name__).exception("avatar: warmup of %s model failed", name)

    if not background:
        _load()
        return None
    t = threading.Thread(target=_load, name="avatar-warmup", daemon=True)
    t.start()
    return t
