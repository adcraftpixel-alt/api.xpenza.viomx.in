from fastapi import APIRouter

from app.api.v1.auth.router import router as auth_router
from app.api.v1.users.router import router as users_router
from app.api.v1.expenses.router import router as expenses_router
from app.api.v1.categories.router import router as categories_router
from app.api.v1.budgets.router import router as budgets_router
from app.api.v1.savings_goals.router import router as savings_goals_router
from app.api.v1.dashboard.router import router as dashboard_router
from app.api.v1.ocr.router import router as ocr_router
from app.api.v1.ai.router import router as ai_router
from app.api.v1.subscriptions.router import router as subscriptions_router
from app.api.v1.notifications.router import router as notifications_router
from app.api.v1.billing.router import router as billing_router
from app.api.v1.reports.router import router as reports_router
from app.api.v1.admin.router import router as admin_router
from app.api.v1.analytics.router import router as analytics_router
from app.api.v1.content.router import router as content_router
from app.api.v1.support.router import router as support_router
from app.api.v1.family.router import router as family_router
from app.api.v1.wallets.router import router as wallets_router
from app.api.v1.service.router import router as service_router

router = APIRouter()

router.include_router(auth_router, prefix="/api/v1/auth")
router.include_router(users_router, prefix="/api/v1/users")
router.include_router(expenses_router, prefix="/api/v1/expenses")
router.include_router(categories_router, prefix="/api/v1/categories")
router.include_router(budgets_router, prefix="/api/v1/budgets")
router.include_router(savings_goals_router, prefix="/api/v1/savings-goals")
router.include_router(dashboard_router, prefix="/api/v1/dashboard")
router.include_router(ocr_router, prefix="/api/v1/ocr")
router.include_router(ai_router, prefix="/api/v1/ai")
router.include_router(subscriptions_router, prefix="/api/v1/subscriptions")
router.include_router(notifications_router, prefix="/api/v1/notifications")
router.include_router(billing_router, prefix="/api/v1/billing")
router.include_router(reports_router, prefix="/api/v1/reports")
router.include_router(admin_router, prefix="/api/v1/admin")
router.include_router(analytics_router, prefix="/api/v1/analytics")
router.include_router(content_router, prefix="/api/v1/content")
router.include_router(support_router, prefix="/api/v1/support")
router.include_router(family_router, prefix="/api/v1/family")
router.include_router(wallets_router, prefix="/api/v1/wallets")
router.include_router(service_router, prefix="/api/v1/service")
