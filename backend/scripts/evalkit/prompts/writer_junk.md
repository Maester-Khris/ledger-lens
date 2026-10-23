You write evaluation questions for a chat assistant that answers questions about a fixed set of investment advisory
agreements (fund-level advisory and sub-advisory contracts filed with the SEC, plus one synthetic household
agreement). It must refuse or ask for clarification when a question cannot be answered from those agreements.

Write exactly $count questions of the category "$category":
- out_of_corpus: about fees, advisers or contracts in general, worded like a real question, but about a contract or
  fact that is NOT one of the agreements listed below (another fund family, a bank account, a mortgage). Expect "refuse".
- underspecified: asks for one contract term without naming which contract, for example "What is the fee?". Use only
  these terms and set "field_path" to the term asked: $fields. Expect "clarify".
- nonsense: grammatical but meaningless, or random words. Expect "refuse".
- off_topic: unrelated to contracts or finance (cooking, sport, coding). Expect "refuse".

Agreements in the set (do not ask about these for out_of_corpus):
$titles

Vary the wording; no two questions alike. Reply with JSON only, no prose:
{"cases": [{"category": "$category", "question": "...", "expect": "refuse", "field_path": null}]}
