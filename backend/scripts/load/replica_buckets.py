"""X3: one replica_loss.sh result in 15 s buckets, then before / during / after the kill.
Run from backend/:  $PYDEV/bin/python scripts/load/replica_buckets.py reports/load/<date>-<label> [hold seconds]
                    $PYDEV/bin/python scripts/load/replica_buckets.py --selftest

A request is served (answer, refused, clarify), busy (503 /problems/busy), or failed, and failures carry the kind chat.js
gave them (cut, timeout, guest, http_<status>, error_event). Times are when k6 recorded the request, i.e. when it ended.
A cut stream behind nginx has no response headers, so it cannot be tied to a replica; without the kill there are none.
Hung: a timeout, or a cut that ended more than 1 s after the kill (it waited instead of failing at once). Recovery: from `docker start` to the restarted replica's first served turn, and to the last failure."""
import csv
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

BUCKET_SECONDS = 15
RAMP_SECONDS = 10
SETTLE_SECONDS = 30  # skipped after the ramp and after the restart before a window counts as steady


@dataclass
class Request:
    at: float
    outcome: str  # served, busy, failed
    kind: str = ""
    upstream: str = ""
    duration_ms: float = 0.0


@dataclass
class Window:
    served: int = 0
    busy: int = 0
    failures: Counter = field(default_factory=Counter)
    durations: list[float] = field(default_factory=list)
    by_upstream: Counter = field(default_factory=Counter)

    def add(self, request: Request) -> None:
        if request.outcome == "served":
            self.served += 1
            self.durations.append(request.duration_ms / 1000)
            self.by_upstream[request.upstream] += 1
        elif request.outcome == "busy":
            self.busy += 1
        else:
            self.failures[request.kind] += 1

    @property
    def total(self) -> int:
        return self.served + self.busy + sum(self.failures.values())


def p95(values: list[float]) -> float:
    return sorted(values)[max(0, int(0.95 * len(values)) - 1)] if values else float("nan")


def _tags(raw: str) -> dict[str, str]:
    return dict(part.split("=", 1) for part in raw.split("&") if "=" in part)


def _last_address(upstream: str) -> str:
    """X-Upstream lists every replica nginx tried ("a:8000, b:8000"); the last one answered."""
    return upstream.split(",")[-1].strip().split(":")[0] if upstream else ""


def read_requests(rows: list[dict]) -> list[Request]:
    requests = []
    for r in rows:
        name, value, tags = r["metric_name"], float(r["metric_value"]), _tags(r.get("extra_tags", ""))
        at = float(r["timestamp"]) / 1000  # replica_loss.sh writes milliseconds (K6_CSV_TIME_FORMAT=unix_milli)
        if name == "chat_turn_duration":
            requests.append(Request(at, "served", upstream=_last_address(tags.get("upstream", "")), duration_ms=value))
        elif name == "chat_busy_duration":
            requests.append(Request(at, "busy", duration_ms=value))
        elif name == "chat_turn_failed" and value == 1:
            requests.append(Request(at, "failed", kind=tags.get("kind", "unknown"),
                                    upstream=_last_address(tags.get("upstream", ""))))
    return sorted(requests, key=lambda q: q.at)


def hung(requests: list[Request], kill_at: float) -> list[Request]:
    return [q for q in requests if q.outcome == "failed" and (
        q.kind == "timeout" or (q.kind == "cut" and q.at > kill_at + 1))]


def summarise(requests: list[Request], start: float, kill_at: float, restart_at: float, end: float,
              names: dict[str, str]) -> list[str]:
    lines = ["| From (s) | Turns/s | p95 | Busy % | Failed | Failure kinds | Served per replica |",
             "|---|---|---|---|---|---|---|"]
    buckets: dict[int, Window] = defaultdict(Window)
    for q in requests:
        if q.at < end:  # ramp-down after the hold is not part of the run
            buckets[int((q.at - start) // BUCKET_SECONDS)].add(q)
    for index in sorted(buckets):
        w = buckets[index]
        kinds = ", ".join(f"{k} {n}" for k, n in sorted(w.failures.items())) or "-"
        split = " / ".join(f"{names.get(a, a or '?')} {n}" for a, n in sorted(w.by_upstream.items(), key=lambda x: names.get(x[0], x[0])))
        lines.append(f"| {index * BUCKET_SECONDS} | {w.served / BUCKET_SECONDS:.2f} | {p95(w.durations):.2f} s "
                     f"| {100 * w.busy / max(1, w.total):.1f} | {sum(w.failures.values())} | {kinds} | {split or '-'} |")

    hold_start = start + RAMP_SECONDS
    phases = {"before": (hold_start + SETTLE_SECONDS, kill_at), "during": (kill_at, restart_at),
              "after": (restart_at + SETTLE_SECONDS, end)}
    lines += ["", "| Phase | Window (s after k6 start) | Turns/s | p50 | p95 | Busy % | Failed | Failure kinds |",
              "|---|---|---|---|---|---|---|---|"]
    for phase, (lo, hi) in phases.items():
        w = Window()
        for q in requests:
            if lo <= q.at < hi:
                w.add(q)
        kinds = ", ".join(f"{k} {n}" for k, n in sorted(w.failures.items())) or "-"
        median = statistics.median(w.durations) if w.durations else float("nan")
        lines.append(f"| {phase} | {lo - start:.0f}-{hi - start:.0f} | {w.served / max(1e-9, hi - lo):.2f} | {median:.2f} s "
                     f"| {p95(w.durations):.2f} s | {100 * w.busy / max(1, w.total):.1f} | {sum(w.failures.values())} | {kinds} |")

    victim = next(a for a, n in names.items() if n == "victim")
    stuck = hung(requests, kill_at)
    cut = [q for q in requests if q.outcome == "failed" and q.kind == "cut" and q.at >= kill_at]
    first_back = next((q.at for q in requests if q.outcome == "served" and q.upstream == victim and q.at > restart_at), None)
    last_failure = max((q.at for q in requests if q.outcome == "failed" and q.at > restart_at), default=None)
    lines += ["",
              f"- Streams cut after the kill: {len(cut)}; the last ended {max((q.at for q in cut), default=kill_at) - kill_at:.2f} s after it.",
              f"- Hung (timeout, or cut more than 1 s after the kill): {len(stuck)}.",
              f"- Restarted replica's first served turn: "
              + (f"{first_back - restart_at:.1f} s after `docker start`." if first_back else "none (it never served again)."),
              f"- Last failure after `docker start`: "
              + (f"{last_failure - restart_at:.1f} s after it." if last_failure else "none.")]
    return lines


def main(base: str, hold: int) -> None:
    events = {r["event"]: float(r["epoch"]) for r in csv.DictReader(open(f"{base}.events.tsv"), delimiter="\t")}
    replicas = list(csv.DictReader(open(f"{base}.replicas.tsv"), delimiter="\t"))
    names, survivors = {}, 0
    for r in replicas:
        if r["role"] == "survivor":
            survivors += 1
            names[r["address"]] = f"s{survivors}"
        else:  # victim, and victim_restarted (its address after `docker start`, if it changed)
            names[r["address"]] = "victim"
    start = events["k6_start"]
    requests = read_requests(list(csv.DictReader(open(f"{base}.k6.csv"))))
    print("\n".join(summarise(requests, start, events["kill"], events["start"], start + RAMP_SECONDS + hold, names)))


def selftest() -> None:
    victim, survivor = "10.0.0.2", "10.0.0.3"
    requests = [
        Request(100.0, "served", upstream=survivor, duration_ms=4000),
        Request(130.2, "failed", kind="cut", upstream=victim),   # cut at once: clean
        Request(132.0, "failed", kind="cut", upstream=victim),   # cut 2 s after the kill: hung
        Request(140.0, "failed", kind="timeout", upstream=survivor),  # any timeout: hung
        Request(141.0, "busy", duration_ms=2),
    ]
    assert [q.at for q in hung(requests, kill_at=130.0)] == [132.0, 140.0]
    assert _last_address("10.0.0.2:8000, 10.0.0.3:8000") == survivor
    assert _tags("kind=cut&upstream=10.0.0.2:8000") == {"kind": "cut", "upstream": "10.0.0.2:8000"}
    lines = summarise(requests + [Request(170.0, "served", upstream=victim, duration_ms=3000)],
                      start=95.0, kill_at=130.0, restart_at=160.0, end=180.0, names={victim: "victim", survivor: "s1"})
    assert lines[2].startswith("| 0 | ") and "s1 1" in lines[2]  # bucket 0 = 95..110 s
    assert any("first served turn: 10.0 s" in line for line in lines)
    assert any("Hung (timeout, or cut more than 1 s after the kill): 2." in line for line in lines)
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    else:
        main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 360)
