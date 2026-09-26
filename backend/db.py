"""Shared MongoDB access. PM-owned: lanes import it, never edit it.

Collections (one owner each):
    items    - vision writes, styling/avatar read
    avatars  - avatar
    renders  - avatar (render_id is the cache key)
"""
from functools import lru_cache

from pymongo import MongoClient
from pymongo.database import Database

from backend import config


@lru_cache(maxsize=1)
def client() -> MongoClient:
    if not config.MONGODB_URI:
        raise RuntimeError("MONGODB_URI is not set (backend/.env).")
    return MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=3000, tz_aware=True)


def get_db() -> Database:
    """FastAPI dependency and plain accessor. Tests override this with a fake."""
    return client()[config.MONGODB_DB]


def ping() -> bool:
    try:
        client().admin.command("ping")
        return True
    except Exception:
        return False
