# 07: Settlements and balances in chat

**What to build:** A user says "Jaymin paid me 500" or "paid Jaymin 500" (when they owe him) and
the chat records a settlement; "paid Ramesh 2000 for his old phone" stays an expense. "How much
does Jaymin owe me?" and "who owes me money?" answer from the balances, and "show my shared
expenses this month" lists them.

Spec: `../spec.md` → User Stories 29-36; Implementation Decisions → Chat.

**Blocked by:** 03, 06

**Status:** ready-for-agent

- [ ] The understand prompt (a new version if 06's has shipped) recognises a settlement (paying back, either direction) and a balance question; the offline parser reads the same phrasings (unit tests).
- [ ] "paid X N" is a settlement only when the user has a non-zero balance with X in that currency and the message reads as paying back; otherwise it stays an expense with X as merchant (unit and integration tests for both).
- [ ] A settlement saved from chat goes through the settlement service from ticket 03 and can be tagged with an account ("Jaymin paid me 500 to HDFC").
- [ ] Balance questions answer with amounts computed in SQL, per currency, for one friend or all friends; the model never calculates.
- [ ] "show my shared expenses this month" lists the user's shared expenses for the period.
- [ ] At least 8 new eval cases; the live eval over at least 5 repeated runs keeps accuracy, numbers under `## Comments`.
- [ ] API checks, full pytest, and web typecheck, lint and build pass.

## Comments
