# 06: Shared expenses in chat

**What to build:** A user says "me and Jaymin spent 1000 on pizza, split it", "Jaymin paid 1000
for pizza, split it", "me, Jaymin and Riya spent 1500 on cab, split it" or "dinner 1000 with
Jaymin, I had 400 and he had 600", and the chat records a shared expense, asking only for what
is missing or unclear. The save card shows the total, who paid, and each share.

Spec: `../spec.md` → User Stories 12-24; Implementation Decisions → Chat.

**Blocked by:** 02

**Status:** ready-for-agent

- [x] A new versioned understand prompt (the context block stays at the top, now listing the user's friends) adds participants, payer, split kind and exact per-person amounts; the previous version stays; the prompt version is logged.
- [x] The understanding schema carries these fields for Gemini and the offline parser alike; the offline parser reads the phrasings above (unit tests).
- [x] The payer defaults to the user unless the message names a friend as payer; the split defaults to equal.
- [x] Friend names resolve like account names (exact ignoring case, else word containment); an ambiguous name asks which friend (options show emails where known); an unknown name asks "Add Jaymin as a new friend?" and adds them by name at save if confirmed.
- [x] Exact amounts that don't add up to the total ask again with a notice; a friend-paid expense naming more than one other person asks the user to narrow it down or explains the limit.
- [x] Category follows the usual category precedence on the recorder's side; "paid from HDFC" still tags the account.
- [x] Save goes through the shared-expense service from ticket 02, idempotent like other chat saves.
- [x] The save card shows total, "You paid"/"Jaymin paid", and each share.
- [x] At least 8 new eval cases cover shared expenses; the live eval over at least 5 repeated runs keeps accuracy with no meaningful latency regression, numbers noted under `## Comments`.
- [x] API checks, full pytest, and web typecheck, lint and build pass.

## Comments

- Live eval (Gemini on Vertex, `understand_v3`, with reconcile), 38 cases: the 29 existing plus 9 new shared-expense cases ("me and Jaymin spent 1000 on pizza, split it", "Jaymin paid 1000 for pizza, split it", three people, exact amounts with "he", "split 1200 for movie tickets with Riya", a friend-paid bill, a group hotel bill with a date, "from HDFC", and the negative "coffee with Jaymin 200"). Five repeated runs:

  | run | accuracy | p50 | p95 |
  | --- | --- | --- | --- |
  | 1 | 100% (38/38) | 1277 ms | 1625 ms |
  | 2 | 100% | 1258 ms | 1490 ms |
  | 3 | 100% | 1248 ms | 1494 ms |
  | 4 | 100% | 1191 ms | 1521 ms |
  | 5 | 100% | 1227 ms | 1475 ms |

  Same-day comparison on the 29 older cases with the previous prompt `understand_v2`, five runs: 100% every run, p50 1171 / 1126 / 1111 / 1180 / 1118 ms, p95 1848 / 1726 / 1369 / 1426 / 1372 ms. v3 has a median p50 of about 1.25 s against about 1.13 s for v2 on the same day: roughly 0.1 s more, which fits the longer prompt (the two comparisons ran at different times and v3 ran over 38 cases, so this is indicative, not exact). No provider errors in either set.
- The offline parser (`llm/sharing.py`) reads the same phrasings, and all 9 new cases pass against it too. It needs the user's friend names only to read "Jaymin 600" in an exact split.
- Decisions: a friend who paid and more than one other friend sharing asks "I paid it, split with everyone" or "Split only between me and X". An exact split that does not add up asks again with "Those add up to X, but the total is Y" and accepts a reply like "I had 400, Jaymin 600" or "split it equally". Unknown names are offered alongside the existing friends so a misspelling is one tap from the right person.
- One small change outside chat: `SharedExpenseService.create` and `TransactionService.add_share_row` take optional `source` and `source_ref`, so a retried chat message finds the share it already saved. No migration.
- The save card's Edit opens the shared-expense dialog, and Undo deletes the whole shared expense (there is no restore for it).
