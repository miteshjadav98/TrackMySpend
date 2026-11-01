# A share is an expense in each user's own records

A shared expense is the first thing two users can both see, but the rule "every transaction
belongs to one user, and another user's row is a 404" stays true. The shared expense, its
shares and settlements live in their own tables, visible only to their participants. Each
participant who is a user gets an ordinary expense transaction for their share, in their own
records, linked to the shared expense. Summaries, category totals and search therefore add up
shares with no change, and the friend's category, account tag and notes stay their own.

## Considered Options

- **One transaction for the payer's full amount, with a share column that summaries use.**
  Rejected: every total in the codebase would have to switch columns, and the friend would
  have no row of their own to file or tag.
- **One transaction visible to both users.** Rejected: it breaks per-user scoping everywhere,
  and the two users would fight over its category.

## Consequences

- A share transaction's amount, currency, date and type are read-only through the transaction
  endpoints; they change only through the shared expense, which updates every participant's
  share in one database transaction.
- The money that left the payer's account (the full total) is not stored as a transaction
  amount. That is fine while accounts have no balances. Account balances will need to add the
  shares the user paid for others.
