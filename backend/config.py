"""Shared configuration. PM-owned: lanes read it, never edit it.

Every value comes from the environment (backend/.env locally, platform env vars in deploy),
with a safe default where one exists. Model versions are pinned, never "latest".
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")

# ---- storage
MONGODB_URI = os.environ.get("MONGODB_URI", "")
MONGODB_DB = os.environ.get("MONGODB_DB", "atelier")
MEDIA_DIR = Path(os.environ.get("MEDIA_DIR") or REPO_ROOT / "media")
FAILURE_LOG = MEDIA_DIR / "_failures" / "rejections.jsonl"
TEMP_DIR = MEDIA_DIR / "_tmp"
TEMP_TTL_SECONDS = 3600

# ---- Gemini (pinned; change only deliberately and re-run the lane evals)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_TEXT_MODEL = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
GEMINI_TIMEOUT_SECONDS = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "8"))  # local waits (explanations)
# Sent to Gemini as the request deadline for image generation: the API rejects deadlines under
# 10 s, and a try-on takes ~10 s. Runs in the background, so it never delays a response.
GEMINI_IMAGE_TIMEOUT_SECONDS = float(os.environ.get("GEMINI_IMAGE_TIMEOUT_SECONDS", "60"))

# ---- CORS: the frontend proxies /api and /media, so this only matters for direct calls
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
