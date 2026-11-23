"""HTTP load test for POST /api/v1/search: latency at a fixed number of searches in flight.

Usage (from a container on the Compose network, e.g. `docker compose run --rm ingest`):
    python -m scripts.load_search --base http://api:8000 --concurrency 4 10 --requests 60

Registers a throwaway user, warms the API (every uvicorn worker loads its models on its
first search), then for each concurrency level keeps exactly C requests in flight until
`--requests` have completed. Queries x dealbreaker sets come from bench_search, so no
two consecutive requests are identical; run the API with SEARCH_CACHE_SECONDS=0 and a
high RATE_LIMIT_SEARCH_PER_MINUTE, or the cache and the limiter decide the numbers.
Prints one JSON object: p50/p95/max per level, error counts, and the settings the API
reported (rerank profile, reranked count).
"""

import argparse
import asyncio
import itertools
import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx

from scripts.bench_search import PROFILE, QUERIES, RULE_SETS


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return round(ordered[max(0, min(len(ordered) - 1, round(q * (len(ordered) - 1))))], 1)


def bodies() -> Iterator[dict[str, Any]]:
    items = [
        {
            "query": query,
            "profile": PROFILE.model_dump(),
            "rules": [rule.model_dump() for rule in rules],
            "limit": 10,
        }
        for rules in RULE_SETS.values()
        for query in QUERIES
    ]
    return itertools.cycle(items)


async def level(
    http: httpx.AsyncClient, headers: dict[str, str], concurrency: int, total: int
) -> dict[str, Any]:
    source = bodies()
    latencies: list[float] = []
    statuses: dict[int, int] = {}
    reranked: set[tuple[str, int]] = set()
    remaining = total
    lock = asyncio.Lock()

    async def client() -> None:
        nonlocal remaining
        while True:
            async with lock:
                if remaining == 0:
                    return
                remaining -= 1
                body = next(source)
            started = time.perf_counter()
            response = await http.post("/api/v1/search", json=body, headers=headers)
            latencies.append((time.perf_counter() - started) * 1000)
            statuses[response.status_code] = statuses.get(response.status_code, 0) + 1
            if response.status_code == 200:
                data = response.json()
                reranked.add((data["rerank_profile"], data["reranked"]))

    started = time.perf_counter()
    await asyncio.gather(*(client() for _ in range(concurrency)))
    seconds = time.perf_counter() - started
    return {
        "requests": total,
        "p50_ms": pct(latencies, 0.5),
        "p95_ms": pct(latencies, 0.95),
        "max_ms": round(max(latencies), 1),
        "throughput_per_s": round(total / seconds, 2),
        "statuses": statuses,
        "rerank": sorted(reranked),
    }


async def main(base: str, levels: list[int], total: int, warmup: int) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=120) as http:
        email = f"load-{uuid.uuid4().hex[:10]}@example.com"
        response = await http.post(
            "/api/v1/auth/register", json={"email": email, "password": uuid.uuid4().hex}
        )
        response.raise_for_status()
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        # Warm-up in parallel, so every worker process gets requests and loads its models.
        await level(http, headers, min(warmup, 8), warmup)
        results = {str(c): await level(http, headers, c, total) for c in levels}
    print(json.dumps(results))


def cli() -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.load_search")
    parser.add_argument("--base", default="http://api:8000")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[4, 10])
    parser.add_argument("--requests", type=int, default=60)
    parser.add_argument("--warmup", type=int, default=16)
    args = parser.parse_args()
    asyncio.run(main(args.base, args.concurrency, args.requests, args.warmup))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
