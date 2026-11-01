# 07: Settlements and balances in chat

**What to build:** A user says "Jaymin paid me 500" or "paid Jaymin 500" (when they owe him) and
the chat records a settlement; "paid Ramesh 2000 for his old phone" stays an expense. "How much
does Jaymin owe me?" and "who owes me money?" answer from the balances, and "show my shared
expenses this month" lists them.

Spec: `../spec.md` → User Stories 29-36; Implementation Decisions → Chat.

**Blocked by:** 03, 06

**Status:** done

- [x] The understand prompt (a new version if 06's has shipped) recognises a settlement (paying back, either direction) and a balance question; the offline parser reads the same phrasings (unit tests).
- [x] "paid X N" is a settlement only when the user has a non-zero balance with X in that currency and the message reads as paying back; otherwise it stays an expense with X as merchant (unit and integration tests for both).
- [x] A settlement saved from chat goes through the settlement service from ticket 03 and can be tagged with an account ("Jaymin paid me 500 to HDFC").
- [x] Balance questions answer with amounts computed in SQL, per currency, for one friend or all friends; the model never calculates.
- [x] "show my shared expenses this month" lists the user's shared expenses for the period.
- [x] At least 8 new eval cases; the live eval over at least 5 repeated runs keeps accuracy, numbers under `## Comments`.
- [x] API checks, full pytest, and web typecheck, lint and build pass.

## Comments

- Built: prompt `understand_v4` (v3 stays) adds the `record_settlement` and `balance_question` intents and a `shared` flag on search. The offline parser (`llm/settling.py`) reads the same phrasings. New workflow nodes `settle` (through `SettlementService`, tagged with an account when one is named) and `balances` (from `FriendService.list_friends`, SQL balances per currency). "show my shared expenses" reuses the transaction list card through a new `shared_only` filter on `TransactionQuery`. No migration, no contract change.
- "paid X N" rule (`workflows/settling.py`): "X paid me N" is always a settlement. "I paid X N" is one only when X is one of the friends, no purpose is given ("for his old phone"), and the balance with X in that currency is not zero; otherwise it goes on as an expense with X as merchant.
- Decisions: a stranger or an ambiguous name ("Jaymin" with two Jaymins) gets a plain reply asking to add the friend or to say the full name, not a pending question card, and nothing is saved. `settle` has no retry policy because a settlement has no idempotency key; a retried chat message id is replayed by the chat layer (tested). Balance answers are text only, no new card.
- Live eval (Gemini on Vertex, `understand_v4`, with reconcile), 50 cases: the 38 existing plus 12 new (four settlements in each direction, one with an account and one with a date, the negatives "paid Ramesh 2000 for his old phone" and "paid Riya 800 for the movie tickets", three balance questions, "show my shared expenses this month"). Five runs, no provider errors:

  | run | accuracy | p50 | p95 |
  | --- | --- | --- | --- |
  | 1 | 100% (50/50) | 1388 ms | 2111 ms |
  | 2 | 100% | 1400 ms | 1993 ms |
  | 3 | 100% | 1326 ms | 1618 ms |
  | 4 | 100% | 1368 ms | 1743 ms |
  | 5 | 100% | 1342 ms | 1617 ms |

  Same-day comparison on the 38 older cases, five runs each. v3: 97.4% in run 1 (one duplicated transaction on the HDFC lunch case), then 100% in runs 2 to 5, p50 1246 / 1215 / 1201 / 1229 / 1236 ms, p95 5420 / 1952 / 1389 / 2055 / 1523 ms. v4: 100%, 97.4% (one duplicated transaction on the pizza case), then 100% three times, p50 1408 / 1418 / 1340 / 1356 / 1366 ms, p95 1871 / 2181 / 1721 / 1600 / 1740 ms. Same accuracy; v4 adds about 0.12 to 0.15 s at the median for the longer prompt. The duplicate-transaction miss is the known one that reconcile usually removes; it showed once in each version.
- Tests: 20 parser unit tests, 20 choice and reply unit tests, 17 chat integration tests. Merged `phase-3/integration` (ticket 04) into the branch: API checks, web typecheck, lint and build pass; contracts unchanged; full pytest 577 passed, 1 skipped (live eval).

- Merged into phase-3/integration as 0094a13. No conflicts with ticket 05: notices are written inside `SettlementService.create`, which the `settle` node calls, so chat settlements notify a linked friend. Added `test_a_settlement_recorded_from_chat_is_told_to_the_linked_friend` in `tests/integration/test_notices.py`. Merge checks: full pytest 588 passed, 1 skipped (live LLM eval); check:api, check:web, web build pass; contracts no real diff (CRLF only, restored); alembic head 0011, no drift. All boxes ticked.
