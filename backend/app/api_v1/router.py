from fastapi import APIRouter

from app.modules.agents.router import router as agents_router
from app.modules.ai.router import router as ai_router
from app.modules.analytics.router import router as analytics_router
from app.modules.api.router import public_router as public_api_router
from app.modules.api.router import router as api_keys_router
from app.modules.api.router import webhooks_router as api_webhooks_router
from app.modules.assistant.router import conversations_router
from app.modules.assistant.router import router as assistant_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.billing.router import router as billing_router
from app.modules.billing.router import webhooks_router as billing_webhooks_router
from app.modules.connectors.router import oauth_router as connectors_oauth_router
from app.modules.connectors.router import router as connectors_router
from app.modules.documents.router import router as documents_router
from app.modules.notifications.router import prefs_router as notification_prefs_router
from app.modules.notifications.router import router as notifications_router
from app.modules.orgs.router import invitations_router
from app.modules.orgs.router import router as orgs_router
from app.modules.search.router import router as search_router
from app.modules.workflows.router import router as workflows_router
from app.modules.workflows.router import webhooks_router as workflows_webhooks_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(orgs_router)
router.include_router(invitations_router)
router.include_router(documents_router)
router.include_router(search_router)
router.include_router(assistant_router)
router.include_router(conversations_router)
router.include_router(ai_router)
router.include_router(agents_router)
router.include_router(workflows_router)
router.include_router(workflows_webhooks_router)
router.include_router(connectors_router)
router.include_router(connectors_oauth_router)
router.include_router(notifications_router)
router.include_router(notification_prefs_router)
router.include_router(billing_router)
router.include_router(billing_webhooks_router)
router.include_router(audit_router)
router.include_router(analytics_router)
router.include_router(api_keys_router)
router.include_router(api_webhooks_router)
router.include_router(public_api_router)
