"""Lazy-loaded MediaPipe Tasks models: pose landmarker + multiclass segmenter.

Model files are not checked in (see backend/vision/models/.gitignore); they download once on
first use and are cached under backend/vision/models/. V-S1: the multiclass segmenter's
category mask is how we tell skin from clothes -- never HSV/RGB thresholding.

Category ids of selfie_multiclass_256x256: 0 background, 1 hair, 2 body-skin, 3 face-skin,
4 clothes, 5 others (accessories).
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

SEGMENTER_MODEL_PATH = MODELS_DIR / "selfie_multiclass_256x256.tflite"
SEGMENTER_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/image_segmenter/"
    "selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite"
)

CATEGORY_BACKGROUND = 0
CATEGORY_HAIR = 1
CATEGORY_BODY_SKIN = 2
CATEGORY_FACE_SKIN = 3
CATEGORY_CLOTHES = 4
CATEGORY_OTHERS = 5


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
    """num_poses=2 (V-S6: detect a second person if present), no segmentation mask output.

    This mediapipe build (1.0.1, Windows) hard-crashes (native `CHECK failed:
    1 == ChannelSize()`) inside `.numpy_view()` on a PoseLandmarker segmentation mask --
    confirmed by isolated probe to be independent of `num_poses` and to affect the mask
    conversion itself, not detection. So this pass never requests pose segmentation masks;
    per-person spatial isolation instead comes from `image_segmenter()`'s category mask
    (V-S1) plus the chosen person's own landmark-derived region box (V-S5), and "largest
    person" (V-S6) is approximated by landmark bounding-box area instead of mask area. See
    backend/vision/CLAUDE.md / DECISIONS.md V-S1/V-S6 for the rule this approximates.
    """
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    from .candidate_params import POSE_MIN_CONFIDENCE

    _ensure(POSE_MODEL_PATH, POSE_MODEL_URL)
    base = mp_python.BaseOptions(model_asset_path=str(POSE_MODEL_PATH))
    opts = mp_vision.PoseLandmarkerOptions(
        base_options=base,
        running_mode=mp_vision.RunningMode.IMAGE,
        num_poses=2,
        output_segmentation_masks=False,
        min_pose_detection_confidence=POSE_MIN_CONFIDENCE,
        min_pose_presence_confidence=POSE_MIN_CONFIDENCE,
    )
    return mp_vision.PoseLandmarker.create_from_options(opts)


@lru_cache(maxsize=1)
def image_segmenter():
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    _ensure(SEGMENTER_MODEL_PATH, SEGMENTER_MODEL_URL)
    base = mp_python.BaseOptions(model_asset_path=str(SEGMENTER_MODEL_PATH))
    opts = mp_vision.ImageSegmenterOptions(
        base_options=base,
        running_mode=mp_vision.RunningMode.IMAGE,
        output_category_mask=True,
    )
    return mp_vision.ImageSegmenter.create_from_options(opts)
