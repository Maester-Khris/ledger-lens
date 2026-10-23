# CPU profile: chat turns at 40 conversations, after C1-C3b

Same method as `2026-10-15-profile-gil-40.md`: py-spy 0.4.2 --gil (only the thread holding the GIL: Python CPU work, not I/O or idle waits), 100 Hz, whole machine (no BOX), provider mock and stub index, 2 minutes at 40 conversations (`PROFILE=1 scripts/load/run_chat.sh profile-gil-40-after 40 2m`). Code at commit e3ef002 (C1, C2, C3a, C3b on top of N4). 7.78 turns/s, p50 3.83 s, p95 6.74 s, 0 failed; 1,020 turns. About 55 CPU-seconds sampled: **about 54 ms of Python CPU per turn, against about 90 ms before (-40%)**. Limits: one run; the stub index skips the Pinecone client's own CPU; C code that releases the GIL is not counted; py-spy could not read 1 sample.

What is left, inclusive: tool calls 30% (search 22%: dense matching 12%, section text reads 7%, which T1 cuts to one read per section), PII tokenising 12.6% (now mostly psycopg dumping the about 620 candidate tokens as an array, 2.0%, and the HMAC copies, 3.2%), the turn's opening session 8%. Self time: SQLAlchemy 18% (was 24%), the OpenAI client 10% and typing 8% (request and response handling, which shrinks with smaller requests, Section 2).

samples: 5519 (about 55 CPU-seconds)

## Self time by library

| Share | Samples | Where |
|---|---|---|
| 18.1% | 1001 | sqlalchemy |
| 10.2% | 561 | openai |
| 8.4% | 466 | typing |
| 7.4% | 411 | psycopg |
| 4.6% | 256 | app (our code) |
| 4.5% | 247 | langchain_core |
| 4.0% | 222 | asyncio |
| 4.0% | 221 | pregel |
| 3.7% | 206 | pydantic |
| 3.4% | 189 | httpx |
| 3.3% | 180 | hmac |
| 3.1% | 172 | httpcore |
| 2.9% | 160 | anyio |
| 2.2% | 120 | json |
| 2.1% | 116 | inspect |
| 1.9% | 105 | h11 |
| 1.7% | 96 | <string> |
| 1.2% | 64 | contextlib |

## Self time by function

| Share | Samples | Where |
|---|---|---|
| 3.6% | 201 | get_origin (typing.py) |
| 2.6% | 141 | _async_transform_recursive (_transform.py) |
| 2.4% | 131 | __hash__ (typing.py) |
| 2.2% | 120 | construct_type (_models.py) |
| 2.0% | 113 | run (runners.py) |
| 2.0% | 112 | copy (hmac.py) |
| 2.0% | 108 | dump_list (array.py) |
| 1.4% | 79 | tokenize_known_values (dao.py) |
| 1.2% | 67 | expect (coercions.py) |
| 1.2% | 67 | _gen_cache_key (cache_key.py) |
| 1.2% | 65 | __init__ (<string>) |
| 1.2% | 64 | hexdigest (hmac.py) |
| 1.1% | 60 | iterencode (encoder.py) |
| 1.0% | 53 | _raw_all_rows (result.py) |
| 0.9% | 52 | is_union (_compat.py) |
| 0.9% | 51 | raw_decode (decoder.py) |
| 0.7% | 36 | ensure_config (config.py) |
| 0.6% | 34 | _async_transform_typeddict (_transform.py) |

## Inclusive time, our code

| Share | Samples | Where |
|---|---|---|
| 30.2% | 1669 | run_tools (app/assistant/graph.py) |
| 30.1% | 1663 | execute (app/assistant/tools.py) |
| 22.6% | 1248 | _search_contracts (app/assistant/tools.py) |
| 22.3% | 1229 | search (app/retrieval/search.py) |
| 12.6% | 693 | tokenize_known_values (app/documents/dao.py) |
| 11.8% | 653 | dense_matches (app/retrieval/search.py) |
| 10.4% | 575 | _with_session (app/assistant/service.py) |
| 8.5% | 467 | stream (app/routes/chat.py) |
| 8.3% | 456 | run_turn (app/assistant/service.py) |
| 8.0% | 442 | _open_turn (app/assistant/service.py) |
| 6.9% | 380 | section_texts (app/retrieval/dao.py) |
| 3.8% | 209 | make (app/documents/redact.py) |
| 2.6% | 144 | <module> (app/main.py) |
| 2.4% | 133 | register_guest (app/routes/guests.py) |
| 2.0% | 108 | current_element_ids (app/retrieval/dao.py) |
| 1.8% | 97 | get_guest_id (app/deps.py) |
| 1.8% | 97 | touch_guest (app/assistant/dao.py) |
| 1.7% | 94 | purge_stale_overlays (app/assistant/overlays.py) |

