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
A place where the user's money is held or owed. Its kind is bank, credit card, loan, wallet, cash or other. Optional on an expense or income ("paid from HDFC"); a transfer always has one at each end.
_Avoid_: wallet (one kind of account), source, user account (that is the User)

**Asset account**:
An account whose balance is money the user holds, such as a bank, wallet or cash account. Money in increases it and money out decreases it.
_Avoid_: positive account

**Liability account**:
An account whose balance is money the user owes, currently a credit card or loan. Spending or borrowing through it increases the amount owed; refunds and repayments decrease it.
_Avoid_: debt (the amount owed), negative account

**Account balance**:
The amount held in an asset account or owed on a liability account, computed from a balance anchor and later cash movements. It is unknown when the account has no anchor.
_Avoid_: Balance (that is what one friend owes another), current total

**Balance anchor**:
An exact signed amount at the start of a stated local date, from which later account movements are applied. Positive means held for an asset or owed for a liability; negative means overdraft or credit. It is a fact about an account, not a transaction.
_Avoid_: opening transaction, assumed balance

**Credit-card bill**:
A card issuer's request for payment for one non-overlapping statement period, with a statement date, due date, total due and optional minimum due.
_Avoid_: card expense, statement (that is an imported file)

**Bill payment**:
The part of a transfer into a credit-card account allocated to one credit-card bill. It reduces the bill and the card's amount owed but is not spending.
_Avoid_: card expense, repayment (used broadly for loans)

**Debt plan**:
The lender, installment and next due date attached to one loan account. It tracks obligations but does not calculate interest or an amortisation schedule.
_Avoid_: loan (that is the account), repayment schedule

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
_Avoid_: stats

**Report**:
A chart-ready view of one period: exact totals, an equal-length comparison, trends, categories and
merchants, always kept separate by currency.
_Avoid_: dashboard, analytics (the reports module computes it)

**Saved report snapshot**:
A report kept in a conversation as it was when generated, with its period, currency and generation
time. Opening its full report link shows the current records for the same period and currency.
_Avoid_: live chat report, cached report

**Comparison period**:
The immediately preceding period with the same number of days as the selected report, clipped only
by the earliest allowed date.
_Avoid_: previous month (unless the dates actually cover that month)

**Insight**:
A short deterministic fact supported by report values, such as the largest expense category or the
change from the preceding period. It is not a forecast, anomaly claim or financial advice.
_Avoid_: recommendation, prediction, AI insight

### Imports

**Statement**:
A CSV or Excel file of one account's transactions, exported from a bank or card website.
_Avoid_: bank file, export, passbook

**Import**:
One upload of a statement into one account, which becomes many transactions after the user confirms the preview. It can be undone as a whole.
_Avoid_: upload (that is the act), batch, sync

**Statement layout**:
The columns, date order and worksheet used to read an account's statements. The confirmed layout is remembered for the next import with the same headers.
_Avoid_: mapping, template, format

**Import preview**:
The statement rows, detected layout and proposed changes shown for review before confirming an import.

**Row fingerprint**:
The identity of one occurrence of a statement row within an account. An identical payment can appear more than once in the same statement and each occurrence can be imported once.

**Likely duplicate**:
A statement row that matches a transaction the user already has in that account on date, amount and direction. The preview shows the match and leaves the row unticked for the user to review.
_Avoid_: dupe, conflict

**Matched transfer**:
A statement row that represents one side of a transfer already recorded between the user's accounts. Both statement sides can refer to the same transfer.

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

**Assistant language**:
The user's choice of English, Hinglish or Gujarati for chat replies and voice input. It is separate from locale, which controls date and money formatting.
_Avoid_: locale, translation language

**Voice transcription**:
Editable text produced from one push-to-talk recording before the user sends it as a turn. The recording itself is not a turn and is not retained.
_Avoid_: voice command (it has no effect until sent), audio message

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

**Friend balance**:
What one person owes another across their shared expenses and settlements, per currency, such as "Jaymin owes you ₹500". It is unrelated to an account balance.
_Avoid_: debt, due, outstanding, account balance

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
