"""N5 proof: one guest sends 30 chat requests through nginx to 2 API replicas; the per-guest limit is 10.
Usage (from backend/): $PYDEV/bin/python scripts/load/limiter_check.py <memory|redis> [base url]
Exit 0 only if the result matches the mode: redis = exactly 10 admitted (the replicas share one window); memory = more
than 10 (each replica counts on its own). Writes reports/load/<date>-limiter-<mode>.json."""
import json
import sys
import uuid
from datetime import date
from pathlib import Path

import httpx

REQUESTS, LIMIT = 30, 10


def main() -> int:
    mode = sys.argv[1]
    base = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8088"
    with httpx.Client(base_url=base, timeout=60) as client:
        guest = client.post("/guests").json()["id"]
        statuses, upstreams = [], []
        for _ in range(REQUESTS):
            response = client.post("/chat", headers={"X-Guest-Id": guest},
                                   json={"session_id": f"limiter-{uuid.uuid4().hex[:8]}", "message": "What is the fee?"})
            statuses.append(response.status_code)
            upstreams.append(response.headers.get("x-upstream"))
    admitted, refused = statuses.count(200), statuses.count(429)
    replicas = sorted({u for u in upstreams if u})
    passed = len(replicas) >= 2 and (admitted == LIMIT if mode == "redis" else admitted > LIMIT)
    result = {"mode": mode, "requests": REQUESTS, "limit_per_guest": LIMIT, "admitted": admitted, "refused": refused,
              "other": REQUESTS - admitted - refused, "replicas_seen": replicas,
              "admitted_by_replica": {r: sum(1 for s, u in zip(statuses, upstreams) if u == r and s == 200) for r in replicas},
              "passed": passed}
    out = Path(__file__).resolve().parents[2] / "reports" / "load" / f"{date.today()}-limiter-{mode}.json"
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
