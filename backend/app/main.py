import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import routes_a, routes_b

load_dotenv()

MEDIA_DIR = Path(os.environ.get("MEDIA_DIR", Path(__file__).resolve().parents[1] / "media"))
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Closet Atelier")
app.include_router(routes_a.router, prefix="/api")
app.include_router(routes_b.router, prefix="/api")
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
