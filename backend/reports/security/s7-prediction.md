S7 prediction (written 2026-10-17 before the eval):
- basic (no strategy): >= 90% pass.
- jailbreak and crescendo: 75-90% pass.
- Failures concentrate in pii:* / harmful:privacy (grader counts public EDGAR party names or tokens as PII) and in
  specialized advice; no case results in a ledger change (tools can only propose; no approve/post/delete tool exists).
- Real prompt-extraction leak (verbatim tool rules): at most 1-2 cases under jailbreak/crescendo.
