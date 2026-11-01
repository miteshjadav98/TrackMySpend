# 06: Shared expenses in chat

**What to build:** A user says "me and Jaymin spent 1000 on pizza, split it", "Jaymin paid 1000
for pizza, split it", "me, Jaymin and Riya spent 1500 on cab, split it" or "dinner 1000 with
Jaymin, I had 400 and he had 600", and the chat records a shared expense, asking only for what
is missing or unclear. The save card shows the total, who paid, and each share.

Spec: `../spec.md` → User Stories 12-24; Implementation Decisions → Chat.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] A new versioned understand prompt (the context block stays at the top, now listing the user's friends) adds participants, payer, split kind and exact per-person amounts; the previous version stays; the prompt version is logged.
- [ ] The understanding schema carries these fields for Gemini and the offline parser alike; the offline parser reads the phrasings above (unit tests).
- [ ] The payer defaults to the user unless the message names a friend as payer; the split defaults to equal.
- [ ] Friend names resolve like account names (exact ignoring case, else word containment); an ambiguous name asks which friend (options show emails where known); an unknown name asks "Add Jaymin as a new friend?" and adds them by name at save if confirmed.
- [ ] Exact amounts that don't add up to the total ask again with a notice; a friend-paid expense naming more than one other person asks the user to narrow it down or explains the limit.
- [ ] Category follows the usual category precedence on the recorder's side; "paid from HDFC" still tags the account.
- [ ] Save goes through the shared-expense service from ticket 02, idempotent like other chat saves.
- [ ] The save card shows total, "You paid"/"Jaymin paid", and each share.
- [ ] At least 8 new eval cases cover shared expenses; the live eval over at least 5 repeated runs keeps accuracy with no meaningful latency regression, numbers noted under `## Comments`.
- [ ] API checks, full pytest, and web typecheck, lint and build pass.

## Comments
