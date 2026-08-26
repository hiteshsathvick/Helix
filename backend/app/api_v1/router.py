from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.documents.router import router as documents_router
from app.modules.orgs.router import invitations_router
from app.modules.orgs.router import router as orgs_router
from app.modules.search.router import router as search_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(orgs_router)
router.include_router(invitations_router)
router.include_router(documents_router)
router.include_router(search_router)
