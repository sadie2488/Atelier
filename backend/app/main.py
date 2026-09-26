import os
from dotenv import load_dotenv
from fastapi import FastAPI
from pymongo import MongoClient

load_dotenv()
app = FastAPI()


@app.get("/api/health")
def health():
    MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=3000).admin.command("ping")
    return {"status": "ok", "db": "ok"}
