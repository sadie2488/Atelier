import sys
from pathlib import Path

# contract/ lives next to backend/ (repo root locally, /srv in Docker); make it importable.
_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.append(_ROOT)
