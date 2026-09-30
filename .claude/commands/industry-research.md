# /industry-research

Deep, source-verified web research on a domain, industry or topic, for one or
more specific concerns. The goal is to find the **industry-validated way** to
do something: what credible practitioners, standards bodies and
production-proven companies actually agree on, where they disagree, and why.
This is not a quick search summary.

Results are saved to `artifacts/research/`.

## Invocation
```
/industry-research "<topic>" "<concern 1>" ["<concern 2>" ...] [--company <name>]

# Examples:
/industry-research "ledger engineering" "idempotent posting APIs" "immutable ledgers"
/industry-research "wealth-management revenue ops" "fee billing calculation" --company PureFacts
```
- `<topic>`: the domain the concerns belong to (used to pick sources and vocabulary).
- `<concern>`: each one is researched separately and gets its own section.
- `--company`: also look for public hints about how that specific company does each concern.

---

## Step 1 — Frame each concern before searching

For every concern, write down (in the research file, not only in your head):
- The precise question, e.g. "How should a ledger reject UPDATE/DELETE: at the
  database, the application, or both?"
- The vocabulary practitioners use for it (e.g. "append-only", "immutable
  journal", "compensating entry", "reversal"), including synonyms used in
  finance and accounting as well as in engineering.
- What would count as an answer: a principle (the why) **and** an
  implementation protocol (the how).

## Step 2 — Source tiers (what counts as credible)

Rank every source. Only Tier 1–3 sources may support a "consensus" claim.

| Tier | Source type | Examples |
|---|---|---|
| 1 | Standards, regulators, auditors | GAAP/IFRS, AICPA/SOC 1, SOX ITGC guidance, SEC/FINRA rules, PCI DSS, ISO 20022 |
| 2 | Engineering writing from companies running this in production, by named authors | Stripe, Square/Block, Modern Treasury, Uber, Airbnb, Shopify, Monzo, Adyen, TigerBeetle, Formance engineering blogs |
| 3 | Named practitioners with verifiable credentials | Conference talks (QCon, Strange Loop, Money20/20), podcasts with a named guest, books (e.g. Kleppmann's *Designing Data-Intensive Applications*), posts by people whose role and employer can be checked |
| 4 | Vendor marketing, anonymous posts, forum answers | Use only as leads to Tier 1–3 sources, never as evidence |

For every Tier 2–3 source, record **who** (name), **credential** (role and
organisation at the time), **date**, and **URL**. If you can't check the
author's credentials, drop the source to Tier 4.

## Step 3 — Search depth (non-negotiable)

- Use the web search and fetch tools available in the session (WebSearch/WebFetch, Exa, Firecrawl).
  **Read the full text** of every source you cite. Search-result snippets are not evidence.
- Per concern: at least **3 independent Tier 1–3 sources**, with at least one
  Tier 1 or Tier 2 source when one exists.
- Every consensus claim needs **2 or more independent sources** that agree.
  One source means it's an opinion; label it that way.
- Follow references **one step further**: if a credible source cites a
  standard, paper or post, fetch that too.
- **Actively look for disagreement** ("X considered harmful", "why we moved
  away from X", post-mortems). Record where practitioners disagree and why.
- Run independent searches in parallel. Do not stop at the first page of results.

## Step 4 — Company hints (only with `--company`)

For each concern, look for public evidence of how the company does it:
- Their own product pages, documentation, press releases, case studies, job
  descriptions (tech stack, responsibilities), engineering blog, and
  conference or podcast appearances by their staff.
- Regulatory or compliance claims (SOC 1/2 reports mentioned, audit language).

Label each hint by strength:
- **Stated**: the company says it explicitly.
- **Implied**: follows directly from something they say.
- **Speculative**: an educated guess. Never present one as fact.

"No public evidence found" is a valid, useful result. Say it plainly.

## Step 5 — Write the research file

Path: `artifacts/research/<YYYY-MM-DD>-<topic-slug>.md`. If it exists, add a new
dated run section; don't overwrite.

Structure:
```markdown
# <Topic>: industry research
Run: <date> · Concerns: <n> · Company: <name or none>

## Summary
<one short paragraph per concern: the consensus in plain words and how confident you are>

## Concern N — <name>
### Question
### Principle (the approach and why)
### Implementation protocol (the how: concrete, ordered steps)
### Variants and disagreements
### Confidence
High / Medium / Low, with one line saying why (number and tier of sources that agree).
### <Company> hints
- [Stated|Implied|Speculative] <hint> (source)
### Sources
| # | Tier | Who (credential) | Title | Date | URL |

## Open questions
<things the research could not settle>
```

## Step 6 — Report back

In the terminal, give only:
- the file path
- per concern: one line of consensus plus its confidence
- the most important disagreement or open question, if any.

Do not paste the full file into the chat.

---

## Hard rules

| Rule | Why |
|---|---|
| No citation without reading the full text | Snippets misquote |
| No consensus claim from a single source or from Tier 4 | "One blog said so" is not a standard |
| Record credentials for every Tier 2–3 source | Credibility has to be checkable later |
| Company hints labelled Stated / Implied / Speculative | Keeps guesses from turning into facts in an interview |
| Never modify code or other files in this command | Research only; implementation decisions happen afterwards, together |
