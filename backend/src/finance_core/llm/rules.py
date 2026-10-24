"""Deterministic, offline understanding engine.

Two jobs:
1. Make the whole product runnable and testable with no cloud credentials.
2. Act as the fallback when Gemini is slow or down, so the common case ("spent 350 on
   dinner") still works during a provider outage.

It intentionally handles the frequent, well-structured phrasings well and leaves anything
ambiguous unset, so the workflow asks a question instead of guessing.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

from finance_core.categories.defaults import (
    CategoryKind,
    infer_category,
    infer_category_slug,
    system_category,
)
from finance_core.dates import MONTHS, WEEKDAYS, day_first_for_locale, resolve_date_expression
from finance_core.llm.base import ReplyRequest, UnderstandRequest, UnderstandResult
from finance_core.llm.schemas import (
    ExtractedTransaction,
    Intent,
    PeriodSpec,
    SearchSpec,
    TurnUnderstanding,
)
from finance_core.money import AmountMention, find_amounts

_I = re.IGNORECASE

_EXPENSE_WORDS = re.compile(
    r"\b(spent|spend|spending|paid|pay|paying|bought|buy|buying|purchased|purchase|cost|costs|"
    r"debited|gave|recharged|ordered|booked|expense|bill|fees?)\b",
    _I,
)
_INCOME_WORDS = re.compile(
    r"\b(received|receive|earned|earn|credited|salary|refund|refunded|cashback|income|bonus|"
    r"dividends?|interest|reimbursed|reimbursement|deposited|sold|got paid|stipend|freelance)\b",
    _I,
)
_SEARCH = re.compile(
    r"\b(show|list|find|search|display|view|see)\b.*\b(transactions?|expenses?|spends?|spending|"
    r"payments?|purchases?|income|entries|orders?|bills?)\b"
    r"|\b(biggest|largest|highest|most expensive|smallest)\b",
    _I,
)
_SUMMARY = re.compile(
    r"\b(how much|summary|summari[sz]e|totals?|breakdown|overview|report|my finances|"
    r"did i (spend|earn)|have i (spent|earned)|what did i spend|where did my money go)\b",
    _I,
)
_HELP = re.compile(
    r"\b(help|what can you do|what do you do|how (do|does|can) (i|you|this)|features|how to use)\b",
    _I,
)
_SMALLTALK = re.compile(
    r"^\s*(hi+|hello|hey|yo|namaste|thanks|thank you|thx|ty|good (morning|afternoon|evening|night)|"
    r"ok(ay)?|cool|great|nice|bye)\b",
    _I,
)
_LARGEST = re.compile(r"\b(biggest|largest|highest|most expensive)\b", _I)
_TOP_N = re.compile(r"\b(?:top|last|recent|latest)\s+(\d{1,2})\b", _I)

_PAYMENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(upi|gpay|google pay|phonepe|phone pe|paytm|bhim)\b", _I), "upi"),
    (re.compile(r"\bcredit\s*card\b", _I), "credit_card"),
    (re.compile(r"\bdebit\s*card\b", _I), "debit_card"),
    (re.compile(r"\b(net\s*banking|netbanking)\b", _I), "net_banking"),
    (re.compile(r"\b(neft|imps|rtgs|bank transfer)\b", _I), "bank_transfer"),
    (re.compile(r"\bcheque\b", _I), "cheque"),
    (re.compile(r"\b(wallet|amazon pay)\b", _I), "wallet"),
    (re.compile(r"\bcash\b", _I), "cash"),
    (re.compile(r"\bcard\b", _I), "card"),
)

_KNOWN_MERCHANTS = (
    "swiggy", "zomato", "uber", "ola", "rapido", "amazon", "flipkart", "myntra", "ajio",
    "meesho", "nykaa", "netflix", "spotify", "hotstar", "starbucks", "dominos", "mcdonalds",
    "kfc", "bigbasket", "blinkit", "zepto", "dmart", "instamart", "jiomart", "irctc",
    "makemytrip", "goibibo", "airbnb", "apollo", "pharmeasy", "bookmyshow", "pvr", "inox",
)  # fmt: skip
_MERCHANT_PATTERN = re.compile(rf"\b({'|'.join(_KNOWN_MERCHANTS)})\b", _I)
_AT_MERCHANT = re.compile(r"\b(?:at|from)\s+([A-Z][\w&'.-]*(?:\s+[A-Z][\w&'.-]*){0,3})")

_DESCRIPTION = re.compile(
    r"\b(?:on|for)\s+(?:a\s+|an\s+|the\s+|my\s+|some\s+)?"
    r"(?P<d>[a-z][a-z'&\- ]{1,40}?)"
    r"(?=\s+(?:using|via|with|by|through|from|at|on|in|yesterday|today|tonight|last|this|"
    r"ago|and|paid|\d)\b|\s*[,.;!?]|\s*$)",
    _I,
)

_WEEKDAY_ALT = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
_DATE_EXPRESSIONS = re.compile(
    "|".join(
        [
            r"\bday before yesterday\b",
            r"\b(?:yesterday|yday|last night)\b",
            r"\b(?:today|tonight|this morning|this afternoon|this evening)\b",
            r"\b\d{1,3}\s+days?\s+ago\b",
            r"\b(?:a|an|one|two|three)\s+(?:days?|weeks?)\s+ago\b",
            rf"\b(?:last|previous)\s+(?:{_WEEKDAY_ALT})\b",
            rf"\b(?:on\s+)?(?:this\s+)?(?:{_WEEKDAY_ALT})\b",
            r"\b\d{4}-\d{1,2}-\d{1,2}\b",
            r"\b\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\b",
            rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTH_ALT})(?:,?\s+\d{{4}})?\b",
            rf"\b(?:{_MONTH_ALT})\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b",
        ]
    ),
    _I,
)
_SEGMENT_SPLIT = re.compile(r"\s*(?:,(?!\d)|;|\band\b|\balso\b|\bplus\b|\bthen\b|&)\s*", _I)

_REPLIES = {
    "help": (
        "I can record your expenses and income from a quick message - try "
        "“Spent ₹350 on dinner yesterday using UPI”. I can also show this "
        "month's spending summary or find past transactions."
    ),
    "smalltalk": (
        "Happy to help! Tell me about a purchase, or ask “How much did I spend this month?”"
    ),
    "out_of_scope": (
        "I can't help with that, but I can track your spending, record income, and "
        "summarise your finances."
    ),
}


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")


def detect_type(text: str) -> CategoryKind | None:
    income = bool(_INCOME_WORDS.search(text))
    expense = bool(_EXPENSE_WORDS.search(text))
    if income and not expense:
        return "income"
    if expense and not income:
        return "expense"
    return None


def detect_payment_method(text: str) -> str | None:
    for pattern, method in _PAYMENT_PATTERNS:
        if pattern.search(text):
            return method
    return None


def detect_merchant(text: str) -> str | None:
    if match := _MERCHANT_PATTERN.search(text):
        return match.group(1).title()
    if match := _AT_MERCHANT.search(text):
        return match.group(1).strip()
    return None


def find_date_expression(text: str) -> str | None:
    match = _DATE_EXPRESSIONS.search(text)
    return match.group(0) if match else None


def _description(
    segment: str, keyword: str | None, merchant: str | None, category_slug: str | None
) -> str | None:
    if match := _DESCRIPTION.search(segment):
        words = match.group("d").strip()
        if words and not _DATE_EXPRESSIONS.fullmatch(words):
            return words.title()[:80]
    if keyword:
        return keyword.title()
    if merchant:
        return merchant
    if category_slug and (definition := system_category(category_slug)):
        return definition.name
    return None


def _choose_amount(mentions: list[AmountMention]) -> AmountMention:
    marked = [m for m in mentions if m.has_marker]
    return marked[0] if marked else mentions[0]


def _segments(text: str) -> list[str]:
    """Split "200 on lunch and 100 on coffee" into one segment per amount."""
    segments: list[str] = []
    prefix = ""
    for part in _SEGMENT_SPLIT.split(text):
        if not part:
            continue
        if find_amounts(_strip_dates(part)):
            segments.append(f"{prefix} {part}".strip() if not segments else part)
            prefix = ""
        elif segments:
            segments[-1] = f"{segments[-1]} {part}"
        else:
            prefix = f"{prefix} {part}".strip()
    return segments


def _strip_dates(text: str) -> str:
    return _DATE_EXPRESSIONS.sub(" ", text)


def extract_transactions(text: str, today: date, locale: str) -> list[ExtractedTransaction]:
    global_date = find_date_expression(text)
    global_type = detect_type(text)
    global_payment = detect_payment_method(text)
    day_first = day_first_for_locale(locale)
    results: list[ExtractedTransaction] = []
    for segment in _segments(text)[:10]:
        mentions = find_amounts(_strip_dates(segment))
        if not mentions:
            continue
        mention = _choose_amount(mentions)
        kind = detect_type(segment) or global_type
        found = infer_category(segment, kind)
        category, keyword = (found[0].slug, found[1]) if found else (None, None)
        if kind is None and found is not None:
            kind = found[0].kind  # "uber 220" -> transport -> an expense
        date_text = find_date_expression(segment) or global_date
        resolved = resolve_date_expression(date_text, today, day_first=day_first) if date_text else None
        merchant = detect_merchant(segment)
        results.append(
            ExtractedTransaction(
                type=kind,
                amount=_plain(mention.value),
                currency=mention.currency,
                category=category,
                date_text=date_text,
                date=resolved.isoformat() if resolved else None,
                description=_description(segment, keyword, merchant, category),
                merchant=merchant,
                payment_method=detect_payment_method(segment) or global_payment,  # type: ignore[arg-type]
            )
        )
    return results


def extract_period(text: str, today: date) -> PeriodSpec:
    t = text.lower()
    if re.search(r"\byesterday\b", t):
        return PeriodSpec(kind="yesterday")
    if re.search(r"\btoday\b", t):
        return PeriodSpec(kind="today")
    if match := re.search(r"\b(?:last|past|previous)\s+(\d{1,3})\s+days\b", t):
        return PeriodSpec(kind="last_n_days", days=int(match.group(1)))
    if re.search(r"\b(?:last|past|previous)\s+week\b", t):
        return PeriodSpec(kind="last_week")
    if re.search(r"\bthis\s+week\b", t):
        return PeriodSpec(kind="this_week")
    if re.search(r"\b(?:last|previous)\s+month\b", t):
        return PeriodSpec(kind="last_month")
    if re.search(r"\b(?:last|previous)\s+year\b", t):
        return PeriodSpec(kind="last_year")
    if re.search(r"\bthis\s+year\b", t):
        return PeriodSpec(kind="this_year")
    if match := re.search(rf"\b({_MONTH_ALT})\b(?:\s+(\d{{4}}))?", t):
        month = MONTHS[match.group(1)]
        if match.group(1) != "may" or match.group(2) or re.search(r"\b(in|for|during)\s+may\b", t):
            year = int(match.group(2)) if match.group(2) else (
                today.year if month <= today.month else today.year - 1
            )
            return PeriodSpec(kind="month", month=f"{year:04d}-{month:02d}")
    return PeriodSpec(kind="this_month")


def extract_search(text: str) -> SearchSpec:
    t = text.lower()
    kind: CategoryKind | None = None
    if re.search(r"\b(income|earned|received|salary)\b", t):
        kind = "income"
    elif re.search(r"\b(expenses?|spent|spending|spends|purchases?|payments?|bills?)\b", t):
        kind = "expense"
    top = _TOP_N.search(t)
    merchant = detect_merchant(text)
    return SearchSpec(
        type=kind,
        category=infer_category_slug(text, kind),
        text=merchant,
        sort="largest" if _LARGEST.search(t) else "recent",
        limit=int(top.group(1)) if top else (1 if _LARGEST.search(t) and "expenses" not in t else None),
    )


def classify(text: str) -> Intent:
    stripped = text.strip()
    has_amount = bool(find_amounts(_strip_dates(stripped)))
    question = stripped.endswith("?") or bool(re.match(r"^(how|what|which|where|when|show|list)\b", stripped, _I))
    if _SEARCH.search(stripped) and not (has_amount and not question):
        return "search_transactions"
    if _SUMMARY.search(stripped) and not (has_amount and not question):
        return "spending_summary"
    if has_amount:
        return "record_transactions"
    if _SMALLTALK.search(stripped):
        return "smalltalk"
    return "help"


class RulesLLMClient:
    name = "rules"

    async def understand(self, request: UnderstandRequest) -> UnderstandResult:
        started = time.perf_counter()
        intent = classify(request.text)
        understanding = TurnUnderstanding(intent=intent)
        if intent == "record_transactions":
            understanding.transactions = extract_transactions(
                request.text, request.today, request.locale
            )
        elif intent in ("spending_summary", "search_transactions"):
            understanding.period = extract_period(request.text, request.today)
            understanding.search = extract_search(request.text)
        if request.pending is not None:
            # The workflow already tried a deterministic parse of the answer; if we are
            # here, treat the message as a new request.
            understanding.pending_answer = None
        return UnderstandResult(
            understanding=understanding,
            source="rules",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def stream_reply(self, request: ReplyRequest) -> AsyncIterator[str]:
        text = _REPLIES.get(request.kind, _REPLIES["help"])
        for word in re.findall(r"\S+\s*", text):
            yield word
            await asyncio.sleep(0)
