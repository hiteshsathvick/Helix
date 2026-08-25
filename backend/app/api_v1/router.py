from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.orgs.router import invitations_router
from app.modules.orgs.router import router as orgs_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(orgs_router)
router.include_router(invitations_router)
