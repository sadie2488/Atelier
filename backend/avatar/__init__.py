"""Avatar lane: capture + pose validation, wireframe rig, avatar assembly, local compositing,
and the two-stage render endpoint. See backend/avatar/CLAUDE.md and contract/DECISIONS.md
(Avatar section) for the rules this package implements.
"""


def warmup(background: bool = True):
    """App startup hook: load the MediaPipe models in a background thread (see mp_models.warmup)."""
    from .mp_models import warmup as _warmup
    return _warmup(background)
