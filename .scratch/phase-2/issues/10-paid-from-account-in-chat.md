# 10: Chat tags expenses and income with a named account

**What to build:** "paid 300 for lunch from HDFC" saves an expense tagged with the user's HDFC
account; "salary 50000 into HDFC" tags the income. The chat never asks about accounts for
expenses and income; when the named account isn't one of the user's (or matches several), the
transaction is saved untagged and the reply says so.

Spec: `../spec.md` → Implementation Decisions → Transfers and accounts in chat (the
expense/income tagging rules).

**Blocked by:** 09

**Status:** done

- [x] With an HDFC account, "paid 300 for lunch from HDFC" saves an expense tagged with HDFC, and the merchant is not "HDFC".
- [x] "salary 50000 into HDFC" saves income tagged with HDFC.
- [x] An unknown or ambiguous account name saves the transaction untagged, asks nothing, and the reply says which name wasn't matched.
- [x] The saved slip shows "from HDFC" for a tagged expense and "into HDFC" for tagged income.
- [x] At least 4 new eval cases cover "paid from" phrasing; the live eval over at least 5 repeated runs shows no regression, noted under `## Comments` in this ticket.
- [x] API checks, the full pytest suite, and web typecheck, lint and build pass.

## Comments

- Live eval (Gemini on Vertex, `understand_v2` unchanged, with reconcile), 29 cases: the 23 existing plus 6 new "paid from" / "into" cases (expense from HDFC, salary into HDFC, "using my SBI account", merchant plus account together, income "on ICICI account", and "from the office" which must not become an account). Ten repeated runs of all 29 cases (two batches of five):

  | run | accuracy | p50 | p95 | notes |
  | --- | --- | --- | --- | --- |
  | 1 | 100% | 1168 ms | 2842 ms | |
  | 2 | 96.6% | 1055 ms | 1394 ms | model missed a transfer ("sent 3000 from Paytm to HDFC on 20 oct") |
  | 3 | 100% | 1077 ms | 1324 ms | |
  | 4 | 96.6% | 1064 ms | 1384 ms | model split "uber 220 and lunch 180" into one transaction |
  | 5 | 100% | 1123 ms | 1510 ms | |
  | 6 | 93.1% | 1147 ms | 1357 ms | same "uber ... lunch" split, plus one Gemini 504 |
  | 7 | 100% | 1109 ms | 2375 ms | |
  | 8 | 100% | 1118 ms | 2309 ms | |
  | 9 | 93.1% | 1138 ms | 1392 ms | two provider errors (429 RESOURCE_EXHAUSTED, 504) |
  | 10 | 96.6% | 1105 ms | 1415 ms | one provider 504 |

  The 6 new cases passed in all 10 runs (60 of 60). Every miss is on an existing case: two model misreadings that are not about accounts ("uber 220 and lunch 180" split once in each batch, the "sent 3000" transfer once) and four Gemini provider errors (504 and 429, counted as failures here, not as accuracy). Median of the run p50s is about 1.11 s against the Phase 1 baseline of 1.26 s. The existing 23 cases are therefore not at a clean 100% in these runs, and the evidence says the misses are model/provider noise rather than this change, but that is my reading, not proven by a before-and-after on the same days.
- No prompt change: `understand_v2` already returns `account` for expenses and income. What was wrong was after the model: the `from X` phrase made X the merchant. Reconcile now drops a merchant that is the account's words, and turns a merchant that follows "from/into" and names one of the user's accounts into the account.
- The offline parser takes the user's account names. "from HDFC" / "into HDFC" / "using my SBI account" naming an account (one or several) is the account and never the merchant; "from Nike" stays a merchant. With no account list the parser tags nothing, and an account name the user does not have cannot be told from a shop by the parser alone; only the model reading flags such a name, and the reply then says it was not matched.
- A merchant is only turned into the account when the text says "from/into <merchant>"; merchant "Amazon" with an "Amazon Pay" account stays a merchant when the model also named an account.
- The reply says "from HDFC" / "into HDFC" for a single tagged transaction (the web card shows the same as a line under the description); unmatched or ambiguous names add "I couldn't match “X” to one of your accounts, so I saved it without an account."
- The sandbox worktree has no `node_modules`, so Turbopack (`npm run build -w web`) cannot resolve `next` from inside it; the production build was run with `next build --webpack` through a junction to the main checkout's `node_modules`, and compiled. Typecheck and lint pass.

- Merged into `phase-2/integration` as the merge of branch `phase-2/t10-paid-from-account` (ticket 10 merge commit; see git log for the sha).
- Same-day comparison (2026-11-01), the 23 cases both trees share, 5 runs each: integration before ticket 10 had 1 misread and 2 provider errors over 115 calls (p50 1093 ms); ticket 10 had 2 misreads and 0 errors (p50 1107 ms). The misses differ from run to run and are model noise, not a regression.
