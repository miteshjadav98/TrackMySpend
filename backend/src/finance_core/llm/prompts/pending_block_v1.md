
## Pending question
The assistant just asked the user: "{question}" (about the transaction's {field}).
{options_line}
Decide whether the user's latest message answers that question.
- If it does: set pending_answer = {{"answers_question": true, "value": <answer>}} and
  intent = "record_transactions" with an empty transactions list. Give the value as a
  category slug, a plain amount string, a date as YYYY-MM-DD, "expense"/"income", or
  "yes"/"no", whichever the question needs.
- If it is a new request instead: set pending_answer = {{"answers_question": false}} and fill
  everything else for the new request as usual.
