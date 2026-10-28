# Phase 2: merchant rules, accounts and transfers, account security

Status: ready-for-agent
Integration branch: `phase-2/integration`
Tickets: `issues/` in this directory

## Problem Statement

MoneyMoney forgets how I file things. Each time I log Swiggy it may guess a different category,
and when it asks me, my answer only applies to that one transaction.

It also cannot say where my money came from or went. Moving money between my bank, credit
card, wallet and cash is either recorded as an expense (paying my credit card bill counts my
spending twice) or not recorded at all, and the chat cannot record a transfer.

My login has no safety net. I cannot see where I am signed in, sign out a lost phone, change my
password, or get back in when I forget it.

## Solution

- **Merchant rules.** MoneyMoney learns from every saved transaction which category I use for
  each merchant and files the next one the same way, unless I name a different category. I can
  see, change and forget these rules in Settings.
- **Accounts and transfers.** I set up my accounts (bank, credit card, wallet, cash), tag
  expenses and income with one, and record transfers between them, in chat ("moved 5000 from
  HDFC to Paytm") or on the transactions page. Transfers never count as income or expense.
- **Account security.** Settings lists my signed-in devices; I can sign out one or all the
  others, and change my password. "Forgot password?" sends me a single-use reset link (printed
  in the API log until an email provider is chosen).

## User Stories

### Merchant rules

1. As a user, I want MoneyMoney to remember the category I used for a merchant, so that I don't answer the same category question twice.
2. As a user, I want "Swiggy 250" saved under Office meals without a question after I filed Swiggy there, so that logging stays one message.
3. As a user, I want the reply to tell me when a merchant rule chose the category, so that I understand why it was filed that way.
4. As a user, I want a category I name in my message ("Amazon 2000 shopping") to win over the merchant rule, so that I stay in control.
5. As a user, I want a category I pick in a clarification to be used and remembered for that merchant.
6. As a user, I want my category corrections on the transactions page to update the merchant rule, so that the next one comes out right.
7. As a user, I want merchant names matched regardless of case, punctuation and spacing ("SWIGGY", "Swiggy!"), so that typing differences don't split my rules.
8. As a user, I want expense and income rules kept apart, so that an Amazon refund isn't filed under Shopping.
9. As a user, I want "Other", "Other income" and skipped categories never learned, so that "I don't know" never becomes a rule.
10. As a user, I want transfers never to create or use merchant rules.
11. As a user, I want to see all my merchant rules in Settings, most recently used first, with how often each was used.
12. As a user, I want to search my merchant rules by merchant name.
13. As a user, I want to change a rule's category in Settings.
14. As a user, I want to forget a rule, so that MoneyMoney guesses again next time and learns from what I save then.
15. As a user, I want my merchant rules private: another user's Swiggy rule never affects mine.

### Accounts

16. As a user, I want to add my accounts with a name, kind (bank, credit card, wallet, cash, other) and currency, so that I can say where money moves.
17. As a user, I want a new account's currency to default to my base currency.
18. As a user, I want to rename an account and change its kind.
19. As a user, I want to archive an account I no longer use, so that it leaves my pickers but stays on old transactions.
20. As a user, I want to unarchive an account.
21. As a user, I want a clear error when I create a second active account with the same name, ignoring case.
22. As a user, I want to tag an expense or income with the account it was paid from or into, on the transactions page.
23. As a user, I want to filter my transactions by account.
24. As a user, I want another user's accounts to be invisible to me.

### Transfers

25. As a user, I want to record a transfer between two of my accounts, so that moving money is not counted as spending.
26. As a user, I want transfers left out of income, expense, category totals and the monthly tally.
27. As a user, I want transfers shown distinctly in my transaction list ("HDFC → Paytm Wallet"), so that I can tell them apart from expenses.
28. As a user, I want to edit a transfer's amount, date, accounts and notes on the transactions page.
29. As a user, I want a clear error when a transfer's two accounts are the same, or when the accounts and the amount are in different currencies.
30. As a user, I want "moved 5000 from HDFC to Paytm" in chat saved as a transfer.
31. As a user, I want "withdrew 2000 from SBI" understood as a transfer from SBI to my cash account.
32. As a user, I want "paid 15000 credit card bill from HDFC" understood as a transfer to my credit card, not an expense.
33. As a user, I want a clarification offering my accounts when I don't name an account, or the name matches none or several of mine.
34. As a user, I want to type a new account name in that clarification and have the account created, so that I don't leave the chat.
35. As a user, I want "show my transfers this month" to list my transfers, and my chat summaries to keep excluding them.
36. As a user, I want "paid 300 for lunch from HDFC" tagged with my HDFC account, without being asked about accounts I didn't mention.
37. As a user, I want an expense saved anyway when the account I mention isn't one of mine, with the reply saying no account was tagged.

### Account security

38. As a user, I want to see every device where I am signed in, with its browser, last activity, and which one is this device.
39. As a user, I want to sign out one device, so that a lost phone can't reach my finances.
40. As a user, I want to sign out all other devices at once.
41. As a user, I want to change my password by entering the current one, and have my other devices signed out.
42. As a user, I want a clear error when my current password is wrong or the new one breaks the password rules.
43. As a user who forgot my password, I want to request a reset link by email from the login page.
44. As a user, I want the same reply whether or not an account exists for an email, so that nobody can probe which emails are registered.
45. As a user, I want a reset link to work once and expire after 30 minutes.
46. As a user, I want every session signed out after a password reset, so that whoever knew the old password loses access.
47. As a user, I want a clear message when a reset link is invalid or expired, with a way to request a new one.
48. As an operator, I want reset requests rate-limited per email and per IP, so that the feature can't be used to spam people.
49. As a developer, I want reset emails printed in the API log locally, so that I can test the flow without an email provider.
50. As an operator, I want every security event (session revoked, password changed, reset requested, password reset) in the audit log.

## Implementation Decisions

### Shared

- The domain terms are defined in `GLOSSARY.md`: account, archived account, transfer, merchant, merchant rule, session, password reset.
- Two new domain modules, `accounts` and `merchants`, follow the existing domain-service pattern: async methods that take the user's context, scope every query by user, write audit events in the same database transaction, and stay independent of the workflow, agent and LLM layers (both join the import-linter contract).
- Every schema change is its own Alembic revision chained onto the current head.
- References from transactions and merchant rules to accounts and categories use the database default action (NO ACTION), so a future cascading user deletion succeeds. The app never hard-deletes accounts or categories.
- REST endpoints live under `/api/v1`, use the existing error envelope, camelCase JSON, and keyset pagination for lists. OpenAPI and the TypeScript contracts are regenerated with every API change.

### Merchant rules

- A `ledger` table with one row per (user, transaction type, merchant key): the merchant's display name (latest spelling), the category, the use count, when it was last used, and created/updated timestamps.
- **Merchant key**: the merchant name case-folded, with punctuation removed and whitespace collapsed. A pure, unit-tested function.
- **Learning** happens inside the transactions domain service, in the same database transaction as the save, so every save path learns: chat saves, API creates, and API edits that change the category or the merchant. It upserts the rule for (type, merchant key) with the saved category, and bumps the use count and last-used time. Only newly inserted rows teach (an idempotent replay teaches nothing). Nothing is learned from transactions without a merchant, from transfers, or from the fallback categories ("Other", "Other income").
- Automatic learning has no audit event of its own (the save that caused it has one). Changing and forgetting a rule are audited.
- **Category precedence** for a chat draft, highest first:
  1. a category the user picked in a clarification;
  2. a category the user named in the message: the model's suggested category counts as named when its name, or a distinctive word of it ("Food" for "Food & Dining"), appears as a whole word in the user's message; fallback categories never count;
  3. the merchant rule for the draft's merchant and type;
  4. the model's suggested category;
  5. otherwise, a clarification.

  The draft records which level chose the category, so the reply can say "Filed under Office meals, as before for Swiggy."
- A rule whose category is archived is ignored.
- **API**: `GET /merchant-rules` (filters `type` and `q`, a merchant substring; newest use first; keyset pagination), `PATCH /merchant-rules/{id}` (`categoryId`: visible to the user and of the rule's type), `DELETE /merchant-rules/{id}` (forget; 204). The view: id, merchant, type, category (id, slug, name, icon), timesUsed, lastUsedAt.
- Forgetting a rule does not switch learning off: the next save for that merchant teaches a new rule. The Settings copy says so.

### Accounts

- A `ledger` table: id, user, name (1–60 characters, trimmed), kind (`bank`, `credit_card`, `wallet`, `cash`, `other`), currency (ISO 4217; defaults to the base currency; fixed after creation), an archived flag, and timestamps. Names are unique per user, ignoring case, among active accounts. At most 50 active accounts per user.
- **API**: `GET /accounts` (`includeArchived`, default false; active first, then by name), `POST /accounts` (201), `PATCH /accounts/{id}` (name, kind, isArchived). No delete. Errors: a duplicate active name is 409 `account_exists`; over the limit or an unsupported currency is 422; an unknown or another user's id is 404.
- The account view: id, name, kind, currency, isArchived, createdAt, updatedAt. Transactions carry a compact account reference: id, name, kind.
- Transactions gain an optional account (`accountId`) and, for transfers only, a destination account (`toAccountId`). Database check constraints: expense and income have no destination account; a transfer has both accounts, different from each other, and no category.
- Picking an account (on create, or an edit that changes it) needs an active account of the user. An archived account already on a transaction stays when other fields are edited.
- An expense or income may be tagged with an account in another currency (a card used abroad). A transfer may not: currency conversion is out of scope.
- The transaction list filter `accountId` matches either end of a transfer.

### Transfers

- `type: "transfer"` is accepted on create and update. `accountId` (from) and `toAccountId` (to) are both required and must differ; a transfer has no category; the amount's currency must equal both accounts' currency. Validation errors name the field: `accountId`, `toAccountId`, `categoryId` or `currency`.
- Changing a transaction's type clears the fields that don't apply to the new type (the category when it becomes a transfer; the destination account when it stops being one). The result must satisfy the new type's rules, or the edit is a 422.
- Summaries, category totals and the tally already exclude transfers; tests pin that this stays true.

### Transfers and accounts in chat

- The understanding schema gains `transfer` as a type and two fields on each extracted transaction: `account` (the user's own account the money left, or arrived in for income, as the user named it) and `toAccount` (for a transfer, the account the money went to). The user's active account names go into the understanding request beside the categories. This is understand prompt v2, a new file; v1 stays. The context block stays at the top.
- The offline parser learns transfer phrasing: "transfer/transferred/moved X from A to B"; "withdrew X (from A)", which goes to the cash account; "paid X credit card bill (from A)", which goes to the credit card. Ordinary bills ("electricity bill 1200") stay expenses.
- **Account names resolve** against the user's active accounts: an exact name, ignoring case, wins; otherwise a single account whose name contains the words, or whose words are contained ("HDFC" ↔ "HDFC Savings"); several matches or none lead to a clarification.
- A transfer draft has no category. Its clarification order: amount, amount confirmation, currency, from account, to account, date. Account clarifications offer the user's active accounts, most used first, and accept a typed new name. A typed new account is created at save in the base currency, its kind inferred from the name: "cash" is cash; "credit" or "card" is a credit card, but "debit" is a bank; known wallet names (Paytm, PhonePe, GPay, Amazon Pay, MobiKwik, "wallet") are wallets; anything else is a bank. Choosing the same account for both ends asks again with a notice.
- An expense or income is tagged with an account only when the user names one that resolves to exactly one active account. The assistant never asks about accounts for them. An unresolved name is left untagged and the reply says so. A "from X" phrase naming one of the user's accounts is an account, not a merchant.
- The saved slip shows "HDFC → Paytm Wallet" for a transfer and "from HDFC" for a tagged expense ("into HDFC" for income). Chat search accepts transfers as a type.
- New eval cases cover transfer and "paid from" phrasing. Over repeated live runs, the eval stays at Phase 1 accuracy with no meaningful latency regression.

### Account security

- `GET /auth/sessions`: the user's active sessions (not revoked, not expired) with id, device label, IP address, createdAt, lastSeenAt and isCurrent; the current one first, then by last activity. A small, unit-tested user-agent reader produces the device label ("Chrome on Windows", "Safari on iPhone", "API client") without a new dependency.
- `DELETE /auth/sessions/{id}` revokes one session (404 for an unknown or another user's id). Revoking the current session signs this device out, like logout.
- `POST /auth/sessions/revoke-others` revokes every other session and returns how many.
- `POST /auth/password` (`currentPassword`, `newPassword`) checks the current password, the password policy, and that the new password differs; rehashes with Argon2id; revokes every other session; keeps the current one. Errors are 422 with the field named. Rate-limited like login.
- **Password reset tokens**: an `identity` table with the user, the SHA-256 of a random token, created time, expiry (30 minutes), used time and the requesting IP. A new request invalidates the user's earlier unused tokens.
- `POST /auth/password-reset` (`email`) always returns 202 with the same body, whether or not an active user has that email. It is rate-limited per email (hashed) and per IP. The email is sent outside the request path, so the response time does not reveal whether the user exists.
- `POST /auth/password-reset/confirm` (`token`, `newPassword`) returns 204: it sets the password, marks the token used, revokes every session of the user, and audits. An unknown, used or expired token is 422 `reset_link_invalid`, with a message saying to request a new link.
- The reset link is `<WEB_BASE_URL>/reset-password#token=<token>`. The token travels in the URL fragment, so it never reaches server logs or Referer headers. `WEB_BASE_URL` is a new setting.
- Email goes through an `EmailSender` interface. The only implementation is a console sender: outside production it logs the message, link included; in production it logs a warning without the link and sends nothing. Tests inject a capturing sender through the app factory, the way they inject the LLM and the clock.
- Audit actions: `auth.session_revoked`, `auth.other_sessions_revoked`, `auth.password_changed`, `auth.password_reset_requested` (only for existing users) and `auth.password_reset`.
- **Web**: Settings → Security (device list marking "This device", sign out per device, sign out all others, change-password form). The login page links "Forgot password?" to a forgot-password page (neutral confirmation), and the link in the email opens a reset-password page (new password twice), which returns to login with a "password changed" notice. Both pages work signed out.

### Web

- The settings page becomes a stack of independent section components sharing one section frame (a prefactor), so Accounts, Merchant rules and Security each add one section.
- New screens use the existing UI primitives, TanStack Query hooks and generated API types.

## Testing Decisions

- A good test exercises external behaviour through the highest seam: an HTTP request into the real app (ASGI transport) against real Postgres and Redis, with the offline parser standing in for the language model, as the Phase 1 integration tests do. It asserts what a user or client observes (status codes, JSON, saved transactions read back through the API, chat replies and interactions), never internal calls.
- Where a behaviour depends on what the model returns, the test swaps in a scripted model through the existing switchable LLM fixture.
- Pure deterministic logic gets fast unit tests: merchant key normalisation, category precedence, the user-agent reader, account-name resolution and kind inference, transfer draft issues, and the offline parser's transfer phrasing.
- Every new user-scoped resource gets an isolation test: another user gets a 404 and is unaffected.
- Prompt v2 is measured with the live eval over repeated runs, and the numbers go in the phase report.
- Web changes are verified by typecheck, lint and production build. No browser end-to-end tests this phase.
- Prior art: the chat integration tests (the `say()` helper drives turns and clarifications), the transaction tests (idempotency, optimistic locking, audit), the isolation tests, the auth tests (two clients prove revocation), the workflow-logic and reconcile unit tests, and the understanding eval cases.

## Out of Scope

- Account balances and opening balances (deferred until most transactions carry an account: Phase 4 imports, Phase 7 debt).
- Currency conversion, and transfers between accounts in different currencies.
- A real email provider, email verification, and two-factor sign-in.
- Data export, user deletion and transcript retention (data rights were not taken into this phase).
- Measurable NFR targets and an eval-accuracy release gate.
- Browser end-to-end tests.
- Creating merchant rules by hand, or a "never learn this merchant" switch.
- Splitting one transaction across categories or accounts.
- Hard-deleting accounts.

## Further Notes

- The precedence rule in one sentence, for users: "If you pick or name a category, I use it; otherwise I use what you used last time for that merchant; otherwise I guess, or ask."
- Learning from every save, model guesses included, was the user's choice over learning from explicit choices only. Because a merchant rule outranks the model's guess, a guess is only learned for a merchant that had no rule, and a correction always wins.
- Parallel build: each schema-changing ticket chains its migration onto the integration branch head and re-chains when it merges; generated contracts are regenerated, never hand-merged.
