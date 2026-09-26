import json

import pytest

from contract.schemas import ENDPOINTS
from app.main import MEDIA_DIR
from app.routes_scaffold import FIXTURE_DIR


def _concrete(path: str) -> str:
    return path.replace("{photo_id}", "p1").replace("{garment_id}", "100000000000000000000001")


@pytest.mark.parametrize("method,path,request_model,response_model", ENDPOINTS, ids=[f"{m} {p}" for m, p, *_ in ENDPOINTS])
def test_endpoint_serves_valid_fixture(client, method, path, request_model, response_model):
    resp = client.request(method, "/api" + _concrete(path))
    if response_model is None:
        assert resp.status_code == 204
        return
    assert resp.status_code == 200, resp.text
    response_model.model_validate(resp.json())


def test_fixture_dir_exists():
    assert FIXTURE_DIR.is_dir()


def test_media_served(client):
    sub = MEDIA_DIR / "test"
    sub.mkdir(exist_ok=True)
    f = sub / "scaffold_probe.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n")
    try:
        resp = client.get("/media/test/scaffold_probe.png")
        assert resp.status_code == 200
        assert resp.content.startswith(b"\x89PNG")
    finally:
        f.unlink()
        sub.rmdir()
