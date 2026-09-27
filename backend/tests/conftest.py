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


class FakeCursor(list):
    def sort(self, key, direction=1):
        super().sort(key=lambda d: d.get(key), reverse=direction < 0)
        return self

    def limit(self, n):
        return FakeCursor(self[:n]) if n else self


class FakeCollection:
    """Just enough of pymongo's Collection for route tests: equality filters only."""

    def __init__(self):
        self.docs: list[dict] = []

    def _match(self, doc, flt):
        return all(doc.get(k) == v for k, v in (flt or {}).items())

    def find(self, flt=None, projection=None):
        return FakeCursor(dict(d) for d in self.docs if self._match(d, flt))

    def find_one(self, flt=None, projection=None):
        return next((dict(d) for d in self.docs if self._match(d, flt)), None)

    def insert_one(self, doc):
        self.docs.append(dict(doc))

    def update_one(self, flt, update, upsert=False):
        """Supports {"$set": {...}} only."""
        for d in self.docs:
            if self._match(d, flt):
                d.update(update.get("$set", {}))
                return
        if upsert:
            self.docs.append({**flt, **update.get("$set", {})})

    def count_documents(self, flt=None):
        return sum(self._match(d, flt) for d in self.docs)

    def delete_many(self, flt=None):
        self.docs = [d for d in self.docs if not self._match(d, flt)]


class FakeDB(dict):
    def __missing__(self, name):
        self[name] = FakeCollection()
        return self[name]


@pytest.fixture(autouse=True)
def memory_media(monkeypatch):
    """Durable media goes to a dict instead of GridFS: tests never touch MongoDB."""
    from backend import media_store

    store: dict[str, bytes] = {}
    monkeypatch.setattr(media_store, "put", lambda key, data: store.__setitem__(key, bytes(data)))
    monkeypatch.setattr(media_store, "get", lambda key: store.get(key))
    return store


@pytest.fixture
def memory_db():
    return FakeDB()


@pytest.fixture
def client(monkeypatch, memory_db):
    """App client wired to an in-memory database: tests never touch MongoDB."""
    monkeypatch.setattr(db, "ping", lambda: True)
    app.dependency_overrides[db.get_db] = lambda: memory_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(db.get_db, None)


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
