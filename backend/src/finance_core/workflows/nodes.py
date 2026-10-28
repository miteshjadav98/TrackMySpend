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

from finance_core.categories.defaults import FALLBACK_SLUG, FALLBACK_SLUGS
from finance_core.categories.models import Category
from finance_core.categories.schemas import CategoryCreate
from finance_core.categories.service import CategoryService
from finance_core.conversations.service import HistoryItem
from finance_core.dates import DateRange, PeriodError, resolve_period
from finance_core.errors import ConflictError, ValidationFailedError
from finance_core.ids import derived_id
from finance_core.llm.base import (
    CategoryHint,
    LLMUnavailableError,
    PendingQuestion,
    ReplyRequest,
    UnderstandRequest,
)
from finance_core.llm.rules import RulesLLMClient
from finance_core.llm.schemas import PeriodSpec, SearchSpec
from finance_core.merchants.service import MerchantRuleService
from finance_core.reports.service import ReportService
from finance_core.transactions.schemas import TransactionCreate, TransactionQuery, TransactionView
from finance_core.transactions.service import TransactionService
from finance_core.workflows.answers import AnswerApplier, AnswerOutcome, pending_field
from finance_core.workflows.category_choice import CategoryOption, choose_category
from finance_core.workflows.drafts import TransactionDraft, draft_from_extraction, first_issue
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
    if draft.type is None or draft.category_text or draft.category_skipped:
        return draft
    suggested = (
        await categories.by_slug(user_id, draft.category_slug, draft.type)
        if draft.category_slug
        else None
    )
    rule = await merchant_rules.category_for(user_id, type=draft.type, merchant=draft.merchant)
    choice = choose_category(
        draft.source_text,
        picked=_picked(draft),
        suggested=_option(suggested),
        merchant_rule=_option(rule),
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
        request = UnderstandRequest(
            text=text,
            today=ctx.today,
            timezone=ctx.timezone,
            base_currency=ctx.base_currency,
            locale=ctx.locale,
            categories=[CategoryHint(c.slug, c.name, c.kind) for c in categories],
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
            understanding = reconcile(understanding, text, today=ctx.today, locale=ctx.locale)
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
        if intent in ("spending_summary", "search_transactions"):
            update["period"] = (understanding.period or PeriodSpec()).model_dump()
            update["search"] = understanding.search.model_dump() if understanding.search else None
            return Command(
                goto="summarize" if intent == "spending_summary" else "search", update=update
            )
        return Command(goto="respond", update=update)

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
                CategoryService(session), user_id=ctx.user_id, today=ctx.today, locale=ctx.locale
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
            for index, draft in enumerate(drafts):
                drafts[index] = await _file_under_category(
                    draft, ctx.user_id, categories, merchant_rules
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
                        ctx.user_id, draft.type or "expense", ctx.today
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
                CategoryService(session), user_id=ctx.user_id, today=ctx.today, locale=ctx.locale
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
            existing = await transactions.find_by_source_ref(ctx.user, source_ref)
            if existing:
                views = existing
            else:
                categories = CategoryService(session)
                items = []
                for draft in drafts:
                    assert draft.type is not None and draft.amount is not None and draft.date
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
                            matched = await categories.match(
                                ctx.user_id, draft.category_text, draft.type
                            )
                            category_id = matched.id if matched else None
                    if category_id is None:
                        fallback = await categories.by_slug(
                            ctx.user_id, FALLBACK_SLUG[draft.type], draft.type
                        )
                        category_id = fallback.id if fallback else None
                    data = TransactionCreate(
                        type=draft.type,
                        amount=Decimal(draft.amount),
                        currency=draft.currency,
                        occurred_on=date.fromisoformat(draft.date),
                        category_id=category_id,
                        description=draft.description,
                        merchant=draft.merchant,
                        payment_method=draft.payment_method,
                    )
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
                views = [view for view, _ in results]
        return {
            "saved": [view.model_dump(mode="json", by_alias=True) for view in views],
            "filed_by_merchant_rule": _filed_by_merchant_rule(drafts, views),
            "drafts": [],
            "outcome": "saved",
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
            if spec.category:
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
                    sort=spec.sort,
                    limit=min(spec.limit or 10, MAX_SEARCH_RESULTS),
                ),
            )
        noun = {"expense": "expenses", "income": "income entries"}.get(
            spec.type or "", "transactions"
        )
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
