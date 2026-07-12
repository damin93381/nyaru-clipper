from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.runtime import router as runtime_router
from app.api.routes.tasks import router as tasks_router
from app.api.routes.workstation_sources import router as workstation_sources_router
from app.api.routes.workstation_tasks import router as workstation_tasks_router
from app.api.routes.workstation_queue import router as workstation_queue_router


api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(runtime_router)
api_router.include_router(tasks_router)
api_router.include_router(workstation_sources_router)
api_router.include_router(workstation_tasks_router)
api_router.include_router(workstation_queue_router)

__all__ = ["api_router"]
