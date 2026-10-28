from finance_api.routes import (
    accounts,
    auth,
    categories,
    conversations,
    health,
    profile,
    reports,
    transactions,
)

ROUTERS = (
    health.router,
    auth.router,
    profile.router,
    categories.router,
    accounts.router,
    transactions.router,
    reports.router,
    conversations.router,
)

__all__ = ["ROUTERS"]
