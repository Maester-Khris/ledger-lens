# Chat eval: a corpus-wide answer key, threshold calibration and a publishable run

**Date:** 2026-10-21 · **Status:** approved by the owner (brainstorming, 2026-10-21) · **Backlog:** not epic-tracked

## Intent

Publish numbers that support one claim about the chat: **when it answers, the answer is right and every statement
in it points to a passage that actually says it; when it doesn't know, it says so instead of guessing.** The claim
must hold across the whole 102-document corpus, not the 4 documents the current golden set covers, and every rate
is published with its ± margin.

Why now: the golden set (37 written cases, 49 run) asks answerable questions about 4 of 102 documents, and at
about ±14% it is a smoke test. The relevance threshold is no longer clean on the larger corpus (`governing-law`
scores 0.446, between two junk cases at 0.445 and 0.456), so it cannot be recalibrated on the current set.

## Goals

1. An answer key of about 300 cases over the 102-document corpus, built and checked by models other than the one
   under test, with a human-checked anchor that measures the key's own error rate.
2. Calibrate the one retrieval threshold (`MIN_DENSE_SIMILARITY`) and record a generation confidence signal
   (logprobs), each swept against measured outcomes.
3. One final run on the deployed configuration (`gpt-4.1`), judged by a different model family, producing the
   published numbers with their margins and limits.

## Non-goals

- An escalation path (to a broader search, a stronger model or a person). This eval measures the two signals such
  a path would use (context recall, logprob confidence) and reports what a threshold would catch; the path is
  designed later from these numbers.
- A runtime check that retrieved context is sufficient (the "Sufficient Context" approach, ICLR 2025): measured in
  the eval through context recall only.
- Prompt, model or graph changes; extending the document corpus.

## Anti-goals (a failure even if it runs)

- Any model grading its own output, or a family grading a relative's answers.
- The final run's prompts, threshold candidates or metrics changed after its results are seen.
- A rate published without its sample size, ± margin and the limits below.
- A paid OpenAI call made without first checking its estimated cost against the remaining credit.

## Constraints

- **Budget:** OpenAI $3.43 (system under test only; the owner checks cost and tops up before any paid step that
  needs it); Anthropic $1.29 (API judge validation only); Groq free tier; Gemini through the owner's Google One
  subscription via agy (`gemini-4-argon-high`; 94% of the weekly quota left on 2026-10-21).
- **Groq free tier, per model:** 30 requests and 8k tokens per minute, 1k requests and 200k tokens per day. Usable
  for text: `qwen/qwen3.8-27b`, `openai/gpt-oss-120b`, `openai/gpt-oss-20b`.
- **Privacy:** only redacted document text (`document_elements.text_redacted`, PII tokens in place) leaves the
  machine, as in production. The corpus is public SEC filings plus one synthetic agreement.
- **One sitting:** the key build runs end to end without waiting on a daily cap.
- **Independence:** every stage is a separate process that reads only the previous stage's output file. All prompts
  and instruction files are committed before the stage that uses them runs.

## Model roles

| Role | Model | Why |
|---|---|---|
| Write questions and reference answers | Groq `qwen3.8-27b` (half the documents) and `gpt-oss-120b` (the other half), in parallel | not the system under test; parallel per-model limits fit one sitting (about 140k tokens each, about 18 min) |
| Check each case against its document | Gemini `gemini-4-argon-high` through agy | a third family, independent of the writers and the judge |
| Tiebreak a writer/checker disagreement | the Groq model of the other family from the case's writer (`gpt-oss-20b` for qwen cases, `qwen3.8-27b` for gpt-oss cases) | keeps the judge's family out of the key |
| Judge (calibration and final run) | Claude Sonnet 5.5 | never writes or checks the key, never answers |
| System under test | OpenAI `gpt-4.1-2025-04-14`, deployed configuration | what the demo runs |

`gpt-oss` is OpenAI's open-weights family, a relative of `gpt-4.1`. It writes part of the key but never grades
`gpt-4.1`; every case records its writer so results can be split by writer.

## Part 1: the answer key

**Mix (about 300):** about 190 answerable spread over all 102 documents (about ±7%); about 100 junk, about 20 each of
out of corpus, false premise, underspecified, nonsense and off topic (about ±10% overall, wider per category);
about 10 explained abstentions. The existing 37 cases stay in the set.

**Each answerable case stores:** question, reference answer, expected numbers, expected document, page, and the
**gold passages** (element ids) that hold the answer; its writer, checker verdict and tiebreak, if any.

**Flow:**
1. Writers produce candidate cases per document from the redacted text, through a client-side token limiter per
   model (no 429s, which broke the X1 Groq run). Junk cases not tied to one document are written by `qwen3.8-27b`.
2. The checker reads each batch of 30 to 50 cases in an empty folder holding only that batch, the redacted text of
   its documents and a frozen instruction file, and writes one verdict file. It confirms the reference answer and
   that the gold passages contain it. A script validates each verdict file's shape before the next stage reads it.
3. A disagreement goes to the tiebreak model. A case still disputed is dropped and counted.

**Junk checks that do not rely on the writer:**
- *Out of corpus:* the checker reads the top retrieved passages across all 102 documents and confirms none answers
  the question (not the similarity score: that is the threshold being tuned).
- *False premise:* the case carries the passage that contradicts its premise; the checker confirms it.
- *Underspecified:* a database query confirms the asked field has at least 2 different values across documents.
- *Explained abstention:* built from data (contracts with no billing household); no model.
- *Nonsense, off topic:* the checker confirms the category.

**Human anchor:** cases built on the 128 X1 fields the owner adjudicated (`field_labels`, labeller `adjudicated`)
measure the key's own error rate, which is published next to the headline numbers.

## Part 2: calibration

**Retrieval threshold.** `MIN_DENSE_SIMILARITY` is the one floor below which a passage is dropped before the model
sees it: 0.43 in the local `.env` (September calibration on 4 documents), 0.46 in the code default and on the demo.
The sweep tries 0.38 to 0.50 in 0.01 steps, bracketing every score that matters so far (out of corpus 0.357, junk
0.445 and 0.456, `governing-law` 0.446, lowest correct 0.505). For each value, from retrieval scores alone (embeddings
only, under $0.05): answerable cases whose gold passage is cut, and junk cases with a passage let through. The same
data gives top-5 against top-8 and context recall. The chosen value (no answerable passage cut and the fewest junk
through, or the owner's trade-off if those conflict) is frozen before the paid run and then replaces both 0.43 and
0.46.

Limit: the sweep shows what reaches the model, not what the model does with it. Chat runs on the borderline cases
near the chosen value (about $0.6 per value) confirm it, only if the owner tops up.

**Generation confidence.** `gpt-4.1` token logprobs are recorded on every answer call and averaged into one score per
answer. The threshold is swept offline against the judge's right/wrong labels from the final run, with no extra
chat run. First check: that the structured-output path through LangChain returns logprobs for the answer call.
Logprobs measure how sure the model was of its wording, not whether it is true; the sweep is read against the
labels, never as a probability.

## Part 3: the final run

- **System under test:** the deployed configuration, `gpt-4.1` with the frozen threshold, one run on every case.
- **Judge:** Claude Sonnet 5.5 through headless `claude -p` on the owner's subscription: model pinned (`--model`),
  tools off, a fresh process every about 20 cases, in an empty folder with a frozen instruction file, JSON output
  validated by a script. Validated first on 30 cases through the Anthropic API (about $0.27); the agreement is
  published.
- **Metrics,** each with n and ± margin:
  - answer correctness on answerable cases, against the reference answer;
  - citation recall (ALCE): each statement supported by the union of its citations;
  - citation precision (ALCE): a citation is irrelevant when its statement is supported without it;
  - refusal accuracy on junk, by category; over-refusal on answerable cases;
  - context recall: the gold passages were retrieved; each wrong answer is classed as a retrieval failure (passage
    never arrived) or a generation failure (arrived, still wrong);
  - accuracy above and below the swept confidence threshold, and the share an escalation would have caught;
  - every rate split by writer.

## Budget gates

| Step | Provider | Estimate |
|---|---|---|
| Key build | Groq, Gemini | free |
| Retrieval sweep and out-of-corpus checks | OpenAI embeddings | under $0.05 |
| Judge validation, 30 cases | Anthropic API | about $0.27 |
| Final run, about 300 turns at $0.0093 to $0.011 | OpenAI `gpt-4.1` | $2.8 to $3.3 |
| Judging | Claude subscription | no cash |

Every paid OpenAI step is estimated and checked against the credit before it runs (owner rule); each run is
recorded in `artifacts/2026-10-17-x1-spend-ledger.md`.

## Limits to publish

The key is written and checked by LLMs, anchored on 128 human-adjudicated fields; the judge is an LLM, validated
against the API on 30 cases; one run; part of the key is written by `gpt-oss`, a relative of `gpt-4.1`, so results
are split by writer; no escalation path yet; local corpus until the X0 cutover.

## Left to the builder

- File layout for the new key and stage outputs, and whether the existing `tests/eval/test_golden.py` runner is
  extended or a new runner added (it already appends per-case JSONL and resumes).
- Prompts and instruction files for the writers, checker, tiebreak and judge, within the rules above.
- How the judge splits an answer into statements for ALCE scoring.
- The margin formula (Wilson or Clopper-Pearson; X1 used Clopper-Pearson).

## Calls made in writing this up (not discussed)

- The existing 37 cases stay in the new set.
- A case still disputed after the tiebreak is dropped and counted, not settled further.
- The confidence score is the mean logprob over the answer call's tokens.
- The checker also confirms that the gold passages contain the answer (raised during the session as an addition
  to the approved part 1).
