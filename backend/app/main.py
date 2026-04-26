from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.db import init_db
from app.services.runtime_capabilities import get_runtime_capability_summary
from app.services.storage import get_tasks_root

runtime_logger = logging.getLogger("app.runtime")


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_tasks_root()
    init_db()
    runtime_summary = get_runtime_capability_summary()
    runtime_logger.info(
        json.dumps(
            {
                "event": "runtime_capabilities_startup",
                "profile": runtime_summary["detected_profile"],
                "status": runtime_summary["status"],
                "accelerator": runtime_summary["accelerator"],
                "warnings": runtime_summary["warnings"],
                "issue_codes": runtime_summary["issue_codes"],
            }
        )
    )
    yield


app = FastAPI(title="Bilibili VTuber Suite API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"status": "ok", "service": "bilibili-vtuber-suite"}
