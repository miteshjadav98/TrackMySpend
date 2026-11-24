"""Import every module's models so `Base.metadata` is complete (Alembic, tests)."""

from finance_core.accounts.models import Account
from finance_core.audit.models import AuditEvent
from finance_core.auth.models import AuthSession, PasswordResetToken
from finance_core.categories.models import Category
from finance_core.conversations.models import Conversation, Message
from finance_core.database.base import Base
from finance_core.friends.models import (
    Friend,
    FriendInvite,
    Notice,
    Settlement,
    SharedExpense,
    SharedExpenseShare,
)
from finance_core.imports.models import ImportRow, StatementImport, StatementLayout
from finance_core.merchants.models import MerchantRule
from finance_core.transactions.models import Transaction
from finance_core.users.models import FinancialProfile, User

__all__ = [
    "Account",
    "AuditEvent",
    "AuthSession",
    "Base",
    "Category",
    "Conversation",
    "FinancialProfile",
    "Friend",
    "FriendInvite",
    "ImportRow",
    "MerchantRule",
    "Message",
    "Notice",
    "PasswordResetToken",
    "Settlement",
    "SharedExpense",
    "SharedExpenseShare",
    "StatementImport",
    "StatementLayout",
    "Transaction",
    "User",
]
