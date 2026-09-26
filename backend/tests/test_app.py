"""PM-owned: every contract endpoint is routed under /api and errors are contract-shaped."""
import pytest

from contract.schemas import ENDPOINTS, ErrorResponse


def _url(path: str) -> str:
    parts = ["sample" if p.startswith("{") else p for p in path.split("/")]
    return "/api" + "/".join(parts)


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok", "db": "ok"}


@pytest.mark.parametrize("method,path", [(m, p) for m, p, *_ in ENDPOINTS if p != "/health"])
def test_endpoint_is_routed(client, method, path):
    resp = client.request(method, _url(path))
    assert resp.status_code != 405, f"{method} {path} not routed"
    if resp.status_code == 404:  # a routed "no such id" carries its own message; an unrouted path gets Starlette's
        assert resp.json()["error"]["message"] != "Not Found", f"{method} {path} not routed"
    if resp.status_code >= 400:
        ErrorResponse.model_validate(resp.json())


def test_unknown_route_is_contract_error(client):
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert ErrorResponse.model_validate(resp.json()).error.code.value == "not_found"
