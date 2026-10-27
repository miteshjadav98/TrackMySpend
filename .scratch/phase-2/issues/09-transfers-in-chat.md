# 09: Transfers in chat

**What to build:** A user says "moved 5000 from HDFC to Paytm", "withdrew 2000 from SBI" or
"paid 15000 credit card bill from HDFC" and the chat saves a transfer between their accounts,
asking only for what is missing or unclear, and creating an account the user names in a
clarification. The understanding prompt moves to v2, which also captures the account named
for expenses and income (ticket 10 uses that).

Spec: `../spec.md` → Implementation Decisions → Transfers and accounts in chat.

**Blocked by:** 08, 02

**Status:** ready-for-agent

- [ ] Understand prompt v2 is a new file with the user's active account names in the context block at the top; v1 stays; the prompt version is logged.
- [ ] The understanding schema has the `transfer` type and the `account` / `toAccount` fields, for Gemini and the offline parser alike.
- [ ] The offline parser reads the transfer phrasings in the spec (unit tests), and ordinary bills such as "electricity bill 1200" stay expenses.
- [ ] With HDFC and Paytm accounts, "moved 5000 from HDFC to Paytm" saves a transfer without a question, and the saved slip shows "HDFC → Paytm".
- [ ] A missing, unknown or ambiguous account leads to a clarification offering the user's active accounts; typing a new name creates that account at save, kind inferred from the name (unit tests for the inference).
- [ ] Choosing the same account for both ends asks again with a notice.
- [ ] "withdrew 2000 from SBI" saves a transfer from SBI to the cash account; "paid 15000 credit card bill from HDFC" saves a transfer from HDFC to the credit card account.
- [ ] "show my transfers this month" lists the transfers, and the chat summary still excludes them.
- [ ] Transfers in chat never teach or use merchant rules.
- [ ] At least 8 new eval cases cover transfers; the live eval over at least 5 repeated runs keeps Phase 1 accuracy with no meaningful latency regression, and the numbers are noted under `## Comments` in this ticket.
- [ ] API checks, the full pytest suite, and web typecheck, lint and build pass.
