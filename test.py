#!/usr/bin/env python3
"""
spark_export_test.py

Usage:
  python spark_export_test.py "https://spark.lucko.me/abcd1234?raw=1"
  python spark_export_test.py "https://spark.lucko.me/abcd1234"          # will auto-add ?raw=1

Outputs:
  - parsed_spark.json (normalized export)
  - spark_raw.json    (downloaded raw json)
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


def ensure_raw_url(url: str) -> str:
    """Ensure the URL has raw=1 query param."""
    parts = urlparse(url)
    qs = parse_qs(parts.query, keep_blank_values=True)
    qs["raw"] = ["1"]
    new_query = urlencode(qs, doseq=True)
    return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))


def fetch_json(url: str, timeout: int = 20) -> dict:
    req = Request(
        url,
        headers={
            "User-Agent": "spark-export-test/1.0 (+python urllib)",
            "Accept": "application/json,text/plain,*/*",
        },
        method="GET",
    )
    with urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "")
        data = resp.read()

    # Spark raw endpoint usually returns JSON, but may be text/json.
    try:
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to decode JSON (Content-Type={content_type}): {e}") from e


def parse_spark_sampler(raw: dict) -> dict:
    meta = raw.get("metadata", {})
    platform = meta.get("platformStatistics", {})
    sources = meta.get("sources", {})

    # ----- Run info -----
    start = meta.get("startTime", 0)
    end = meta.get("endTime", 0)
    duration = (end - start) / 1000 if start and end else 0.0
    ticks = meta.get("numberOfTicks", 0)
    avg_tps = round(ticks / duration, 2) if duration > 0 else 0.0

    # ----- TPS / MSPT -----
    tps = platform.get("tps", {})
    mspt = platform.get("mspt", {})

    # ----- Entities -----
    world = platform.get("world", {})
    entity_counts = world.get("entityCounts", {}) or {}
    top_entities = dict(sorted(entity_counts.items(), key=lambda x: x[1], reverse=True)[:10])

    # ----- GC -----
    gc = platform.get("gc", {}) or {}

    # ----- Memory -----
    heap = (platform.get("memory", {}) or {}).get("heap", {}) or {}

    # ----- Mods (non built-in sources) -----
    mods = {
        mod_id: info.get("version")
        for mod_id, info in (sources or {}).items()
        if isinstance(info, dict) and not info.get("builtIn", False)
    }

    # ----- Server properties (stringified JSON sometimes) -----
    server_cfg_raw = (meta.get("serverConfigurations", {}) or {}).get("server.properties")
    server_cfg = {}
    if server_cfg_raw:
        try:
            server_cfg = json.loads(server_cfg_raw)
        except Exception:
            server_cfg = {}

    return {
        "run": {
            "duration_seconds": round(duration, 2),
            "interval_ms": meta.get("interval"),
            "ticks": ticks,
            "approx_avg_tps": avg_tps,
        },
        "tps": {
            "last_1m": tps.get("last1m"),
            "last_5m": tps.get("last5m"),
            "last_15m": tps.get("last15m"),
        },
        "mspt": {
            "last_1m": mspt.get("last1m"),
            "last_5m": mspt.get("last5m"),
        },
        "players": platform.get("playerCount"),
        "entities": {
            "total": world.get("totalEntities"),
            "top": top_entities,
        },
        "gc": {
            "young": gc.get("young"),
            "old": gc.get("old"),
        },
        "memory": {
            "heap_used_mb": round((heap.get("used", 0) / 1024 / 1024), 1),
            "heap_committed_mb": round((heap.get("committed", 0) / 1024 / 1024), 1),
        },
        "mods": mods,
        "server": {
            "view_distance": server_cfg.get("view-distance"),
            "simulation_distance": server_cfg.get("simulation-distance"),
            "sync_chunk_writes": server_cfg.get("sync-chunk-writes"),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch a Spark ?raw=1 JSON and output a normalized export JSON.")
    ap.add_argument("url", help="Spark report URL (spark.lucko.me/...) optionally without ?raw=1")
    ap.add_argument("-o", "--out", default="parsed_spark.json", help="Output file for parsed export JSON")
    ap.add_argument("--raw-out", default="spark_raw.json", help="Output file to save the downloaded raw JSON")
    ap.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds")
    args = ap.parse_args()

    url = args.url.strip()
    if not urlparse(url).scheme:
        print("Error: URL must include scheme, e.g. https://...", file=sys.stderr)
        return 2

    raw_url = ensure_raw_url(url)
    print(f"Fetching: {raw_url}")

    try:
        raw = fetch_json(raw_url, timeout=args.timeout)
    except HTTPError as e:
        print(f"HTTP error: {e.code} {e.reason}", file=sys.stderr)
        return 3
    except URLError as e:
        print(f"Network error: {e}", file=sys.stderr)
        return 4
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 5

    # Save raw for debugging
    with open(args.raw_out, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)
    print(f"Wrote raw JSON: {args.raw_out}")

    parsed = parse_spark_sampler(raw)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2)
    print(f"Wrote parsed export: {args.out}")

    # Quick console summary
    print("\nSummary:")
    print(f"  approx_avg_tps: {parsed['run']['approx_avg_tps']}")
    print(f"  players:        {parsed.get('players')}")
    print(f"  entities_total: {parsed['entities'].get('total')}")
    print(f"  heap_used_mb:   {parsed['memory'].get('heap_used_mb')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
