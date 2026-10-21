You check evaluation cases for a chat assistant that answers questions about investment advisory agreements. The
cases are in batch.jsonl, one JSON object per line. Agreement texts are in documents/<document_key>.txt (each line:
an element id in square brackets, a page, the text). For out_of_corpus cases, passages/<case id>.txt holds the
passages a search across all agreements found closest to the question. Read only the files in this folder.

For each case decide "agrees" (true or false) and give a one-sentence "reason":
- answerable: the reference answer is correct according to the agreement text, every number in expect_numbers is
  right, and the lines named in gold_element_ids contain the answer. Any error → false.
- false_premise: the question assumes something the agreement contradicts, and the line premise_element_id shows the
  contradiction. Otherwise → false.
- out_of_corpus: none of the passages given answers the question. If any passage answers it → false.
- nonsense, off_topic: the question really is meaningless, or really is unrelated to contracts and finance.
- underspecified: the question asks for the term in field_path without naming a contract.

Return one verdict for every case id in batch.jsonl, no more and no fewer:
{"verdicts": [{"case_id": "...", "agrees": true, "reason": "..."}]}
