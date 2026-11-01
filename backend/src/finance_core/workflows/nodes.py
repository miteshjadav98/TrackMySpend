"""Graph nodes. Each node has one job and one reason to fail.

Database sessions are opened per node and closed before any model call, so a slow LLM
never holds a pooled connection. The only side-effecting node (`save`) is idempotent.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from finance_core.accounts.names import infer_account_kind, resolve_account_name
from finance_core.accounts.schemas import AccountCreate, AccountView
from finance_core.accounts.service import AccountService
from finance_core.categories.defaults import FALLBACK_SLUG, FALLBACK_SLUGS
from finance_core.categories.models import Category
from finance_core.categories.schemas import CategoryCreate
from finance_core.categories.service import CategoryService
from finance_core.conversations.service import HistoryItem
from finance_core.dates import DateRange, PeriodError, resolve_period
from finance_core.errors import ConflictError, NotFoundError, ValidationFailedError
from finance_core.friends.names import matching_friends
from finance_core.friends.schemas import (
    BalanceView,
    FriendCreate,
    FriendView,
    ParticipantInput,
    SettlementCreate,
    SharedExpenseCreate,
    SharedExpenseView,
)
from finance_core.friends.service import FriendService
from finance_core.friends.settlements import SettlementService
from finance_core.friends.shared_expenses import SharedExpenseService
from finance_core.ids import derived_id
from finance_core.llm.base import (
    CategoryHint,
    LLMUnavailableError,
    PendingQuestion,
    ReplyRequest,
    UnderstandRequest,
)
from finance_core.llm.rules import RulesLLMClient
from finance_core.llm.schemas import BalanceSpec, PeriodSpec, SearchSpec, SettlementSpec
from finance_core.merchants.service import MerchantRuleService
from finance_core.reports.service import ReportService
from finance_core.transactions.schemas import TransactionCreate, TransactionQuery, TransactionView
from finance_core.transactions.service import TransactionService
from finance_core.workflows.answers import AnswerApplier, AnswerOutcome, pending_field
from finance_core.workflows.category_choice import CategoryOption, choose_category
from finance_core.workflows.drafts import (
    TransactionDraft,
    draft_from_extraction,
    first_issue,
    merge_repeated_people,
)
from finance_core.workflows.friend_replies import (
    compose_balances,
    compose_settlement_saved,
    compose_unclear_balance_question,
    compose_unclear_settlement,
)
from finance_core.workflows.questions import build_question
from finance_core.workflows.reconcile import reconcile
from finance_core.workflows.replies import (
    STATIC_REPLIES,
    compose_saved,
    compose_search,
    compose_summary,
    reply_is_grounded,
    suggestions_for,
)
from finance_core.workflows.settling import choose_settlement, expense_from_settlement
from finance_core.workflows.state import (
    AgentDeps,
    FinanceState,
    HistoryEntry,
    TurnContext,
    status_event,
    text_event,
)

logger = logging.getLogger(__name__)

MAX_DRAFTS = 10
MAX_SEARCH_RESULTS = 20
# Per-turn keys cleared whenever a new request starts.
_TURN_RESET: dict[str, Any] = {
    "drafts": [],
    "pending": None,
    "rounds": 0,
    "notice": None,
    "followup": None,
    "abandoned": False,
    "period": None,
    "search": None,
    "outcome": None,
    "saved": [],
    "filed_by_merchant_rule": [],
    "unmatched_accounts": [],
    "shared_saved": [],
    "added_friends": [],
    "settlement": None,
    "settlement_saved": None,
    "balance": None,
    "balance_answer": None,
    "friend_question": None,
    "summary": None,
    "results": None,
    "reply": None,
}


def _drafts(state: FinanceState) -> list[TransactionDraft]:
    return [TransactionDraft.model_validate(item) for item in state.get("drafts") or []]


def _dump(drafts: list[TransactionDraft]) -> list[dict[str, Any]]:
    return [draft.model_dump(mode="json") for draft in drafts]


def _history(entries: list[HistoryEntry], limit: int) -> list[HistoryItem]:
    items = [HistoryItem(role=e["role"], text=e["text"]) for e in entries if e.get("text")]
    return items[-limit:] if limit else []


def _option(category: Category | None) -> CategoryOption | None:
    if category is None:
        return None
    return CategoryOption(
        id=str(category.id), name=category.name, is_fallback=category.slug in FALLBACK_SLUGS
    )


def _picked(draft: TransactionDraft) -> CategoryOption | None:
    """The category the user picked in a clarification, if they did."""
    if draft.category_source != "picked" or draft.category_id is None:
        return None
    return CategoryOption(id=draft.category_id, name=draft.category_name or "")


async def _file_under_category(
    draft: TransactionDraft,
    user_id: uuid.UUID,
    categories: CategoryService,
    merchant_rules: MerchantRuleService,
) -> TransactionDraft:
    """The draft filed under the category the precedence chooses; unchanged if none applies.

    Worked out again on every pass, so a pick from a clarification stands because it
    outranks everything else.
    """
    # The type comes first; a typed new category or a skipped question is already the
    # user's answer.
    # A transfer has no category, and no merchant to look a rule up by.
    if (
        draft.type is None
        or draft.type == "transfer"
        or draft.category_text
        or draft.category_skipped
    ):
        return draft
    suggested = (
        await categories.by_slug(user_id, draft.category_slug, draft.type)
        if draft.category_slug
        else None
    )
    rule = await merchant_rules.category_for(user_id, type=draft.type, merchant=draft.merchant)
    choice = choose_category(
        draft.item_text or draft.source_text,
        picked=_picked(draft),
        suggested=_option(suggested),
        merchant_rule=_option(rule),
        merchant=draft.merchant,
    )
    if choice is None:
        return draft
    return draft.model_copy(
        update={
            "category_id": choice.category.id,
            "category_name": choice.category.name,
            "category_source": choice.source,
        }
    )


def _with_accounts_resolved(
    draft: TransactionDraft, accounts: list[AccountView]
) -> TransactionDraft:
    """The account names the user said, matched to their active accounts.

    A transfer whose name matches none or several is left alone, so the draft asks which one
    is meant. An expense or income is only tagged when the name means exactly one account;
    otherwise it is saved untagged and the reply says so, because the chat never asks.
    An end the user already answered (picked, or typed as a new account) is never touched.
    """
    if draft.type != "transfer":
        found = resolve_account_name(draft.account, accounts) if draft.account else None
        if found is None or draft.account_id:
            return draft
        return draft.model_copy(update={"account_id": str(found.id), "account_name": found.name})
    updates: dict[str, Any] = {}
    for prefix, said in (("account", draft.account), ("to_account", draft.to_account)):
        answered = getattr(draft, f"{prefix}_id") or getattr(draft, f"{prefix}_new")
        found = resolve_account_name(said, accounts) if said and not answered else None
        if found is not None:
            updates[f"{prefix}_id"] = str(found.id)
            updates[f"{prefix}_name"] = found.name
    return draft.model_copy(update=updates) if updates else draft


def _with_friends_resolved(draft: TransactionDraft, friends: list[FriendView]) -> TransactionDraft:
    """The friends a shared expense names, matched to the user's friends.

    A name matching exactly one friend is settled. A name matching several is marked ambiguous
    and one matching none is left alone, so the draft asks. A name the user already answered
    (picked, or agreed to add) is never touched.
    """
    if not draft.is_shared():
        return draft
    people = []
    for said in draft.people:
        person = said
        matches = [] if said.is_resolved() else matching_friends(said.said, friends)
        if len(matches) == 1:
            person = said.model_copy(
                update={"friend_id": str(matches[0].id), "name": matches[0].name}
            )
        elif not said.is_resolved():
            person = said.model_copy(update={"ambiguous": len(matches) > 1})
        people.append(person)
    return draft.model_copy(update={"people": merge_repeated_people(people)})


class _CannotSave(Exception):
    """A transfer that cannot be saved, with the reply outcome that explains why."""

    def __init__(self, outcome: str) -> None:
        super().__init__(outcome)
        self.outcome = outcome


def _currency_for_new_ends(draft: TransactionDraft, active: dict[str, AccountView]) -> str | None:
    """The currency a transfer's new account takes, checking the existing ends agree with it.

    A new end follows the existing one, so "moved $100 from Wise to Revolut" opens Revolut in
    USD. None means the user's base currency. Raises before anything is created, so a transfer
    that cannot be saved leaves no account behind.
    """
    existing = [
        active[account_id]
        for account_id in (draft.account_id, draft.to_account_id)
        if account_id and account_id in active
    ]
    wanted = draft.currency.upper() if draft.currency else None
    if wanted is None and existing:
        wanted = existing[0].currency
    if any(account.currency != wanted for account in existing):
        raise _CannotSave("transfer_currency_mismatch")
    return wanted


async def _account_for_save(
    accounts: AccountService,
    ctx: TurnContext,
    account_id: str | None,
    new_name: str | None,
    currency: str | None,
) -> uuid.UUID | None:
    """The account a transfer end points at, creating the one the user typed if it is new.

    The new account is only flushed, so it commits (or rolls back) together with the transfer.
    """
    if account_id:
        return uuid.UUID(account_id)
    if not new_name:
        return None
    try:
        created = await accounts.create(
            ctx.user,
            AccountCreate(name=new_name, kind=infer_account_kind(new_name), currency=currency),
            request_id=ctx.request_id,
            commit=False,
        )
        return created.id
    except ConflictError:
        # Created meanwhile, or the same name was typed twice: use the one that exists.
        existing = resolve_account_name(new_name, await accounts.list_accounts(ctx.user))
        return existing.id if existing else None
    except ValidationFailedError:
        # The currency is already known to be supported, so what is left is the account limit.
        raise _CannotSave("account_limit") from None


def _unmatched_accounts(drafts: list[TransactionDraft]) -> list[str]:
    """Account names the user said for an expense or income that matched none of their accounts."""
    return [
        draft.account
        for draft in drafts
        if draft.type != "transfer" and draft.account and not draft.account_id
    ]


def _filed_by_merchant_rule(
    drafts: list[TransactionDraft], views: list[TransactionView]
) -> list[str]:
    """Ids of the saved transactions whose category a merchant rule chose, for the reply."""
    if len(drafts) != len(views):
        return []  # a replayed save that no longer lines up with its drafts: skip the note
    return [
        str(view.id)
        for draft, view in zip(drafts, views, strict=True)
        if draft.category_source == "merchant_rule"
    ]


class FinanceNodes:
    def __init__(self, deps: AgentDeps) -> None:
        self._deps = deps

    # -- understand -----------------------------------------------------------------------

    async def understand(self, state: FinanceState, runtime: Runtime[TurnContext]) -> Command[str]:
        ctx = runtime.context
        settings = self._deps.settings
        runtime.stream_writer(status_event("understanding", "Reading your message…"))
        text = (state.get("user_text") or "")[: settings.agent_max_input_chars]
        followup = state.get("followup")

        history = list(state.get("history") or [])
        if followup:
            # Show the model the exchange it is following up on.
            if followup.get("previousText"):
                history.append({"role": "user", "text": followup["previousText"]})
            history.append({"role": "assistant", "text": followup.get("message") or ""})

        async with self._deps.session_factory() as session:
            categories = await CategoryService(session).list_visible(ctx.user_id)
            accounts = await AccountService(session).list_accounts(ctx.user)
            friends = await FriendService(session).list_friends(ctx.user)
        request = UnderstandRequest(
            text=text,
            today=ctx.today,
            timezone=ctx.timezone,
            base_currency=ctx.base_currency,
            locale=ctx.locale,
            categories=[CategoryHint(c.slug, c.name, c.kind) for c in categories],
            accounts=[account.name for account in accounts],
            friends=[friend.name for friend in friends],
            history=_history(history, settings.agent_history_window),
            pending=(
                PendingQuestion(
                    field=followup.get("fieldKey", ""),
                    message=followup.get("message", ""),
                    options=tuple(followup.get("options") or ()),
                )
                if followup
                else None
            ),
        )
        try:
            result = await self._deps.llm.understand(request)
        except LLMUnavailableError:
            return Command(
                goto="respond",
                update={
                    **_TURN_RESET,
                    "intent": "unavailable",
                    "outcome": "llm_unavailable",
                    "last_message_id": state.get("message_id"),
                },
            )
        understanding = result.understanding
        if result.source != "rules":
            understanding = reconcile(
                understanding,
                text,
                today=ctx.today,
                locale=ctx.locale,
                account_names=request.accounts,
                friend_names=request.friends,
            )
        meta = {
            "intent": understanding.intent,
            "source": result.source,
            "degraded": result.degraded,
            "last_message_id": state.get("message_id"),
        }
        logger.info(
            "turn understood",
            extra={
                "intent": understanding.intent,
                "llmSource": result.source,
                "degraded": result.degraded,
            },
        )

        if followup:
            answer = understanding.pending_answer
            drafts = _drafts(state)
            index = int(followup.get("draftIndex", 0))
            if answer and answer.answers_question and answer.value and 0 <= index < len(drafts):
                outcome = await self._apply_followup_answer(
                    ctx, followup, answer.value, drafts[index]
                )
                if outcome.kind == "applied" and outcome.draft is not None:
                    drafts[index] = outcome.draft
                return Command(
                    goto="prepare_record",
                    update={
                        **meta,
                        "intent": "record_transactions",
                        "drafts": _dump(drafts),
                        "followup": None,
                        "notice": outcome.notice if outcome.kind == "invalid" else None,
                    },
                )

        update: dict[str, Any] = {
            **_TURN_RESET,
            **meta,
            "abandoned": bool(followup and state.get("drafts")),
        }
        intent = understanding.intent
        if intent == "record_transactions":
            message_id = state.get("message_id") or ""
            drafts = [
                draft_from_extraction(
                    extracted,
                    draft_id=str(derived_id(message_id, index)),
                    origin_message_id=message_id,
                    source_text=text,
                    today=ctx.today,
                    locale=ctx.locale,
                )
                for index, extracted in enumerate(understanding.transactions[:MAX_DRAFTS])
            ]
            if not drafts:
                return Command(goto="respond", update={**update, "outcome": "nothing_to_record"})
            return Command(goto="prepare_record", update={**update, "drafts": _dump(drafts)})
        if intent == "record_settlement":
            return self._route_settlement(
                understanding.settlement, update, friends, text, ctx, state.get("message_id") or ""
            )
        if intent == "balance_question":
            update["balance"] = (understanding.balance or BalanceSpec()).model_dump()
            return Command(goto="balances", update=update)
        if intent in ("spending_summary", "search_transactions"):
            update["period"] = (understanding.period or PeriodSpec()).model_dump()
            update["search"] = understanding.search.model_dump() if understanding.search else None
            return Command(
                goto="summarize" if intent == "spending_summary" else "search", update=update
            )
        return Command(goto="respond", update=update)

    @staticmethod
    def _route_settlement(
        spec: SettlementSpec | None,
        update: dict[str, Any],
        friends: list[FriendView],
        text: str,
        ctx: TurnContext,
        message_id: str,
    ) -> Command[str]:
        """Send a settlement message to be recorded, to be asked about, or on as an expense."""
        if spec is None:
            return Command(goto="respond", update={**update, "outcome": "nothing_to_record"})
        choice = choose_settlement(spec, friends, ctx.base_currency)
        if choice.kind == "ask":
            ask = {"reason": choice.reason, "name": spec.friend or "", "options": choice.options}
            return Command(
                goto="respond",
                update={**update, "outcome": "settlement_unclear", "friend_question": ask},
            )
        if choice.kind == "expense":
            draft = draft_from_extraction(
                expense_from_settlement(spec),
                draft_id=str(derived_id(message_id, 0)),
                origin_message_id=message_id,
                source_text=text,
                today=ctx.today,
                locale=ctx.locale,
            )
            return Command(goto="prepare_record", update={**update, "drafts": _dump([draft])})
        assert choice.friend is not None
        planned = {
            **spec.model_dump(),
            "friend_id": str(choice.friend.id),
            "friend": choice.friend.name,
        }
        return Command(goto="settle", update={**update, "settlement": planned})

    async def _apply_followup_answer(
        self, ctx: TurnContext, followup: dict[str, Any], value: str, draft: TransactionDraft
    ) -> AnswerOutcome:
        field = followup.get("fieldKey", "")
        if field == "amount_confirm":
            confirmed = value.strip().lower() in ("yes", "y", "true", "confirm")
            if confirmed:
                return AnswerOutcome(
                    "applied", draft=draft.model_copy(update={"amount_confirmed": True})
                )
            return AnswerOutcome(
                "applied",
                draft=draft.model_copy(update={"amount": None, "amount_confirmed": False}),
            )
        async with self._deps.session_factory() as session:
            applier = AnswerApplier(
                CategoryService(session),
                user_id=ctx.user_id,
                today=ctx.today,
                locale=ctx.locale,
                accounts=await AccountService(session).list_accounts(ctx.user),
                friends=await FriendService(session).list_friends(ctx.user),
            )
            return await applier.apply_value(
                field, value, draft, allow_custom=bool(followup.get("allowCustom"))
            )

    # -- record workflow ------------------------------------------------------------------

    async def prepare_record(
        self, state: FinanceState, runtime: Runtime[TurnContext]
    ) -> Command[str]:
        ctx = runtime.context
        settings = self._deps.settings
        drafts = _drafts(state)
        if not drafts:
            return Command(goto="respond", update={"outcome": "nothing_to_record"})
        rounds = int(state.get("rounds") or 0)

        async with self._deps.session_factory() as session:
            categories = CategoryService(session)
            merchant_rules = MerchantRuleService(session, clock=self._deps.clock)
            account_service = AccountService(session)
            active_accounts = await account_service.list_accounts(ctx.user)
            friends = await FriendService(session).list_friends(ctx.user)
            for index, draft in enumerate(drafts):
                drafts[index] = await _file_under_category(
                    _with_friends_resolved(
                        _with_accounts_resolved(draft, active_accounts), friends
                    ),
                    ctx.user_id,
                    categories,
                    merchant_rules,
                )

            for index, draft in enumerate(drafts):
                issue = first_issue(draft, base_currency=ctx.base_currency, today=ctx.today)
                if issue is None:
                    continue
                if rounds >= settings.agent_max_clarification_rounds:
                    return Command(
                        goto="respond", update={"drafts": [], "pending": None, "outcome": "gave_up"}
                    )
                options = (
                    await categories.ranked_for_choice(
                        ctx.user_id, "income" if draft.type == "income" else "expense", ctx.today
                    )
                    if issue.field == "category"
                    else []
                )
                question = build_question(
                    issue,
                    draft,
                    draft_index=index,
                    draft_count=len(drafts),
                    round_number=rounds,
                    base_currency=ctx.base_currency,
                    locale=ctx.locale,
                    today=ctx.today,
                    category_options=options,
                    account_options=(
                        await account_service.ranked_for_choice(ctx.user)
                        if issue.field in ("account", "to_account")
                        else None
                    ),
                    friend_options=friends,
                    notice=state.get("notice"),
                )
                return Command(
                    goto="clarify",
                    update={
                        "drafts": _dump(drafts),
                        "pending": question.model_dump(mode="json", by_alias=True),
                        "notice": None,
                    },
                )
        return Command(
            goto="save", update={"drafts": _dump(drafts), "pending": None, "notice": None}
        )

    async def clarify(self, state: FinanceState, runtime: Runtime[TurnContext]) -> Command[str]:
        pending = state.get("pending") or {}
        # Pauses the run and surfaces `pending` to the client. On resume the node re-runs
        # from the top and `interrupt` returns the user's answer instead. Nothing with a
        # side effect happens before this line.
        resume = interrupt(pending)

        ctx = runtime.context
        payload = resume if isinstance(resume, dict) else {}
        processed = {"last_message_id": payload.get("messageId") or state.get("last_message_id")}
        rounds = int(state.get("rounds") or 0) + 1
        drafts = _drafts(state)
        index = int(pending.get("draftIndex", 0))
        if not 0 <= index < len(drafts):
            return Command(
                goto="prepare_record", update={"pending": None, "rounds": rounds, **processed}
            )

        async with self._deps.session_factory() as session:
            applier = AnswerApplier(
                CategoryService(session),
                user_id=ctx.user_id,
                today=ctx.today,
                locale=ctx.locale,
                accounts=await AccountService(session).list_accounts(ctx.user),
                friends=await FriendService(session).list_friends(ctx.user),
            )
            if payload.get("kind") == "text":
                outcome = await applier.from_text(
                    pending, str(payload.get("text", "")), drafts[index]
                )
            elif payload.get("kind") == "response":
                outcome = await applier.from_response(pending, payload, drafts[index])
            else:
                outcome = AnswerOutcome("invalid", notice="Sorry, I didn't get that.")

        if outcome.kind == "not_an_answer":
            # Let the model decide: an answer in other words, or a new request entirely.
            return Command(
                goto="understand",
                update={
                    "user_text": str(payload.get("text", "")),
                    "message_id": payload.get("messageId") or state.get("message_id"),
                    "followup": {
                        "fieldKey": pending_field(pending),
                        "message": pending.get("message", ""),
                        "options": [o.get("value") for o in pending.get("options", [])],
                        "draftIndex": index,
                        "previousText": state.get("user_text"),
                        "allowCustom": bool(pending.get("allowCustomInput")),
                    },
                    "pending": None,
                    "rounds": rounds,
                },
            )
        if outcome.kind == "cancel_all":
            return Command(
                goto="respond",
                update={
                    "drafts": [],
                    "pending": None,
                    "rounds": rounds,
                    "outcome": "cancelled",
                    **processed,
                },
            )
        if outcome.kind == "applied" and outcome.draft is not None:
            drafts[index] = outcome.draft
        return Command(
            goto="prepare_record",
            update={
                "drafts": _dump(drafts),
                "pending": None,
                "rounds": rounds,
                "notice": outcome.notice,
                **processed,
            },
        )

    async def save(self, state: FinanceState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
        """Persist the completed drafts. Idempotent, so retries and replays are safe:
        - each draft has a deterministic id -> per-row idempotency key;
        - check-before-act on the originating message catches a re-extracted retry."""
        ctx = runtime.context
        runtime.stream_writer(status_event("saving", "Saving…"))
        drafts = _drafts(state)
        if not drafts:
            return {"outcome": "nothing_to_record"}
        source_ref = f"chat:{drafts[0].origin_message_id}"

        async with self._deps.session_factory() as session:
            transactions = TransactionService(
                session, clock=self._deps.clock, generation=self._deps.generation
            )
            shared_service = SharedExpenseService(
                session, clock=self._deps.clock, generation=self._deps.generation
            )
            shared_views: list[SharedExpenseView] = []
            added_friends: list[str] = []
            existing = await transactions.find_by_source_ref(ctx.user, source_ref)
            if existing:
                views = existing
                for shared_id in dict.fromkeys(v.shared_expense_id for v in existing):
                    if shared_id is not None:
                        shared_views.append(await shared_service.get(ctx.user, shared_id))
            else:
                categories = CategoryService(session)
                accounts = AccountService(session)
                items = []
                active = {str(a.id): a for a in await accounts.list_accounts(ctx.user)}
                for draft in drafts:
                    assert draft.type is not None and draft.amount is not None and draft.date
                    if draft.is_shared():
                        continue  # saved through the shared-expense service below
                    if draft.type == "transfer":
                        try:
                            new_end_currency = _currency_for_new_ends(draft, active)
                            data = TransactionCreate(
                                type="transfer",
                                amount=Decimal(draft.amount),
                                currency=draft.currency,
                                occurred_on=date.fromisoformat(draft.date),
                                description=draft.description,
                                account_id=await _account_for_save(
                                    accounts, ctx, draft.account_id, draft.account_name,
                                    new_end_currency,
                                ),
                                to_account_id=await _account_for_save(
                                    accounts, ctx, draft.to_account_id, draft.to_account_name,
                                    new_end_currency,
                                ),
                            )  # fmt: skip
                        except _CannotSave as stop:
                            return {"outcome": stop.outcome, "drafts": []}
                    else:
                        data = await self._expense_or_income(ctx, categories, draft)
                    try:
                        resolved = await transactions.resolve(ctx.user, data)
                    except ValidationFailedError:
                        logger.warning(
                            "draft failed validation at save", extra={"draftId": draft.id}
                        )
                        return {"outcome": "save_failed", "drafts": []}
                    items.append((resolved, f"chat:{draft.id}"))
                results = await transactions.create_resolved(
                    ctx.user,
                    items,
                    source="chat",
                    source_ref=source_ref,
                    actor="assistant",
                    request_id=ctx.request_id,
                )
                saved_by_draft = {
                    key.removeprefix("chat:"): view
                    for (_, key), (view, _) in zip(items, results, strict=True)
                }
                for draft in drafts:
                    if not draft.is_shared():
                        continue
                    try:
                        shared_view, added = await self._save_shared(
                            ctx, session, categories, shared_service, draft, source_ref
                        )
                    except (ValidationFailedError, NotFoundError):
                        logger.warning("shared draft failed at save", extra={"draftId": draft.id})
                        return {"outcome": "save_failed", "drafts": []}
                    shared_views.append(shared_view)
                    added_friends += added
                    assert shared_view.my_transaction_id is not None
                    saved_by_draft[draft.id] = await transactions.get(
                        ctx.user, shared_view.my_transaction_id
                    )
                views = [saved_by_draft[draft.id] for draft in drafts]  # in the order said
        return {
            "shared_saved": [v.model_dump(mode="json", by_alias=True) for v in shared_views],
            "added_friends": added_friends,
            "saved": [view.model_dump(mode="json", by_alias=True) for view in views],
            "filed_by_merchant_rule": _filed_by_merchant_rule(drafts, views),
            "unmatched_accounts": _unmatched_accounts(drafts),
            "drafts": [],
            "outcome": "saved",
        }

    async def _save_shared(
        self,
        ctx: TurnContext,
        session: Any,
        categories: CategoryService,
        shared_service: SharedExpenseService,
        draft: TransactionDraft,
        source_ref: str,
    ) -> tuple[SharedExpenseView, list[str]]:
        """Record a shared expense through the shared-expense service, adding the friends the
        user agreed to add. Returns it with the names of the friends added."""
        assert draft.amount is not None and draft.date
        friend_ids, added = await self._friend_ids_for(ctx, FriendService(session), draft)
        own = await self._expense_or_income(ctx, categories, draft)
        exact = draft.split == "exact"
        participants = [
            ParticipantInput(
                friend_id=None,
                amount=Decimal(draft.my_amount) if exact and draft.my_amount else None,
            ),
            *(
                ParticipantInput(
                    friend_id=friend_id,
                    amount=Decimal(person.amount) if exact and person.amount else None,
                )
                for friend_id, person in zip(friend_ids, draft.people, strict=True)
            ),
        ]
        payer = next(
            (fid for fid, person in zip(friend_ids, draft.people, strict=True) if person.paid),
            None,
        )
        view = await shared_service.create(
            ctx.user,
            SharedExpenseCreate(
                total=Decimal(draft.amount),
                currency=draft.currency,
                occurred_on=date.fromisoformat(draft.date),
                description=draft.description,
                merchant=draft.merchant,
                payer_friend_id=payer,
                split=draft.split,
                participants=participants,
                category_id=own.category_id,
                account_id=own.account_id,
            ),
            request_id=ctx.request_id,
            source="chat",
            source_ref=source_ref,
        )
        return view, added

    @staticmethod
    async def _friend_ids_for(
        ctx: TurnContext, friends: FriendService, draft: TransactionDraft
    ) -> tuple[list[uuid.UUID], list[str]]:
        """The friend behind each person in the draft, adding the ones the user agreed to add.

        A new friend is looked up by exact name first, so a retried save never adds them twice.
        """
        known = await friends.list_friends(ctx.user)
        ids: list[uuid.UUID] = []
        added: list[str] = []
        for person in draft.people:
            if person.friend_id:
                ids.append(uuid.UUID(person.friend_id))
                continue
            name = person.display_name()
            same = next((f for f in known if f.name.casefold() == name.casefold()), None)
            if same is None:
                created = FriendCreate(name=name)
                same = await friends.add(ctx.user, created, request_id=ctx.request_id)
                added.append(name)
            ids.append(same.id)
        return ids, added

    async def _expense_or_income(
        self, ctx: TurnContext, categories: CategoryService, draft: TransactionDraft
    ) -> TransactionCreate:
        """The create request for an expense or income, with its category settled."""
        assert draft.type in ("expense", "income") and draft.amount is not None and draft.date
        category_id = uuid.UUID(draft.category_id) if draft.category_id else None
        if category_id is None and draft.category_text:
            try:
                created = await categories.create(
                    ctx.user_id,
                    CategoryCreate(name=draft.category_text, kind=draft.type),
                    request_id=ctx.request_id,
                )
                category_id = created.id
            except (ConflictError, ValidationFailedError):
                matched = await categories.match(ctx.user_id, draft.category_text, draft.type)
                category_id = matched.id if matched else None
        if category_id is None:
            fallback = await categories.by_slug(ctx.user_id, FALLBACK_SLUG[draft.type], draft.type)
            category_id = fallback.id if fallback else None
        return TransactionCreate(
            type=draft.type,
            amount=Decimal(draft.amount),
            currency=draft.currency,
            occurred_on=date.fromisoformat(draft.date),
            category_id=category_id,
            account_id=uuid.UUID(draft.account_id) if draft.account_id else None,
            description=draft.description,
            merchant=draft.merchant,
            payment_method=draft.payment_method,
        )

    # -- settlements and balances ---------------------------------------------------------

    async def settle(self, state: FinanceState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
        """Record a settlement through the settlement service, tagged with an account if one
        was named. Not retried automatically: a settlement has no idempotency key, so a retry
        after a lost commit acknowledgement would record it twice."""
        ctx = runtime.context
        runtime.stream_writer(status_event("saving", "Saving…"))
        plan = state.get("settlement") or {}
        spec = SettlementSpec.model_validate(plan)
        paid_by_friend = spec.direction == "friend_paid_me"
        async with self._deps.session_factory() as session:
            accounts = await AccountService(session).list_accounts(ctx.user)
            account = resolve_account_name(spec.account, accounts) if spec.account else None
            try:
                created = await SettlementService(session, clock=self._deps.clock).create(
                    ctx.user,
                    SettlementCreate(
                        friend_id=uuid.UUID(plan["friend_id"]),
                        direction="friend_paid_you" if paid_by_friend else "you_paid_friend",
                        amount=Decimal(spec.amount or "0"),
                        currency=spec.currency,
                        occurred_on=date.fromisoformat(spec.date) if spec.date else None,
                        account_id=account.id if account else None,
                    ),
                    request_id=ctx.request_id,
                )
            except (ValidationFailedError, NotFoundError):
                logger.warning("settlement failed at save")
                return {"outcome": "save_failed", "settlement": None}
            friends = await FriendService(session).list_friends(ctx.user)
            friend = next(f for f in friends if str(f.id) == plan["friend_id"])
        return {
            "outcome": "settlement_saved",
            "settlement_saved": {
                "direction": created.direction,
                "friend": created.friend.name,
                "amountFormatted": created.amount_formatted,
                "currency": created.currency,
                "balances": [b.model_dump(mode="json") for b in friend.balances],
                "account": created.account.name if created.account else None,
                "warning": created.warning,
                "unmatchedAccount": spec.account if spec.account and account is None else None,
            },
        }

    async def balances(self, state: FinanceState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
        """Who owes whom, read from the balances the database worked out."""
        ctx = runtime.context
        runtime.stream_writer(status_event("summarizing", "Checking your balances…"))
        spec = BalanceSpec.model_validate(state.get("balance") or {})
        async with self._deps.session_factory() as session:
            friends = await FriendService(session).list_friends(ctx.user)
        if spec.friend:
            matches = matching_friends(spec.friend, friends)
            if len(matches) != 1:
                reason = "ambiguous_friend" if matches else "unknown_friend"
                options = [f.name for f in matches]
                return {
                    "outcome": "balance_unclear",
                    "friend_question": {"reason": reason, "name": spec.friend, "options": options},
                }
            friends = matches
        return {
            "outcome": "balances",
            "balance_answer": {
                "askedAbout": friends[0].name if spec.friend else None,
                "friends": [f.model_dump(mode="json", by_alias=True) for f in friends],
            },
        }

    # -- insights -------------------------------------------------------------------------

    def _period(self, state: FinanceState, ctx: TurnContext) -> DateRange:
        spec = PeriodSpec.model_validate(state.get("period") or {})
        try:
            return resolve_period(
                spec.kind,
                ctx.today,
                month=spec.month,
                start=spec.start,
                end=spec.end,
                days=spec.days,
            )
        except PeriodError:
            return resolve_period("this_month", ctx.today)

    async def summarize(self, state: FinanceState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
        ctx = runtime.context
        runtime.stream_writer(status_event("summarizing", "Adding up your transactions…"))
        period = self._period(state, ctx)
        async with self._deps.session_factory() as session:
            summary = await ReportService(
                session,
                clock=self._deps.clock,
                redis=self._deps.redis,
                generation=self._deps.generation,
                cache_ttl_seconds=self._deps.settings.cache_summary_ttl_seconds,
            ).summary(ctx.user, period)
        return {"summary": summary.model_dump(mode="json", by_alias=True), "outcome": "summary"}

    async def search(self, state: FinanceState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
        ctx = runtime.context
        runtime.stream_writer(status_event("searching", "Looking through your transactions…"))
        spec = SearchSpec.model_validate(state.get("search") or {})
        period = self._period(state, ctx)
        async with self._deps.session_factory() as session:
            category_id = None
            category_name = None
            if spec.category and spec.type != "transfer":
                categories = CategoryService(session)
                for kind in [spec.type] if spec.type else ["expense", "income"]:
                    category = await categories.by_slug(ctx.user_id, spec.category, kind)  # type: ignore[arg-type]
                    if category is not None:
                        category_id, category_name = category.id, category.name
                        break
            page = await TransactionService(session, clock=self._deps.clock).search(
                ctx.user,
                TransactionQuery(
                    type=spec.type,
                    category_id=category_id,
                    date_from=period.start,
                    date_to=period.end,
                    text=spec.text,
                    shared_only=spec.shared,
                    sort=spec.sort,
                    limit=min(spec.limit or 10, MAX_SEARCH_RESULTS),
                ),
            )
        noun = {"expense": "expenses", "income": "income entries", "transfer": "transfers"}.get(
            spec.type or "", "transactions"
        )
        if spec.shared:
            noun = "shared expenses"
        if category_name:
            noun = f"{category_name} {noun}"
        if spec.text:
            noun = f"{noun} matching “{spec.text}”"
        title = ("Largest " if spec.sort == "largest" else "Recent ") + noun
        return {
            "results": {
                "items": [item.model_dump(mode="json", by_alias=True) for item in page.items],
                "hasMore": page.next_cursor is not None,
                "period": {
                    "start": period.start.isoformat(),
                    "end": period.end.isoformat(),
                    "label": period.label,
                },
                "title": title[0].upper() + title[1:],
            },
            "outcome": "search",
        }

    # -- respond --------------------------------------------------------------------------

    async def respond(self, state: FinanceState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
        ctx = runtime.context
        outcome = state.get("outcome")
        base_id = f"r-{(state.get('message_id') or uuid.uuid4().hex)[:8]}"
        ui: list[Any] = []
        streamed = False

        if outcome == "saved":
            text, ui = compose_saved(
                state.get("saved") or [],
                today=ctx.today,
                locale=ctx.locale,
                abandoned=bool(state.get("abandoned")),
                filed_by_merchant_rule=frozenset(state.get("filed_by_merchant_rule") or []),
                unmatched_accounts=state.get("unmatched_accounts") or [],
                shared=state.get("shared_saved") or [],
                added_friends=state.get("added_friends") or [],
                interaction_id=f"{base_id}-saved",
            )
        elif outcome == "summary" and state.get("summary"):
            text, ui = compose_summary(
                state["summary"] or {},
                {"category": (state.get("search") or {}).get("category")},
                interaction_id=f"{base_id}-summary",
            )
        elif outcome == "search" and state.get("results"):
            text, ui = compose_search(state["results"] or {}, interaction_id=f"{base_id}-list")
        elif outcome == "settlement_saved" and state.get("settlement_saved"):
            saved = state["settlement_saved"] or {}
            text = compose_settlement_saved(
                direction=saved["direction"],
                friend=saved["friend"],
                amount_formatted=saved["amountFormatted"],
                currency=saved["currency"],
                balances=[BalanceView.model_validate(b) for b in saved["balances"]],
                account=saved["account"],
                warning=saved["warning"],
                unmatched_account=saved["unmatchedAccount"],
            )
        elif outcome == "balances" and state.get("balance_answer"):
            answer = state["balance_answer"] or {}
            text = compose_balances(
                [FriendView.model_validate(f) for f in answer["friends"]],
                asked_about=answer["askedAbout"],
            )
        elif outcome in ("settlement_unclear", "balance_unclear") and state.get("friend_question"):
            ask = state["friend_question"] or {}
            compose = (
                compose_unclear_settlement
                if outcome == "settlement_unclear"
                else compose_unclear_balance_question
            )
            text = compose(ask["reason"], ask["name"], ask["options"])
        elif outcome in STATIC_REPLIES:
            text = STATIC_REPLIES[outcome or ""]
        else:
            intent = state.get("intent")
            kind = intent if intent in ("help", "smalltalk", "out_of_scope") else "help"
            user_text = state.get("user_text") or ""
            parts: list[str] = []
            async for chunk in self._deps.llm.stream_reply(
                ReplyRequest(
                    kind=kind,  # type: ignore[arg-type]
                    text=user_text,
                    locale=ctx.locale,
                    history=_history(list(state.get("history") or []), 4),
                )
            ):
                parts.append(chunk)
                runtime.stream_writer(text_event(chunk))
            streamed = True
            text = "".join(parts).strip()
            if not reply_is_grounded(text, user_text):
                # Free-form replies must never carry invented financial figures.
                fallback = RulesLLMClient().stream_reply(
                    ReplyRequest(kind=kind, text=user_text, locale=ctx.locale)  # type: ignore[arg-type]
                )
                text = "".join([chunk async for chunk in fallback])

        if not streamed:
            runtime.stream_writer(text_event(text))
        ui.append(suggestions_for(outcome, f"{base_id}-suggest"))
        return {
            "reply": {
                "text": text,
                "ui": [item.model_dump(mode="json", by_alias=True) for item in ui],
            }
        }
