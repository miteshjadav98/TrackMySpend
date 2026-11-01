# 04: Merchant names and AI categories for imported rows

**What to build:** Each imported row gets a readable merchant picked out of the bank's narration
(for example "Swiggy" from `UPI/402112345678/SWIGGY/swiggy@icici/Payment`), and rows with no
merchant rule get a category guessed by the AI in batches, falling back to the offline parser's
keyword guesses when the AI fails. The AI only labels; it never sees or returns amounts it could
change.

Spec: `../spec.md` → User Stories 17-19; Implementation Decisions → Categories.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Pure merchant extraction for UPI, NEFT, IMPS, RTGS, POS, ATM and card narrations, with unit tests on realistic samples from several banks.
- [ ] A new versioned categorisation prompt file in `llm/prompts/` (the category list at the top), called in batches of about 50 rows, returning one category slug per row or none; schema-validated; unknown slugs ignored.
- [ ] Order per row: merchant rule, else AI guess, else Other. With the AI stubbed to fail, the offline parser's keyword categories are used and the import still works.
- [ ] The preview shows where each category came from (rule, AI, keyword, Other) so the user knows what to check.
- [ ] Live eval: at least 40 labelled narrations, at least 5 repeated runs, accuracy and latency (p50/p95 per batch) noted under `## Comments`.
- [ ] API checks, full pytest, and web typecheck, lint and build pass.

## Comments
