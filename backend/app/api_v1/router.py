from fastapi import APIRouter

from app.modules.ai.router import router as ai_router
from app.modules.assistant.router import conversations_router
from app.modules.assistant.router import router as assistant_router
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
router.include_router(assistant_router)
router.include_router(conversations_router)
router.include_router(ai_router)
