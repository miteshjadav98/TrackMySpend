# 10: Chat tags expenses and income with a named account

**What to build:** "paid 300 for lunch from HDFC" saves an expense tagged with the user's HDFC
account; "salary 50000 into HDFC" tags the income. The chat never asks about accounts for
expenses and income; when the named account isn't one of the user's (or matches several), the
transaction is saved untagged and the reply says so.

Spec: `../spec.md` → Implementation Decisions → Transfers and accounts in chat (the
expense/income tagging rules).

**Blocked by:** 09

**Status:** ready-for-agent

- [ ] With an HDFC account, "paid 300 for lunch from HDFC" saves an expense tagged with HDFC, and the merchant is not "HDFC".
- [ ] "salary 50000 into HDFC" saves income tagged with HDFC.
- [ ] An unknown or ambiguous account name saves the transaction untagged, asks nothing, and the reply says which name wasn't matched.
- [ ] The saved slip shows "from HDFC" for a tagged expense and "into HDFC" for tagged income.
- [ ] At least 4 new eval cases cover "paid from" phrasing; the live eval over at least 5 repeated runs shows no regression, noted under `## Comments` in this ticket.
- [ ] API checks, the full pytest suite, and web typecheck, lint and build pass.
