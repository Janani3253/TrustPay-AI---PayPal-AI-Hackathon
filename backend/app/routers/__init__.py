"""FastAPI routers package for TrustPay AI."""
from .auth import router as auth_router
from .users import router as users_router
from .products import router as products_router
from .platforms import router as platforms_router
from .intent import router as intent_router
from .security import router as security_router
from .cart import router as cart_router
from .verification import router as verification_router
from .orders import router as orders_router
from .approvals import router as approvals_router
from .payments import router as payments_router
from .transactions import router as transactions_router
from .dashboard import router as dashboard_router
from .audit import router as audit_router

__all__ = [
    "auth_router",
    "users_router",
    "products_router",
    "platforms_router",
    "intent_router",
    "security_router",
    "cart_router",
    "verification_router",
    "orders_router",
    "approvals_router",
    "payments_router",
    "transactions_router",
    "dashboard_router",
    "audit_router",
]

