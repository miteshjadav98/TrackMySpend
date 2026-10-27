# MoneyMoney

A chat-first personal finance tracker: people say what they spent, earned or moved in plain
language, and MoneyMoney keeps an exact record they can search, correct and summarise.

## Language

### Money records

**Transaction**:
One movement of money in the user's records: an expense, an income or a transfer.
_Avoid_: entry, record, txn

**Expense**:
A transaction where money leaves the user's hands for something outside, such as buying lunch or paying a friend.
_Avoid_: spend, debit, payment

**Income**:
A transaction where money arrives from outside, such as salary or a refund.
_Avoid_: credit, earning

**Transfer**:
A transaction that moves money between two of the user's own accounts, such as withdrawing cash or paying a credit card bill. It is never income or expense.
_Avoid_: payment (money sent to another person is an expense)

**Account**:
A place where the user's money is held: a bank account, credit card, wallet or cash. Optional on an expense or income; a transfer always has one at each end.
_Avoid_: wallet (one kind of account), source, user account (that is the User)

**Archived account**:
An account the user has retired: it stays on its past transactions but cannot be picked for new ones.
_Avoid_: deleted account, closed account

**Category**:
A label that groups expenses, or incomes, for summaries, such as Food & Dining. A category is for expenses or for income, never both.
_Avoid_: tag, type, bucket

**Merchant**:
The business or person a transaction names, such as Swiggy or Ramesh.
_Avoid_: payee, vendor, store

**Merchant rule**:
The category a user files a merchant under, learned from their saved transactions and used to file that merchant's next one. The user can change or forget it.
_Avoid_: merchant memory, mapping, learned merchant, rules engine (that is the offline parser)

**Base currency**:
The user's home currency, used whenever a message names no currency.
_Avoid_: default currency, home currency

**Period**:
The date range a summary or search covers, worked out in the user's own timezone, such as "October 2026 (1–26 Oct)".
_Avoid_: timeframe, window

**Summary**:
Income and expense totals for a period, per currency, computed from the saved transactions.
_Avoid_: report, stats

### Conversation

**Turn**:
One user message and everything the assistant does in response, up to its reply.
_Avoid_: request, exchange

**Draft**:
A transaction the assistant has understood from a turn but not saved yet, possibly with details still missing.
_Avoid_: pending transaction, candidate

**Clarification**:
A question the assistant asks to fill one missing or doubtful detail of a draft, with options where possible.
_Avoid_: follow-up, prompt

**Interaction**:
A typed piece of UI the assistant sends with a reply, such as a clarification, a saved slip, a summary or a list.
_Avoid_: widget, component, card (the card is how the web app draws one)

**Offline parser**:
The deterministic, rule-based reader of messages, used to cross-check the language model and to answer on its own when the model is unavailable.
_Avoid_: rules engine, fallback model

**Degraded turn**:
A turn the offline parser answered because the language model was unavailable.
_Avoid_: fallback turn

### People and access

**User**:
A person with a MoneyMoney login. Owns every transaction, account, category and merchant rule they create.
_Avoid_: account, customer, member

**Session**:
One signed-in browser or device of a user. The user can see each one and sign it out.
_Avoid_: login, token, device

**Password reset**:
Replacing a forgotten password through a single-use, short-lived link sent to the user's email.
_Avoid_: password recovery, forgot password (that is the screen's name)
