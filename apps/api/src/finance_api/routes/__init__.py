from finance_api.routes import (
    accounts,
    auth,
    categories,
    conversations,
    friends,
    health,
    imports,
    merchant_rules,
    notices,
    profile,
    reports,
    settlements,
    shared_expenses,
    transactions,
)

ROUTERS = (
    health.router,
    auth.router,
    profile.router,
    categories.router,
    accounts.router,
    friends.router,
    settlements.router,
    shared_expenses.router,
    imports.router,
    merchant_rules.router,
    notices.router,
    transactions.router,
    reports.router,
    conversations.router,
)

__all__ = ["ROUTERS"]
