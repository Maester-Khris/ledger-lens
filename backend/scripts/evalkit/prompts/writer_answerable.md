You write evaluation questions for a chat assistant that answers questions about investment advisory agreements
from the agreements' text. Below is one agreement, "$title" (key: $document_key). Each line starts with an element id
in square brackets and a page number. Personal names may appear as tokens such as <PERSON_1a2b>; keep them as they are.

Write exactly 2 questions a client or an operations analyst would ask about THIS agreement, each answerable from a
different clause (for example the fee rate or schedule, how often fees are billed, how fees are calculated, the
governing law, termination notice, the effective date, the parties). Name the agreement in each question (by its fund
or adviser name) so it is clear which contract is meant.
$false_premise_rule$anchor_rule
Rules:
- The answer must be stated in the text. Do not ask about anything the text does not say.
- "reference" is the correct answer in one or two sentences, using the text's own figures.
- "expect_numbers" lists every number the correct answer must contain, as written (for example "0.75", "30").
- "gold_element_ids" lists the ids of the lines that contain the answer, copied exactly from the brackets.
- "page" is the page of the first gold line.

Reply with JSON only, no prose:
{"cases": [{"category": "answerable", "question": "...", "expect": "answer", "reference": "...",
"expect_numbers": ["..."], "gold_element_ids": ["..."], "page": 1}]}

Agreement text:
$text
