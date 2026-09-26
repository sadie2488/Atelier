from fastapi.responses import JSONResponse


def not_implemented(what: str) -> JSONResponse:
    """Contract-shaped 501 for endpoints a lane hasn't built yet."""
    return JSONResponse(
        status_code=501,
        content={"error": {"code": "not_implemented", "message": f"{what} is not implemented yet."}},
    )
