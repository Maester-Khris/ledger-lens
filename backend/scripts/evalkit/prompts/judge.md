You judge answers from a chat assistant that answers questions about investment advisory agreements. The cases are in
batch.jsonl, one JSON object per line: the question, a reference answer written from the agreement, the assistant's
answer, and the passages ("citations", each with an id and the quoted text) the assistant cited. Judge only from
what is in the case. Passage text may contain tokens such as <PERSON_1a2b>; treat them as names.

For every case return:
- "correct": true when the answer gives the same facts and figures as the reference answer (wording may differ,
  extra correct detail is fine); false when it contradicts the reference, misses a figure the reference states, or
  refuses to answer.
- "statements": split the answer into its factual statements, one entry each: {"text": the statement, "supported":
  true when the cited passages taken together say it}. A statement no cited passage supports is false, even when it
  is true in general.
- "citations": one entry per cited passage: {"id": its id, "relevant": true when the passage supports at least one
  statement of the answer; false when the answer's statements stand without it or it says nothing relevant}.

Return exactly one judgment per case in batch.jsonl, no more and no fewer, with its case_id:
{"judgments": [{"case_id": "...", "correct": true, "statements": [{"text": "...", "supported": true}],
"citations": [{"id": "...", "relevant": true}]}]}
