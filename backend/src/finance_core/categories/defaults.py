"""System category catalogue and the keyword hints used to infer a category.

The slugs here are stable identifiers: they are referenced by the LLM prompt, the offline
parser, and migrations. Display names can change freely; slugs cannot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

CategoryKind = Literal["expense", "income"]


@dataclass(frozen=True, slots=True)
class CategoryDefinition:
    slug: str
    name: str
    kind: CategoryKind
    icon: str
    sort_order: int
    keywords: tuple[str, ...] = ()


SYSTEM_CATEGORIES: tuple[CategoryDefinition, ...] = (
    # --- expenses -------------------------------------------------------------------------
    CategoryDefinition("food", "Food & Dining", "expense", "utensils", 10, (
        "dinner", "lunch", "breakfast", "brunch", "meal", "meals", "food", "restaurant",
        "cafe", "coffee", "tea", "chai", "snack", "snacks", "pizza", "burger", "biryani",
        "swiggy", "zomato", "dominos", "mcdonalds", "kfc", "starbucks", "dessert",
        "ice cream", "bakery", "takeaway", "dining", "eating out", "drinks", "juice",
    )),
    CategoryDefinition("groceries", "Groceries", "expense", "shopping-basket", 20, (
        "grocery", "groceries", "vegetables", "veggies", "fruits", "milk", "bread", "eggs",
        "kirana", "supermarket", "bigbasket", "blinkit", "zepto", "dmart", "instamart",
        "jiomart", "provisions",
    )),
    CategoryDefinition("transport", "Transport", "expense", "car", 30, (
        "uber", "ola", "rapido", "taxi", "cab", "auto", "rickshaw", "bus", "train", "metro",
        "parking", "toll", "fastag", "petrol", "diesel", "fuel", "cng", "ev charging",
        "commute", "ride",
    )),
    CategoryDefinition("shopping", "Shopping", "expense", "shopping-bag", 40, (
        "amazon", "flipkart", "myntra", "ajio", "meesho", "nykaa", "clothes", "shoes",
        "shirt", "dress", "jeans", "electronics", "gadget", "headphones", "shopping", "mall",
    )),
    CategoryDefinition("housing", "Rent & Housing", "expense", "home", 50, (
        "rent", "house rent", "maintenance", "society", "pg", "hostel", "repair", "plumber",
        "electrician", "furniture", "home",
    )),
    CategoryDefinition("utilities", "Bills & Utilities", "expense", "receipt", 60, (
        "electricity", "electricity bill", "water bill", "gas", "cylinder", "lpg",
        "internet", "wifi", "broadband", "recharge", "mobile recharge", "phone bill",
        "postpaid", "dth", "bill", "bills",
    )),
    CategoryDefinition("subscriptions", "Subscriptions", "expense", "repeat", 70, (
        "netflix", "prime", "hotstar", "spotify", "youtube premium", "subscription",
        "icloud", "google one", "membership",
    )),
    CategoryDefinition("entertainment", "Entertainment", "expense", "clapperboard", 80, (
        "movie", "movies", "cinema", "pvr", "inox", "concert", "game", "gaming", "party",
        "outing", "bookmyshow", "event", "show",
    )),
    CategoryDefinition("health", "Health & Fitness", "expense", "heart-pulse", 90, (
        "doctor", "hospital", "medicine", "medicines", "pharmacy", "chemist", "clinic",
        "dentist", "lab test", "health", "gym", "fitness", "apollo", "pharmeasy", "1mg",
    )),
    CategoryDefinition("education", "Education", "expense", "graduation-cap", 100, (
        "school", "college", "tuition", "course", "books", "fees", "exam", "udemy",
        "coaching", "stationery",
    )),
    CategoryDefinition("travel", "Travel", "expense", "plane", 110, (
        "flight", "hotel", "trip", "travel", "vacation", "holiday", "airbnb", "makemytrip",
        "goibibo", "visa", "irctc",
    )),
    CategoryDefinition("personal_care", "Personal Care", "expense", "sparkles", 120, (
        "salon", "haircut", "spa", "parlour", "grooming", "cosmetics", "skincare",
    )),
    CategoryDefinition("gifts", "Gifts & Donations", "expense", "gift", 130, (
        "gift", "gifts", "donation", "charity", "temple", "present",
    )),
    CategoryDefinition("insurance", "Insurance", "expense", "shield", 140, (
        "insurance", "premium", "lic", "policy",
    )),
    CategoryDefinition("loans", "Loans & EMI", "expense", "landmark", 150, (
        "emi", "loan", "repayment",
    )),
    CategoryDefinition("other", "Other", "expense", "circle-ellipsis", 990, ()),
    # --- income ---------------------------------------------------------------------------
    CategoryDefinition("salary", "Salary", "income", "briefcase", 10, (
        "salary", "paycheck", "payroll", "stipend", "wages", "pay",
    )),
    CategoryDefinition("business", "Business & Freelance", "income", "laptop", 20, (
        "freelance", "client", "invoice", "consulting", "business", "side gig", "commission",
    )),
    CategoryDefinition("investment_income", "Interest & Dividends", "income", "trending-up", 30, (
        "interest", "dividend", "dividends", "fd interest", "returns", "capital gains",
    )),
    CategoryDefinition("refund", "Refunds & Cashback", "income", "undo-2", 40, (
        "refund", "cashback", "reimbursement", "reversal", "refunded",
    )),
    CategoryDefinition("rental_income", "Rental Income", "income", "key", 50, (
        "rent received", "tenant", "rental",
    )),
    CategoryDefinition("gifts_received", "Gifts Received", "income", "gift", 60, (
        "gift", "gifted", "birthday money",
    )),
    CategoryDefinition("other_income", "Other Income", "income", "circle-plus", 990, ()),
)  # fmt: skip

FALLBACK_SLUG: dict[CategoryKind, str] = {"expense": "other", "income": "other_income"}


@lru_cache(maxsize=1)
def _keyword_patterns() -> tuple[tuple[re.Pattern[str], CategoryDefinition, int], ...]:
    patterns = []
    for definition in SYSTEM_CATEGORIES:
        for keyword in definition.keywords:
            pattern = re.compile(rf"(?<![a-z]){re.escape(keyword)}(?![a-z])", re.IGNORECASE)
            patterns.append((pattern, definition, len(keyword)))
    # Longer keywords first, so "rent received" beats "rent" and "ice cream" beats "cream".
    patterns.sort(key=lambda item: item[2], reverse=True)
    return tuple(patterns)


def infer_category(text: str, kind: CategoryKind | None) -> tuple[CategoryDefinition, str] | None:
    """Best keyword match as (category, matched keyword), restricted to `kind` if known."""
    if not text:
        return None
    for pattern, definition, _ in _keyword_patterns():
        if kind is not None and definition.kind != kind:
            continue
        if match := pattern.search(text):
            return definition, match.group(0)
    return None


def infer_category_slug(text: str, kind: CategoryKind | None) -> str | None:
    found = infer_category(text, kind)
    return found[0].slug if found else None


def system_category(slug: str) -> CategoryDefinition | None:
    return next((c for c in SYSTEM_CATEGORIES if c.slug == slug), None)
