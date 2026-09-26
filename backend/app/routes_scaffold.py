"""Fixture routes: serve contract/fixtures/api/*.response.json for contract endpoints.

Each lane builds its router from here, then swaps fixture routes for real ones.
"""
import json
from pathlib import Path

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from contract.schemas import ENDPOINTS, fixture_name

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "contract" / "fixtures" / "api"


def load_fixture(method: str, path: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{fixture_name(method, path)}.response.json").read_text())


def endpoints_for(paths: set[str]) -> list[tuple]:
    return [e for e in ENDPOINTS if e[1] in paths]


def _handler(method: str, path: str, response_model):
    if response_model is None:
        async def handler() -> Response:
            return Response(status_code=204)
    else:
        body = response_model.model_validate(load_fixture(method, path)).model_dump(mode="json")

        async def handler() -> JSONResponse:
            return JSONResponse(body)
    return handler


def fixture_router(endpoints: list[tuple]) -> APIRouter:
    router = APIRouter()
    for method, path, _request, response_model in endpoints:
        router.add_api_route(
            path,
            _handler(method, path, response_model),
            methods=[method],
            name=fixture_name(method, path),
            status_code=204 if response_model is None else 200,
        )
    return router
