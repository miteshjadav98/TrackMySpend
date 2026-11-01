# 09: Transfers in chat

**What to build:** A user says "moved 5000 from HDFC to Paytm", "withdrew 2000 from SBI" or
"paid 15000 credit card bill from HDFC" and the chat saves a transfer between their accounts,
asking only for what is missing or unclear, and creating an account the user names in a
clarification. The understanding prompt moves to v2, which also captures the account named
for expenses and income (ticket 10 uses that).

Spec: `../spec.md` → Implementation Decisions → Transfers and accounts in chat.

**Blocked by:** 08, 02

**Status:** done

- [x] Understand prompt v2 is a new file with the user's active account names in the context block at the top; v1 stays; the prompt version is logged.
- [x] The understanding schema has the `transfer` type and the `account` / `toAccount` fields, for Gemini and the offline parser alike.
- [x] The offline parser reads the transfer phrasings in the spec (unit tests), and ordinary bills such as "electricity bill 1200" stay expenses.
- [x] With HDFC and Paytm accounts, "moved 5000 from HDFC to Paytm" saves a transfer without a question, and the saved slip shows "HDFC → Paytm".
- [x] A missing, unknown or ambiguous account leads to a clarification offering the user's active accounts; typing a new name creates that account at save, kind inferred from the name (unit tests for the inference).
- [x] Choosing the same account for both ends asks again with a notice.
- [x] "withdrew 2000 from SBI" saves a transfer from SBI to the cash account; "paid 15000 credit card bill from HDFC" saves a transfer from HDFC to the credit card account.
- [x] "show my transfers this month" lists the transfers, and the chat summary still excludes them.
- [x] Transfers in chat never teach or use merchant rules.
- [x] At least 8 new eval cases cover transfers; the live eval over at least 5 repeated runs keeps Phase 1 accuracy with no meaningful latency regression, and the numbers are noted under `## Comments` in this ticket.
- [x] API checks, the full pytest suite, and web typecheck, lint and build pass.

## Comments

- Live eval (Gemini on Vertex, `understand_v2`, with reconcile), 23 cases of which 10 are new transfer cases (8 record, 1 search, 1 not-a-transfer bill). Six repeated runs, each over all 23 cases:

  | run | accuracy | p50 | p95 |
  | --- | --- | --- | --- |
  | 1 | 100% | 1128 ms | 1386 ms |
  | 2 | 100% | 1128 ms | 1334 ms |
  | 3 | 100% | 1200 ms | 1577 ms |
  | 4 | 100% | 1078 ms | 1436 ms |
  | 5 | 100% | 1203 ms | 1421 ms |
  | 6 | 100% | 1156 ms | 1604 ms |

  Across all 138 calls: p50 1154 ms, p95 1486 ms, against the Phase 1 baseline of p50 1.26 s. One earlier script run hit a Gemini 504 (DEADLINE_EXCEEDED) on a single call; it was a provider timeout and the rerun is the one above.
- The ticket `Status:` line is left for the merge, as `docs/agents/issue-tracker.md` says.
- The parser also reads "sent X from A to B" as a transfer, but only when both ends are named ("sent 500 to Ramesh" stays an expense).
- Merged to `phase-2/integration` in commit e4706d3 ("Merge ticket 09: transfers in chat").
