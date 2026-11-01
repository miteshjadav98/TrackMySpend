# Phase 3: split expenses with friends

Status: ready-for-agent
Integration branch: `phase-3/integration`
Tickets: `issues/` in this directory
Input: [brief.md](brief.md), settled in a grilling session on 2026-11-01.

## Problem Statement

I often pay for things with friends: a pizza with Jaymin, a cab with Jaymin and Riya. Today
MoneyMoney records the whole 1000 as my spending, even though half of it was Jaymin's, and it
cannot remember that Jaymin owes me 500. I keep that in my head or in another app. When Jaymin
pays me back, I have no right way to record it: as income it inflates what I earned, and it is
not a transfer between my own accounts.

My friends who also use MoneyMoney have to type the same pizza in again on their side.

## Solution

I keep a friends list. In chat I say "me and Jaymin spent 1000 on pizza, split it", and
MoneyMoney records a **shared expense**: I paid, the split is equal, and my **share** of 500 is
what counts in my spending and my Food & Dining total. It shows "Jaymin owes you ₹500", worked
out from every shared expense and **settlement** between us. When Jaymin pays me back, I say
"Jaymin paid me 500" and the **balance** goes to zero, without counting as income.

If Jaymin uses MoneyMoney and has accepted my friend invite, the shared expense lands in his
records straight away. His share counts as his spending, under his own category, and the next
time he opens the app he sees a "Shared with you" card. He sees only that shared expense, never
anything else of mine.

## User Stories

**Friends list**

1. As a user, I want to add a friend by name, so that I can split with people who don't use MoneyMoney.
2. As a user, I want to give a friend an optional email, so that MoneyMoney can link us if they use it.
3. As a user, I want a friend whose email belongs to a MoneyMoney user to get an in-app invite, so that we can share expenses once they agree.
4. As a user, I want an invite to an email with no account to wait until someone signs up with that email, so that I can add friends before they join.
5. As an invited user, I want to accept or decline a friend invite, so that nobody's expenses land in my records without my say.
6. As a user, I want accepting an invite to link us both ways, so that each of us appears in the other's friends list.
7. As a user, I want to rename a friend on my side, so that the name matches how I talk about them.
8. As a user, I want to remove a friend who has no shared expenses or balance, so that my list stays tidy.
9. As a user, I want removing a friend with history to archive them instead, so that past shared expenses and balances stay correct.
10. As a user, I want to see each friend's balance in my friends list, so that I know who owes whom at a glance.
11. As a user, I want a friend with the same name as another to be told apart by email, so that I pick the right one.

**Recording a shared expense in chat**

12. As a user, I want to say "me and Jaymin spent 1000 on pizza, split it", so that a shared expense is recorded in one message.
13. As a user, I want MoneyMoney to assume I paid unless I say a friend paid, so that the common case needs no question.
14. As a user, I want to say "Jaymin paid 1000 for pizza, split it", so that a friend can be the payer.
15. As a user, I want an equal split by default, so that "split it" just works.
16. As a user, I want to give exact amounts ("I had 400, Jaymin 600"), so that uneven bills are right.
17. As a user, I want exact amounts that don't add up to the total to trigger a clarification, so that nothing wrong is saved.
18. As a user, I want leftover paisa to go to the payer's share, so that the shares always add up exactly.
19. As a user, I want the save card to show the total, who paid, and each person's share, so that a wrong guess is easy to spot.
20. As a user, I want the category to follow the usual category precedence, so that shared expenses file like my other expenses.
21. As a user, I want to tag my shared expense with the account I paid from, so that "paid from HDFC" still works.
22. As a user, I want the chat to ask which Jaymin when two friends match, so that the right person is charged.
23. As a user, I want the chat to offer to add an unknown name as a new friend, so that I don't have to leave the chat first.
24. As a user, I want a shared expense with several friends ("me, Jaymin and Riya spent 1500 on cab, split it"), so that group bills work without groups.
25. As a user, I want a shared expense in a currency other than my base currency, so that a trip abroad works, kept apart from my other currencies.

**Shares in my records and summaries**

26. As a user, I want only my share to count in my summaries and category totals, so that my spending is honest.
27. As a user, I want my share to appear in my transaction list as an expense marked as shared, so that I see it with my other spending.
28. As a user, I want to open a shared expense and see the total, the payer and every share, so that I can check the split.
29. As a user, I want "show my shared expenses this month" in chat, so that I can find them.

**Balances and settlements**

30. As a user, I want to ask "how much does Jaymin owe me?" in chat, so that I get the balance in one message.
31. As a user, I want balances per currency, so that rupees and dollars never mix.
32. As a user, I want to say "Jaymin paid me 500", so that a settlement reduces the balance.
33. As a user, I want to say "paid Jaymin 500" when I owe him, so that my settlement is recorded too.
34. As a user, I want a settlement never to count as spending or income, so that my summaries stay honest.
35. As a user, I want to tag a settlement with the account the money went into or left, so that I know where it went.
36. As a user, I want "paid Ramesh 2000 for his old phone" to stay an expense, so that buying from a friend isn't mistaken for paying back.
37. As a user, I want to record a settlement from the friends page as well, so that I don't need chat for it.

**The friend's side**

38. As a linked friend, I want a shared expense to land in my records straight away, so that I don't type it again.
39. As a linked friend, I want my share filed under my merchant rule, else the payer's built-in category, else Other, so that it lands somewhere sensible.
40. As a linked friend, I want to change my own category and account tag on my share, so that it fits my records without touching the other person's.
41. As a linked friend, I want to see only the shared expense (description, date, total, payer, shares), so that I never see the other person's account, category or other records.
42. As a linked friend, I want a "Shared with you" card on home and in chat, and a badge, on my next visit, so that I notice new shared expenses.
43. As a linked friend, I want a settlement my friend records to show up on my side, so that our balances agree.
44. As a user, I want my past shared expenses with a friend to reach them when they link, so that our balances match from day one.

**Edits and deletes**

45. As the user who recorded a shared expense, I want to change its amount, split, payer, date or description, or delete it, so that I can fix mistakes.
46. As a participant, I want a notice when a shared expense I'm in changes or is deleted ("Mitesh changed Pizza: your share is now ₹600"), so that I know my records moved.
47. As a participant who didn't record it, I want the amount, split, payer and date of my share to be read-only, so that two people never edit the same split differently.
48. As the recorder or the friend, I want a settlement to be deletable by whoever recorded it, with a notice to the other, so that a mistaken settlement can be undone.

**Safety**

49. As a user, I want another user's shared expense that I'm not in to be a 404, so that sharing never leaks anything else.
50. As a user, I want every shared-expense, settlement and friend change in the audit log, so that I can see who changed what.

## Implementation Decisions

**Model (see ADR 0001)**

- A new domain module **friends** owns friends, friend invites, shared expenses, shares and
  settlements, plus balance queries. It joins the import-linter "domain services" contract.
- A **friend** row belongs to one user: a name, an optional email, an optional linked user,
  and an archived flag. Linking is by an accepted invite. Accepting creates (or links) the
  mirror friend row on the other side, so each user has their own friend row for the other.
  An invite to an email with no user waits; when someone signs up or signs in with that
  email, they see it.
- A **shared expense** has a recorder (the user who created it), a payer (the recorder or one
  of the recorder's friends), a total in minor units, a currency, a date, a description and an
  optional merchant, with one **share** per participant (the recorder or a friend of the
  recorder), each in minor units. The shares sum to the total, enforced in the service and by
  a deferred check where Postgres allows it.
- Every participant who is a MoneyMoney user (the recorder, and linked friends) gets an
  ordinary **expense transaction** in their own records, for their share, linked to the
  shared expense. That keeps "every transaction belongs to one user" true, and summaries,
  category totals and search need no change: they already add up each user's own
  transactions. The share transaction's amount, currency, date and type are read-only through
  the transaction endpoints; they change only through the shared expense. Its category,
  account tag and notes stay the owner's to change.
- When a friend paid, only the user and that payer can be in the shared expense this phase,
  because MoneyMoney shows balances only between the user and each of their friends.
- A **settlement** has a from-person and a to-person (the user and one friend), an amount, a
  currency, a date, an optional note, and an optional account tag on each user's side. It is
  not a transaction, so it never appears in summaries.
- A **balance** between the user and a friend, per currency, is computed in SQL: the friend's
  shares of expenses the user paid, minus the user's shares of expenses the friend paid,
  minus settlements from the friend to the user, plus settlements from the user to the friend.
  Positive means "the friend owes you".
- For an unlinked friend the shared expense exists only on the recorder's side. When the friend
  links, each existing shared expense and settlement with them creates their share
  transaction and shows up on their side in one go.
- **Leftover paisa:** an equal split gives each share the floor of total ÷ people, and the
  payer's share takes the remainder.
- **The linked friend's category:** their merchant rule for the merchant; else their category
  with the same built-in slug as the recorder's; else Other. Their share teaches their merchant
  rule only when they change its category themselves.

**Visibility and authorization**

- A shared expense or settlement is visible to its participants who are users, and is a 404 to
  everyone else. The friend sees description, date, total, currency, payer and every share,
  with each person named as that friend calls them where known, else by the name the recorder
  gave. Never the recorder's account, category, notes or anything else.
- Only the recorder edits or deletes a shared expense. Only whoever recorded a settlement
  deletes it. Every change updates every participant's share transaction in the same database
  transaction, records an audit event for each affected user, and leaves a notice.

**Notices**

- A new **notice** record per user (who, what happened, the shared expense or settlement, read
  or not). The home page and chat show unread notices as a "Shared with you" card, and the nav
  shows a badge count, loaded on page show. No live push, email or browser notifications.

**Chat**

- A new versioned understand prompt adds: participants (names as said), payer (me or a name),
  split kind (equal or exact), per-person exact amounts, and two new intents or types: a
  shared expense (an expense with participants) and a settlement (paying back, either
  direction). Plus a balance question ("how much does Jaymin owe me"). Measured with the live
  eval over repeated runs, with new eval cases.
- The offline parser learns the same shapes ("me and X spent N on Y, split it", "X paid me N",
  "paid X N" when there is a balance with X, "how much does X owe me").
- Friend names resolve like account names: exact ignoring case, else word containment, else
  ask. An unknown name gets the clarification "Add Jaymin as a new friend?".
- "paid X N" is a settlement only when the user has a non-zero balance with X in that
  currency and the message reads as paying back; otherwise it stays an expense with X as
  merchant.
- The save card shows the total, "You paid" or "Jaymin paid", and each share.

**API and web**

- REST endpoints for friends (list with balances, add, rename, set email, archive or remove),
  invites (list incoming, accept, decline), shared expenses (create, read, update, delete,
  list), settlements (create, list, delete) and notices (list, mark read). Contracts are
  regenerated.
- Web: a Friends page (list with balances, add friend, incoming invites, a friend's history of
  shared expenses and settlements, record settlement), the shared marker and detail on
  transaction rows, the "Shared with you" card on home and in chat, and the nav badge.

**Schema**

- New Alembic revisions on the single head for friends, friend invites, shared expenses,
  shares, settlements and notices, plus a nullable shared-expense link on transactions.

## Testing Decisions

- Tests check behaviour at the highest seam, not internals: the HTTP API with two real users
  (integration tests that drop and re-migrate the test database), and the chat workflow end to
  end, as the existing `test_chat_*` integration tests do.
- Two-user tests are the core: Mitesh records, Jaymin sees it; Jaymin never sees anything
  else; a third user gets 404 everywhere.
- Balances are checked against hand-computed values across mixed shared expenses and
  settlements in two currencies.
- Split arithmetic (equal with leftover paisa, exact amounts that don't add up) gets pure unit
  tests, like the account-name tests.
- The understand prompt is measured with the live eval over at least five runs, with new cases
  for shared expenses, settlements and balance questions; the offline parser gets unit tests for
  the same phrases.
- Prior art: `tests/integration/test_chat_transfers.py`, `test_chat_paid_from.py`, the accounts
  API tests, and `tests/unit/test_transfer_understanding.py`.

## Out of Scope

- Groups (a trip, flatmates), and a friend-paid expense with more than one other participant.
- Percentage and share-count splits.
- Currency conversion, or settling in a different currency.
- Email, push or live notifications.
- Account balances.
- Splitting an income, or splitting a transfer.
- Reminders to pay back, and simplifying debts across several friends.

## Further Notes

- The glossary already defines friend, shared expense, payer, share, split, balance and
  settlement. "Paying a friend" in the expense definition now means paying for something;
  paying back is a settlement.
- Phase 4+ (from the brief): imports, charts, MCP, voice.
