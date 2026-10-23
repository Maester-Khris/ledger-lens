"""Split one run_chat.sh result into its load steps: turns/s, turn p50/p95, failures, and the box during the hold.
X3 appends busy replies (share of turn requests, p95 of the refusal) and timeouts (failed turns of 55 s or more).
Run from backend/:  $PYDEV/bin/python scripts/load/per_step.py reports/load/<date>-<label> [STEPS] [hold seconds]"""
import csv
import statistics
import sys
from collections import defaultdict

RAMP_SECONDS = 10


def p95(values: list[float]) -> float:
    return sorted(values)[max(0, int(0.95 * len(values)) - 1)]


def main() -> None:
    base = sys.argv[1]
    steps = [int(s) for s in (sys.argv[2] if len(sys.argv) > 2 else "5,10,20,40,80,160").split(",")]
    hold = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    rows = list(csv.DictReader(open(f"{base}.k6.csv")))
    start = min(float(r["timestamp"]) for r in rows)
    per = defaultdict(lambda: {"durations": [], "failed": 0, "served": 0, "busy": [], "timeouts": 0})
    for r in rows:
        offset = float(r["timestamp"]) - start
        step = int(offset // (RAMP_SECONDS + hold))
        in_hold = offset % (RAMP_SECONDS + hold) >= RAMP_SECONDS
        if step >= len(steps) or not in_hold:
            continue
        if r["metric_name"] == "chat_turn_duration":
            per[step]["durations"].append(float(r["metric_value"]) / 1000)
        elif r["metric_name"] == "chat_turn_failed" and float(r["metric_value"]) == 1:
            per[step]["failed"] += 1
        elif r["metric_name"] == "chat_turns_served":
            per[step]["served"] += 1
        elif r["metric_name"] == "chat_busy_duration":
            per[step]["busy"].append(float(r["metric_value"]))
        elif r["metric_name"] == "chat_turn_timeout" and float(r["metric_value"]) == 1:
            per[step]["timeouts"] += 1

    box = list(csv.DictReader(open(f"{base}.box.tsv"), delimiter="\t"))
    print("| Conversations | Turns/s | Turn p50 | Turn p95 | Failed | API CPU % (median) | DB connections (max) | Mock in flight (max) "
          "| Busy % | Busy p95 | Timeouts |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for step, level in enumerate(steps):
        data = per.get(step)
        if not data or not data["durations"]:
            continue
        lo, hi = step * (RAMP_SECONDS + hold) + RAMP_SECONDS, (step + 1) * (RAMP_SECONDS + hold)
        # One sample every 5 s from the start of the run. The window stops before the sample at `hi`: that one is
        # already the ramp to the next level, and as a max it once stood in for the whole hold (corrected 2026-10-15).
        window = box[lo // 5 + 1: hi // 5]
        busy = data["busy"]
        requests = len(busy) + data["served"] + data["failed"]
        top = lambda key: max((float(b[key]) for b in window if b[key]), default=float("nan"))
        middle = lambda key: statistics.median([float(b[key]) for b in window if b[key]] or [float("nan")])
        print(f"| {level} | {data['served'] / hold:.2f} | {statistics.median(data['durations']):.2f} s "
              f"| {p95(data['durations']):.2f} s | {data['failed']} | {middle('api_cpu_pct'):.0f} "
              f"| {top('db_connections'):.0f} | {top('mock_in_flight'):.0f} "
              f"| {100 * len(busy) / requests:.1f} | {f'{p95(busy):.0f} ms' if busy else 'n/a'} | {data['timeouts']} |")


if __name__ == "__main__":
    main()
