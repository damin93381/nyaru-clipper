from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import api_router
from app.db import init_db
from app.services.storage import get_tasks_root


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_tasks_root()
    init_db()
    yield


app = FastAPI(title="Bilibili VTuber Suite API", lifespan=lifespan)
app.include_router(api_router)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"status": "ok", "service": "bilibili-vtuber-suite"}
