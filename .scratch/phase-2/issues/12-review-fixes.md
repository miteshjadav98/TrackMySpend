# 12: Code review fixes

**What to build:** Fix the findings from the Phase 2 code review of `phase-2/integration`, so
merchant rules stick, non-answers never become accounts, and a failed transfer save leaves
nothing behind.

Spec: `../spec.md` (merchant rules, accounts, transfers in chat).

**Blocked by:** 01-11

**Status:** done

- [x] A category word inside the merchant's own name, or said about another item in the same message, does not count as "named in the message"; the merchant rule wins and is not rewritten.
- [x] Non-answers ("idk", "skip", "not sure", "don't know", "none", "whatever", ...) to an account question, or as a typed new category name, ask again with a notice instead of creating anything.
- [x] The account question offers a ready-made "Cash" option when the user has no cash account; picking it creates the Cash account at save.
- [x] A new account typed for a transfer takes the other end's currency when that end is an existing account; a currency failure gets its own reply, not "something changed"; nothing is created when the transfer cannot be saved; the active-account limit at save gets a clear reply instead of an error.
- [x] An all-blank model transaction is filled from the parser when each returns exactly one transaction.
- [x] Simple plurals count as naming a category ("grocery" names Groceries).
- [x] Regression tests for each, named as sentences.

## Comments

Implemented all six findings test-first. Category choice now matches only the draft's own segment (`item_text`) with the merchant name cut out, and simple plurals. A `NON_ANSWERS` list rejects "idk" etc. for accounts and new categories. The account question appends a ready-made Cash option. A transfer's new account takes the other end's currency, is validated before creation and flushed (not committed) so it rolls back with a failed transfer; mismatch and account-limit have their own replies. All-blank model transaction is filled from the parser. Full suite: 357 passed, 1 skipped; `npm run check:api` clean.

Merged into phase-2/integration. Verified on the merge: check:api, check:web, web build and contracts clean; single alembic head 0007, no drift; full suite 357 passed, 1 skipped.
