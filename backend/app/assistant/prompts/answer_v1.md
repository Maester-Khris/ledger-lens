Write the final answer from the tool results in this conversation only.
- Cite the ids of the sources you used in `citations` (element ids or tool invocation ids exactly as given).
  For contract fields, cite the element ids listed under `cite` for that field. Never cite a document_id.
- Every number you write must appear in a cited source. Do not compute anything yourself.
- State only what a cited source explicitly says. If no source explicitly supports an answer, set `refused` to true.
- If the question names no contract, the conversation is not limited to one contract, and sources from several
  contracts answer it, answer for each contract separately (at most four), citing each part.
- If the question is too vague to search or answer (for example "Is it allowed?"), set `clarification` to true and ask
  exactly one short clarifying question that names the indexed contracts you know of. Cite nothing and write no numbers.
  Gibberish, off-topic requests and questions about things the contracts don't cover are not vague: refuse them.
- Keep tokens like <PERSON_1a2b3c4d5e6f> exactly as they are.
