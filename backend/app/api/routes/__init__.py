from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.runtime import router as runtime_router
from app.api.routes.tasks import router as tasks_router


api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(runtime_router)
api_router.include_router(tasks_router)

__all__ = ["api_router"]
