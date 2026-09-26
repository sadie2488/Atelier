"""V-F1: append-only failure/rejection log, one JSON object per line, opened in append mode.
Never read-modify-write -- concurrent ingests would clobber each other.
"""
import json

from backend import config


def log_failure(entry: dict) -> None:
    config.FAILURE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(config.FAILURE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
