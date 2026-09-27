"""PM-owned: /media serves local files first, then durable storage, and never escapes MEDIA_DIR."""
import uuid

from backend import config, media_store
from contract.schemas import ErrorResponse


def test_local_file_is_served(client):
    name = f"test/{uuid.uuid4().hex}.png"
    path = config.MEDIA_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG local")
    try:
        resp = client.get(f"/media/{name}")
        assert resp.status_code == 200 and resp.content == b"\x89PNG local"
    finally:
        path.unlink()


def test_missing_local_file_falls_back_to_store_and_caches(client, memory_media):
    name = f"test/{uuid.uuid4().hex}.png"
    media_store.put(name, b"\x89PNG stored")
    path = config.MEDIA_DIR / name
    try:
        resp = client.get(f"/media/{name}")
        assert resp.status_code == 200 and resp.content == b"\x89PNG stored"
        assert resp.headers["content-type"] == "image/png"
        assert path.read_bytes() == b"\x89PNG stored"  # cached locally
    finally:
        path.unlink(missing_ok=True)


def test_persist_uploads_under_relative_key(memory_media):
    name = f"test/{uuid.uuid4().hex}.png"
    path = config.MEDIA_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    try:
        media_store.persist(path)
        assert memory_media[name] == b"x"
    finally:
        path.unlink()


def test_unknown_media_is_contract_404(client):
    resp = client.get("/media/items/does_not_exist.png")
    assert resp.status_code == 404
    assert ErrorResponse.model_validate(resp.json()).error.code.value == "not_found"


def test_path_traversal_is_rejected(client):
    resp = client.get("/media/..%2F..%2Fbackend%2F.env")
    assert resp.status_code == 404
