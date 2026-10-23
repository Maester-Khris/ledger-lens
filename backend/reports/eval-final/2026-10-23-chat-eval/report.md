# Chat Evaluation Report

## Answer correctness
- 79.4% (95% CI 72.8–84.8%, n=175)

## Citation recall
- 94.8% (95% CI 91.6–96.8%, n=290)

## Citation precision
- 93.3% (95% CI 89.0–95.9%, n=208)

## Refusal accuracy
- **Overall:** 80.3% (95% CI 70.0–87.7%, n=76)
- **out_of_corpus:** 88.0% (95% CI 70.0–95.8%, n=25)
- **false_premise:** 55.0% (95% CI 34.2–74.2%, n=20)
- **underspecified:** 75.0% (95% CI 46.8–91.1%, n=12)
- **nonsense:** 100.0% (95% CI 67.6–100.0%, n=8)
- **off_topic:** 100.0% (95% CI 74.1–100.0%, n=11)

## Over-refusal
- 17.4% (95% CI 12.6–23.4%, n=190)

## Context recall
- 83.4% (95% CI 77.2–88.2%, n=175)

## Failure split
- **Retrieval failures (gold passage not retrieved):** 26
- **Generation failures (gold passage retrieved, answer wrong):** 10

## Results by writer
- **openai/gpt-oss-120b:** 83.3% (95% CI 73.5–90.0%, n=78)
- **qwen/qwen3.8-27b:** 76.3% (95% CI 66.9–83.6%, n=97)

## Anchor error rate
- 40/111 (36.0%, one-sided 95% Clopper-Pearson upper bound 44.2%)

## Judge agreement
- 28/29 (96.6% agreement, Cohen's kappa 0.651)

## Confidence sweep

| Threshold | Accuracy above | Accuracy below | Share below |
|---|---|---|---|
| -0.0251 | 93.5% (95% CI 88.5–96.4%, n=154) | 88.9% (95% CI 67.2–96.9%, n=18) | 10.5% |
| -0.0171 | 93.4% (95% CI 88.0–96.5%, n=137) | 91.4% (95% CI 77.6–97.0%, n=35) | 20.3% |
| -0.0113 | 93.4% (95% CI 87.5–96.6%, n=121) | 92.2% (95% CI 81.5–96.9%, n=51) | 29.7% |
| -0.0083 | 94.2% (95% CI 88.0–97.3%, n=104) | 91.2% (95% CI 82.1–95.9%, n=68) | 39.5% |
| -0.0064 | 95.3% (95% CI 88.5–98.2%, n=85) | 90.8% (95% CI 82.9–95.3%, n=87) | 50.6% |
| -0.005 | 94.1% (95% CI 85.8–97.7%, n=68) | 92.3% (95% CI 85.6–96.1%, n=104) | 60.5% |
| -0.0037 | 100.0% (95% CI 93.0–100.0%, n=51) | 90.1% (95% CI 83.5–94.2%, n=121) | 70.3% |
| -0.0016 | 100.0% (95% CI 90.1–100.0%, n=35) | 91.2% (95% CI 85.3–94.9%, n=137) | 79.7% |
| -0.0008 | 100.0% (95% CI 81.6–100.0%, n=17) | 92.3% (95% CI 87.0–95.5%, n=155) | 90.1% |

## Limits
- LLM-written and LLM-checked evaluation key, anchored on 128 human-adjudicated contract fields.
- LLM judge (`claude-sonnet-5-5`), validated between Anthropic API and headless CLI.
- Single final run on the deployed configuration (`gpt-4.1-2025-04-14`).
- Part of the key is written by `gpt-oss`, an open-weights relative of `gpt-4.1`, so correctness is split by writer.
- No runtime escalation path yet; confidence and context recall are measured offline.
- Golden `@scoped` variants are not run in this corpus-wide pass.
