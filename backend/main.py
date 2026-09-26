"""App entry point. PM-owned and not edited after Phase 0: every lane router is registered here.

Run from the repo root:  uvicorn backend.main:app --reload
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import config, db
from backend.routes import avatar, items, outfits

config.MEDIA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Atelier")

if config.CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    if not db.ping():
        return JSONResponse(status_code=503, content={"status": "ok", "db": "down"})
    return {"status": "ok", "db": "ok"}


for module in (items, outfits, avatar):
    app.include_router(module.router, prefix="/api")

app.mount("/media", StaticFiles(directory=config.MEDIA_DIR), name="media")


# Every error leaves as a contract-shaped body, never a bare string or stack trace.
@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    code = "not_found" if exc.status_code == 404 else "invalid_request"
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": code, "message": str(exc.detail)}})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(x) for x in first.get("loc", ()))
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "invalid_request", "message": f"{where}: {first.get('msg', 'invalid request')}"}},
    )
