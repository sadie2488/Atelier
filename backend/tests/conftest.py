"""Shared test fixtures. PM-owned.

Tests run offline: the database is never touched unless a test opts in. Lanes use
`fixture_items`, `fixture_outfits`, etc. (from contract/fixtures) and `client`.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.main import app

CONTRACT_FIXTURES = Path(__file__).resolve().parents[2] / "contract" / "fixtures"


def _load(name: str):
    return json.loads((CONTRACT_FIXTURES / name).read_text())


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(db, "ping", lambda: True)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fixture_items():
    return _load("items.json")


@pytest.fixture
def fixture_outfits():
    return _load("outfits.json")


@pytest.fixture
def fixture_avatar():
    return _load("avatar.json")


@pytest.fixture
def api_fixture():
    """api_fixture("post_items_analyze", "response") -> parsed contract/fixtures/api JSON."""
    return lambda name, kind="response": _load(f"api/{name}.{kind}.json")
