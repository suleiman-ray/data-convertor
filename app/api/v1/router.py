from fastapi import APIRouter

from app.api.v1.authoring import router as authoring_router
from app.api.v1.health import router as health_router
from app.api.v1.submissions import router as submissions_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(submissions_router)
api_router.include_router(authoring_router)
