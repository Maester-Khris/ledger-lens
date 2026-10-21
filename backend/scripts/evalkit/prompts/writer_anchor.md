Read the investment advisory agreement "$title" below and answer one question from its text. Each line starts with
an element id in square brackets and a page number.

Question: $question
The term asked is "$field_path". Give its value as the agreement states it: a short string, a date as YYYY-MM-DD, a
number, a list of names for "signatories", or for "fee_tiers" the whole fee table as a list of
{"band_text": "...", "rate_text": "..."} objects in the order written. If the text does not state it, use null.

Reply with JSON only, no prose:
{"value": ..., "gold_element_ids": ["..."], "page": 1}

Agreement text:
$text
