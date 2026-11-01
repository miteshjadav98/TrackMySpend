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
from collections.abc import AsyncIterator, Sequence
from datetime import date
from decimal import Decimal

from finance_core.accounts.names import could_mean_an_account
from finance_core.categories.defaults import (
    CategoryKind,
    infer_category,
    infer_category_slug,
    system_category,
)
from finance_core.dates import MONTHS, WEEKDAYS, day_first_for_locale, resolve_date_expression
from finance_core.llm.base import ReplyRequest, UnderstandRequest, UnderstandResult
from finance_core.llm.schemas import (
    ExtractedShare,
    ExtractedTransaction,
    Intent,
    PeriodSpec,
    SearchSpec,
    SettlementSpec,
    TurnUnderstanding,
)
from finance_core.llm.settling import read_balance_question, read_paying_back
from finance_core.llm.sharing import Sharing, read_sharing
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
    r"payments?|purchases?|income|entries|orders?|bills?|transfers?)\b"
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

# Transfers between the user's own accounts. An account name is one to four words that
# stop at the next keyword, a date, an amount or punctuation.
_ACCOUNT_NAME = r"(?P<{group}>[A-Za-z][\w&'.-]*(?:\s+(?!{stop}\b)[A-Za-z][\w&'.-]*){{0,3}})"
_ACCOUNT_STOP = (
    r"(?:to|into|from|on|via|using|with|by|for|at|in|and|today|yesterday|tonight|last|this|"
    r"ago|account|a/c|atm)"
)
_FROM_ACCOUNT = re.compile(
    r"\bfrom\s+(?:my\s+)?" + _ACCOUNT_NAME.format(group="name", stop=_ACCOUNT_STOP), _I
)
_TO_ACCOUNT = re.compile(
    r"\b(?:to|into)\s+(?:my\s+)?" + _ACCOUNT_NAME.format(group="name", stop=_ACCOUNT_STOP), _I
)
# Only for expenses and income, and only when the name is one of the user's accounts:
# "using my SBI account", "on ICICI account".
_USING_ACCOUNT = re.compile(
    r"\b(?:using|via|with|through|on)\s+(?:my\s+)?"
    + _ACCOUNT_NAME.format(group="name", stop=_ACCOUNT_STOP),
    _I,
)
_MOVED = re.compile(r"\b(transfer|transferred|transferring|moved|move|moving)\b", _I)
_WITHDREW = re.compile(r"\b(withdrew|withdrawn|withdraw|withdrawal|atm)\b", _I)
# "sent" is a transfer only when both ends are named: "sent 500 to Ramesh" is a payment.
_SENT = re.compile(r"\b(sent|send|sending)\b", _I)
_CARD_BILL = re.compile(r"\b(credit\s*card|cc)\s+(bill|dues?|payment)\b", _I)
# Trailing words that belong to the phrase, not the name: "from HDFC account".
_NAME_TAIL = re.compile(r"\s+(account|a/c|acc|bank account)$", _I)

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


def item_segment(text: str, amount: Decimal) -> str:
    """The part of a multi-item message that holds this amount: "swiggy 300" out of
    "swiggy 300 and dinner food 400". The whole text when it is one item or nothing fits."""
    segments = _segments(text)
    if len(segments) < 2:
        return text
    for segment in segments:
        if any(m.value == amount for m in find_amounts(_strip_dates(segment))):
            return segment
    return text


def _strip_dates(text: str) -> str:
    return _DATE_EXPRESSIONS.sub(" ", text)


def _account_after(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(_strip_dates(text))
    if match is None:
        return None
    name = _NAME_TAIL.sub("", match.group("name").strip())
    return name or None


def detect_transfer(segment: str) -> tuple[str | None, str | None, str] | None:
    """(from account, to account, description) when the segment moves money between the
    user's own accounts; None for anything else, so "electricity bill 1200" stays an expense.
    """
    source = _account_after(_FROM_ACCOUNT, segment)
    if _CARD_BILL.search(segment):
        return source, "Credit card", "Credit Card Bill"
    if _WITHDREW.search(segment):
        return source, "Cash", "Cash Withdrawal"
    target = _account_after(_TO_ACCOUNT, segment)
    if _MOVED.search(segment) or (_SENT.search(segment) and source and target):
        return source, target, "Transfer"
    return None


def _paid_from_account(segment: str, account_names: Sequence[str]) -> tuple[str, str] | None:
    """(account as written, the phrase that named it) for "from HDFC" / "into HDFC" when the
    name is one of the user's accounts; None otherwise, so "from Nike" stays a merchant."""
    stripped = _strip_dates(segment)
    for pattern in (_FROM_ACCOUNT, _TO_ACCOUNT, _USING_ACCOUNT):
        for match in pattern.finditer(stripped):
            name = _NAME_TAIL.sub("", match.group("name").strip())
            if name and could_mean_an_account(name, account_names):
                return name, match.group(0)
    return None


def _shared_expense(
    text: str, sharing: Sharing, today: date, locale: str, account_names: Sequence[str]
) -> ExtractedTransaction:
    """One expense shared with friends, from a message that is entirely about the sharing."""
    # The total is the first amount that is not someone's own share ("1000" in "dinner 1000
    # with Jaymin, I had 400 and he had 600").
    in_shares = {(m.start, m.end) for m in sharing.share_mentions}
    totals = [m for m in find_amounts(_strip_dates(text)) if (m.start, m.end) not in in_shares]
    mention = _choose_amount(totals) if totals else None
    date_text = find_date_expression(text)
    resolved = (
        resolve_date_expression(date_text, today, day_first=day_first_for_locale(locale))
        if date_text
        else None
    )
    found = infer_category(text, "expense")
    category, keyword = (found[0].slug, found[1]) if found else (None, None)
    paid_from = _paid_from_account(text, account_names)
    merchant = detect_merchant(text)
    if merchant and merchant.casefold() in {p.casefold() for p in sharing.participants}:
        merchant = None
    return ExtractedTransaction(
        type="expense",
        amount=_plain(mention.value) if mention else None,
        currency=mention.currency if mention else None,
        category=category,
        date_text=date_text,
        date=resolved.isoformat() if resolved else None,
        description=_description(text, keyword, merchant, category),
        merchant=merchant,
        payment_method=detect_payment_method(text),
        account=paid_from[0] if paid_from else None,
        participants=sharing.participants,
        payer=sharing.payer,
        split=sharing.split,
        shares=[
            ExtractedShare(person=person, amount=_plain(amount))
            for person, amount in sharing.shares
        ],
    )


def extract_transactions(
    text: str,
    today: date,
    locale: str,
    account_names: Sequence[str] = (),
    friend_names: Sequence[str] = (),
) -> list[ExtractedTransaction]:
    if sharing := read_sharing(text, friend_names):
        return [_shared_expense(text, sharing, today, locale, account_names)]
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
        date_text = find_date_expression(segment) or global_date
        resolved = (
            resolve_date_expression(date_text, today, day_first=day_first) if date_text else None
        )
        if transfer := detect_transfer(segment):
            source, target, label = transfer
            # A transfer has no category, merchant or payment method: only its two accounts.
            results.append(
                ExtractedTransaction(
                    type="transfer",
                    amount=_plain(mention.value),
                    currency=mention.currency,
                    date_text=date_text,
                    date=resolved.isoformat() if resolved else None,
                    description=label,
                    account=source,
                    to_account=target,
                )
            )
            continue
        kind = detect_type(segment) or global_type
        found = infer_category(segment, kind)
        category, keyword = (found[0].slug, found[1]) if found else (None, None)
        if kind is None and found is not None:
            kind = found[0].kind  # "uber 220" -> transport -> an expense
        # "from HDFC" naming one of the user's accounts is the account, never the merchant.
        paid_from = _paid_from_account(segment, account_names)
        without_account = (
            re.sub(re.escape(paid_from[1]), " ", segment, flags=_I) if paid_from else segment
        )
        merchant = detect_merchant(without_account)
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
                payment_method=detect_payment_method(segment) or global_payment,
                account=paid_from[0] if paid_from else None,
            )
        )
    return results


def extract_settlement(
    text: str,
    today: date,
    locale: str,
    account_names: Sequence[str] = (),
    friend_names: Sequence[str] = (),
) -> SettlementSpec | None:
    """The settlement in `text` with its account and date, or None if it is not one.

    A message that splits a bill is a shared expense, even when it says "Jaymin paid me".
    """
    if read_sharing(text, friend_names):
        return None
    found = read_paying_back(text, friend_names)
    if found is None:
        return None
    date_text = find_date_expression(text)
    resolved = (
        resolve_date_expression(date_text, today, day_first=day_first_for_locale(locale))
        if date_text
        else None
    )
    account = _paid_from_account(text, account_names)
    return SettlementSpec(
        friend=found.friend,
        direction=found.direction,
        amount=_plain(found.amount),
        currency=found.currency,
        purpose=found.purpose,
        account=account[0] if account else None,
        date_text=date_text,
        date=resolved.isoformat() if resolved else None,
    )


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
            year = (
                int(match.group(2))
                if match.group(2)
                else (today.year if month <= today.month else today.year - 1)
            )
            return PeriodSpec(kind="month", month=f"{year:04d}-{month:02d}")
    return PeriodSpec(kind="this_month")


def extract_search(text: str) -> SearchSpec:
    t = text.lower()
    if re.search(r"\btransfers?\b", t):
        # A transfer has no category, and its accounts are not a merchant to match.
        return SearchSpec(
            type="transfer", sort="largest" if _LARGEST.search(t) else "recent", limit=None
        )
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
        shared=bool(re.search(r"\bshared\b", t)),
        limit=int(top.group(1))
        if top
        else (1 if _LARGEST.search(t) and "expenses" not in t else None),
    )


def classify(text: str) -> Intent:
    stripped = text.strip()
    has_amount = bool(find_amounts(_strip_dates(stripped)))
    question = stripped.endswith("?") or bool(
        re.match(r"^(how|what|which|where|when|show|list)\b", stripped, _I)
    )
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
        settlement = extract_settlement(
            request.text, request.today, request.locale, request.accounts, request.friends
        )
        balance = read_balance_question(request.text, request.friends)
        intent = (
            "balance_question"
            if balance
            else "record_settlement"
            if settlement
            else classify(request.text)
        )
        understanding = TurnUnderstanding(intent=intent)
        if intent == "balance_question":
            understanding.balance = balance
        elif intent == "record_settlement":
            understanding.settlement = settlement
        elif intent == "record_transactions":
            understanding.transactions = extract_transactions(
                request.text, request.today, request.locale, request.accounts, request.friends
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
