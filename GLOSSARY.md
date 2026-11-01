# MoneyMoney

A chat-first personal finance tracker: people say what they spent, earned or moved in plain
language, and MoneyMoney keeps an exact record they can search, correct and summarise.

## Language

### Money records

**Transaction**:
One movement of money in the user's records: an expense, an income or a transfer.
_Avoid_: entry, record, txn

**Expense**:
A transaction where money leaves the user's hands for something outside, such as buying lunch or paying a friend for something. Paying a friend back is a settlement.
_Avoid_: spend, debit, payment

**Income**:
A transaction where money arrives from outside, such as salary or a refund.
_Avoid_: credit, earning

**Transfer**:
A transaction that moves money from one of the user's own accounts (the "from" account) to another (the "to" account), such as withdrawing cash or paying a credit card bill. It has no category or merchant, both accounts must be in the amount's currency, and it is never income or expense.
_Avoid_: payment (money sent to another person is an expense)

**Account**:
A place where the user's money is held. Its kind is bank, credit card, wallet, cash or other. Optional on an expense or income ("paid from HDFC"); a transfer always has one at each end. There are no balances yet.
_Avoid_: wallet (one kind of account), source, user account (that is the User)

**Archived account**:
An account the user has retired: it stays on its past transactions but cannot be picked for new ones, and the user can unarchive it. Accounts are never deleted.
_Avoid_: deleted account, closed account

**Category**:
A label that groups expenses, or incomes, for summaries, such as Food & Dining. A category is for expenses or for income, never both.
_Avoid_: tag, type, bucket

**Merchant**:
The business or person a transaction names, such as Swiggy or Ramesh.
_Avoid_: payee, vendor, store

**Merchant rule**:
The category a user files a merchant under, learned from their saved transactions and used to file that merchant's next one. Expense and income rules are kept apart. The user can change or forget it in Settings; forgetting it does not stop MoneyMoney learning a new one from the next save.
_Avoid_: merchant memory, mapping, learned merchant, rules engine (that is the offline parser)

**Category precedence**:
The order in which a chat draft's category is chosen: the one the user picked in a clarification, then the one they named in the message, then the merchant rule, then the model's guess, and otherwise a clarification.
_Avoid_: category priority

**Base currency**:
The user's home currency, used whenever a message names no currency.
_Avoid_: default currency, home currency

**Period**:
The date range a summary or search covers, worked out in the user's own timezone, such as "October 2026 (1–26 Oct)".
_Avoid_: timeframe, window

**Summary**:
Income and expense totals for a period, per currency, computed from the saved transactions.
_Avoid_: report, stats

### Imports

**Statement**:
A CSV or Excel file of one account's transactions, exported from a bank or card website.
_Avoid_: bank file, export, passbook

**Import**:
One upload of a statement into one account, which becomes many transactions after the user confirms the preview. It can be undone as a whole.
_Avoid_: upload (that is the act), batch, sync

**Statement layout**:
Which column of an account's statement holds the date, description and amounts, confirmed by the user once and remembered for that account's next import.
_Avoid_: mapping, template, format

**Likely duplicate**:
A statement row that matches a transaction the user already has in that account (same date, amount and direction). It is left out of the import unless the user ticks it.
_Avoid_: dupe, conflict

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

### Sharing with friends

**Friend**:
Someone in a user's friends list: a name, and optionally an email. A friend may or may not have a MoneyMoney login; one who does, and accepts the invite, is a linked friend.
_Avoid_: contact, buddy, member (there are no groups)

**Shared expense**:
An expense split between the user and one or more friends, such as a pizza bill split with Jaymin. It has one payer, one currency and one share per person.
_Avoid_: split bill, group expense, shared transaction

**Payer**:
The person who paid a shared expense in full: the user, unless the message names a friend.
_Avoid_: owner, creditor

**Share**:
The part of a shared expense one person is responsible for. The user's share is what counts in their summaries and category totals, not what they paid.
_Avoid_: portion, cut, split (that is how the shares are worked out)

**Split**:
How a shared expense is divided into shares: equally, or by exact amounts. The payer's share takes any leftover paisa so the shares add up exactly.
_Avoid_: division, distribution

**Balance**:
What one person owes another across their shared expenses and settlements, per currency, such as "Jaymin owes you ₹500". Accounts still have no balances.
_Avoid_: debt, due, outstanding

**Settlement**:
A record that one person paid another to reduce their balance, such as "Jaymin paid me 500". It is never spending or income.
_Avoid_: repayment, settle-up, transfer (that moves money between the user's own accounts)

**Invite**:
An offer to link two users as friends, sent when a friend's email belongs to a MoneyMoney user. It is pending until the other user accepts or declines it, and the sender can cancel it by changing the friend's email.
_Avoid_: request, friend request

**Notice**:
An in-app message that a linked friend changed something in a record you share, shown on the "Shared with you" card. It is never sent as a push or an email.
_Avoid_: notification, alert

### People and access

**User**:
A person with a MoneyMoney login. Owns every transaction, account, category and merchant rule they create.
_Avoid_: account, customer, member

**Session**:
One signed-in browser or device of a user. The user can see each one in Settings, where it is labelled by device ("Chrome on Windows"), and sign it out.
_Avoid_: login, token

**Password reset**:
Replacing a forgotten password through a single-use link, valid for 30 minutes, sent to the user's email. Using it signs out every session. Until an email provider exists, the console email sender prints the email in the API log.
_Avoid_: password recovery, forgot password (that is the screen's name)

**Password change**:
Replacing the password while signed in, by entering the current one. It signs out the user's other sessions.
_Avoid_: password reset (that is for a forgotten password)
