# Account balances use dated anchors and cash effects

MoneyMoney does not know that an account started at zero. Imports may begin years after the account
opened, manually recorded transactions may omit an account and a shared expense records each
person's reporting share rather than the cash that left the payer. A balance is therefore known
only after the user supplies an exact signed amount held or owed at the start of a local calendar
date. Movements on and after that date are applied as cash effects. Positive means held for an
asset or owed for a liability; negative means an asset overdraft or liability credit, and the UI
labels that meaning explicitly.

Asset accounts show money held: money in increases the balance and money out decreases it.
Liability accounts show a positive amount owed: spending or borrowing through the liability
increases it, while refunds and repayments decrease it. A liability credit may produce a negative
amount owed and is labelled as a credit rather than silently clamped to zero.

Ordinary account-tagged transactions, transfers, statement imports and friend settlements supply
their natural cash effects. A shared expense uses the full amount on the payer's account and no
purchase-time cash effect for non-payers; reports continue to use each participant's share under
ADR 0001. Deleted and undone sources stop contributing.

## Considered options

- **Assume every account opened at zero and sum all known transactions.** Rejected: incomplete
  history would look exact while being wrong.
- **Store one mutable current-balance number.** Rejected: edits, import undo, restored transactions,
  shared-expense changes and backdated entries would require fragile compensating writes and make
  the result harder to audit.
- **Use the latest imported statement balance automatically.** Rejected for this phase: current
  import layouts deliberately ignore balance columns, and a file may be partial or use an
  ambiguous available/ledger balance. A future confirmed statement anchor can reuse this model.
- **Treat credit cards and loans like asset accounts with negative values.** Rejected: users think
  in a positive amount owed, and requiring negative opening input makes common liability flows easy
  to reverse accidentally.

## Consequences

- Existing accounts have an unknown balance until an anchor is set; unknown is never formatted as
  zero.
- Balance reads recompute deterministic effects from the anchor. If measured history length makes
  that slow, monthly checkpoints may be added without changing the external meaning.
- Anchor changes are audited facts, not transactions, and exclude all pre-anchor movements from
  the current balance while preserving them in history.
- Per-currency totals name excluded unknown accounts and follow ADR 0002; there is no combined
  cross-currency net worth.
- Shared-expense account tagging must distinguish the payer's cash account from each participant's
  personal reporting transaction.
