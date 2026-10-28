from finance_api.routes import (
    auth,
    categories,
    conversations,
    health,
    merchant_rules,
    profile,
    reports,
    transactions,
)

ROUTERS = (
    health.router,
    auth.router,
    profile.router,
    categories.router,
    merchant_rules.router,
    transactions.router,
    reports.router,
    conversations.router,
)

__all__ = ["ROUTERS"]
