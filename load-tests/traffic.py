"""Traffic generator and load-test gate.

  python load-tests/traffic.py --base-url http://localhost:8080 --duration 300 --rps 10
  python load-tests/traffic.py --check --max-error-ratio 0.01 --max-p95-ms 500   (gate mode)
Canary analysis needs traffic: keep this running while a canary is in progress.
"""

import argparse
import json
import random
import statistics
import sys
import time
import urllib.error
import urllib.request

SKUS = ["GEAR-42", "BOLT-M8", "PUMP-7"]


def order(base: str) -> tuple[int, float]:
    body = {"customer_id": f"CUST-{random.randint(1000, 9999)}", "sku": random.choice(SKUS),
            "quantity": random.randint(1, 3), "card_token": "tok_visa_ok"}  # fmt: skip
    request = urllib.request.Request(f"{base}/orders", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})  # fmt: skip
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - lab URL
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (urllib.error.URLError, TimeoutError):
        status = 0
    return status, (time.perf_counter() - started) * 1000


def main() -> int:
    parser = argparse.ArgumentParser(description="SafeOps traffic generator / load gate")
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--rps", type=float, default=5)
    parser.add_argument("--check", action="store_true", help="exit 1 if thresholds are violated")
    parser.add_argument("--max-error-ratio", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=500)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    results: list[tuple[int, float]] = []
    end = time.monotonic() + args.duration
    while time.monotonic() < end:
        results.append(order(base))
        time.sleep(1 / args.rps)
    errors = sum(1 for status, _ in results if status == 0 or status >= 500)
    latencies = sorted(ms for _, ms in results)
    p95 = latencies[int(len(latencies) * 0.95) - 1] if latencies else 0
    summary = {
        "requests": len(results),
        "error_ratio": round(errors / max(1, len(results)), 4),
        "p95_ms": round(p95, 1),
        "median_ms": round(statistics.median(latencies or [0]), 1),
    }
    print(json.dumps(summary))
    if args.check:
        ok = summary["error_ratio"] <= args.max_error_ratio and summary["p95_ms"] <= args.max_p95_ms
        print("LOAD GATE PASSED" if ok else "LOAD GATE FAILED")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
