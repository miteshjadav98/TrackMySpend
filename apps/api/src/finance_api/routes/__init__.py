from finance_api.routes import (
    accounts,
    auth,
    categories,
    conversations,
    friends,
    health,
    merchant_rules,
    profile,
    reports,
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
    shared_expenses.router,
    merchant_rules.router,
    transactions.router,
    reports.router,
    conversations.router,
)

__all__ = ["ROUTERS"]
