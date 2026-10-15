"""Summarise a py-spy collapsed-stack profile (run_chat.sh with PROFILE=1): where the API's CPU time goes.
Run from backend/:  $PYDEV/bin/python scripts/load/profile_top.py reports/load/<date>-<label>.profile.txt [top N]
Samples are the GIL-holding thread only (py-spy --gil), 100 Hz, every worker. Prints three views:
  1. self time by library (the leaf frame's package): what the CPU is literally executing;
  2. self time by function (leaf frame);
  3. inclusive time of our own functions (backend/app/...): which step of a turn costs the most, callees included."""
import re
import sys
from collections import Counter

FRAME = re.compile(r"^(?P<func>.+?) \((?P<path>.+?):\d+\)$")


def library(path: str) -> str:
    """py-spy prints paths relative to the import root: the first component is the package (or stdlib module)."""
    if path.startswith("app/"):
        return "app (our code)"
    return path.split("/", 1)[0].removesuffix(".py") or "?"


def parse(line: str) -> tuple[list[tuple[str, str]], int]:
    stack, _, count = line.rstrip("\n").rpartition(" ")
    frames = []
    for raw in stack.split(";"):
        match = FRAME.match(raw)
        frames.append((match["func"], match["path"]) if match else (raw, ""))
    return frames, int(count)


def main() -> None:
    path, top = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 15
    by_library, by_function, ours = Counter(), Counter(), Counter()
    total = 0
    for line in open(path):
        if not line.strip():
            continue
        frames, count = parse(line)
        total += count
        func, file = frames[-1]
        by_library[library(file)] += count
        by_function[f"{func} ({file.rsplit('/', 2)[-1] if file else '?'})"] += count
        for name in {f"{f} ({p})" for f, p in frames if p.startswith("app/")}:
            ours[name] += count  # once per stack: inclusive time
    print(f"samples: {total} (about {total / 100:.0f} CPU-seconds)\n")
    for title, counter in (("Self time by library", by_library), ("Self time by function", by_function),
                           ("Inclusive time, our code", ours)):
        print(f"## {title}\n\n| Share | Samples | Where |\n|---|---|---|")
        for name, count in counter.most_common(top):
            print(f"| {100 * count / total:.1f}% | {count} | {name} |")
        print()


if __name__ == "__main__":
    main()
