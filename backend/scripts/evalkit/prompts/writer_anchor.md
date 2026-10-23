
Also answer these questions about the agreement, each about one term (its field_path is given before the colon):
$questions
Give each value as the agreement states it: a short string, a date as YYYY-MM-DD, a number, a list of names for
"signatories", or for "fee_tiers" the whole fee table as a list of {"band_text": "...", "rate_text": "..."} objects in
the order written. If the text does not state it, use null. Add them to the same JSON reply as a second list:
"anchors": [{"field_path": "...", "value": ..., "gold_element_ids": ["..."], "page": 1}]
