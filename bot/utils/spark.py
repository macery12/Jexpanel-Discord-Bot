"""Spark profiler report analyzer for Minecraft servers.

Analyzes Spark profiler reports to detect performance issues.
Based on the parsing approach from test.py.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import aiohttp


# Severity thresholds for performance metrics
SEVERITY_THRESHOLDS = {
    "tps": {
        "CRITICAL": 15.0,  # Below 15 TPS
        "HIGH": 18.0,      # Below 18 TPS
        "MEDIUM": 19.5,    # Below 19.5 TPS
    },
    "mspt": {
        "CRITICAL": 100.0,  # Above 100ms per tick
        "HIGH": 65.0,       # Above 65ms per tick  
        "MEDIUM": 55.0,     # Above 55ms per tick
    },
    "entities": {
        "CRITICAL": 1500,
        "HIGH": 1000,
        "MEDIUM": 750,
    },
    "heap_usage": {
        "CRITICAL": 90.0,  # % of committed
        "HIGH": 80.0,
        "MEDIUM": 70.0,
    },
}


def _ensure_raw_url(url: str) -> str:
    """Ensure the Spark URL has ?raw=1 parameter."""
    parts = urlparse(url)
    qs = parse_qs(parts.query, keep_blank_values=True)
    qs["raw"] = ["1"]
    new_query = urlencode(qs, doseq=True)
    return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))


def _validate_spark_url(url: str) -> bool:
    """Validate that this is a Spark profiler URL."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False
    
    # Check if it's a spark.lucko.me URL or similar
    if "spark" not in parsed.netloc.lower():
        return False
    
    # Check if there's a report ID in the path
    path_parts = [p for p in parsed.path.split("/") if p]
    if len(path_parts) == 0 or not path_parts[-1]:
        return False
    
    return True


def _parse_spark_json(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse raw Spark JSON into a normalized structure.
    
    Based on the approach from test.py.
    """
    meta = raw.get("metadata", {})
    platform = meta.get("platformStatistics", {})
    sources = meta.get("sources", {})
    
    # Platform info
    platform_info = meta.get("platform", {})
    
    # Run info
    start = meta.get("startTime", 0)
    end = meta.get("endTime", 0)
    duration = (end - start) / 1000 if start and end else 0.0
    ticks = meta.get("numberOfTicks", 0)
    avg_tps = round(ticks / duration, 2) if duration > 0 else 0.0
    
    # TPS / MSPT
    tps = platform.get("tps", {})
    mspt = platform.get("mspt", {})
    
    # Entities
    world = platform.get("world", {})
    entity_counts = world.get("entityCounts", {}) or {}
    top_entities = dict(sorted(entity_counts.items(), key=lambda x: x[1], reverse=True)[:10])
    
    # GC
    gc = platform.get("gc", {}) or {}
    
    # Memory
    heap = (platform.get("memory", {}) or {}).get("heap", {}) or {}
    
    # Mods (non built-in sources)
    mods = {
        mod_id: info.get("version")
        for mod_id, info in (sources or {}).items()
        if isinstance(info, dict) and not info.get("builtIn", False)
    }
    
    return {
        "platform": {
            "name": platform_info.get("name", "Unknown"),
            "version": platform_info.get("version", "Unknown"),
            "mc_version": platform_info.get("minecraftVersion", "Unknown"),
        },
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
        "gc": gc,
        "memory": {
            "heap_used_mb": round((heap.get("used", 0) / 1024 / 1024), 1),
            "heap_committed_mb": round((heap.get("committed", 0) / 1024 / 1024), 1),
        },
        "mods": mods,
    }


def _analyze_performance(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Analyze the parsed Spark data and detect issues."""
    alerts = []
    
    # TPS Analysis
    tps_1m = data["tps"].get("last_1m")
    if tps_1m is not None:
        severity = _get_tps_severity(tps_1m)
        if severity:
            alerts.append({
                "severity": severity,
                "title": f"Low TPS ({tps_1m:.1f})",
                "description": f"Server TPS is {tps_1m:.1f}/20.0 over the last minute",
                "recommendation": "Check MSPT and entity count. Consider reducing loaded chunks, entities, or mods.",
            })
    
    # MSPT Analysis
    mspt_1m = data["mspt"].get("last_1m")
    if mspt_1m and isinstance(mspt_1m, dict):
        mean_mspt = mspt_1m.get("mean")
        if mean_mspt is not None:
            severity = _get_mspt_severity(mean_mspt)
            if severity:
                max_mspt = mspt_1m.get("max", 0)
                p95_mspt = mspt_1m.get("percentile95", 0)
                alerts.append({
                    "severity": severity,
                    "title": f"High MSPT ({mean_mspt:.1f}ms)",
                    "description": (
                        f"Average tick time: {mean_mspt:.1f}ms (target: <50ms)\n"
                        f"95th percentile: {p95_mspt:.1f}ms\n"
                        f"Max: {max_mspt:.1f}ms"
                    ),
                    "recommendation": "Server is struggling to keep up. Reduce entity count, optimize mods, or upgrade hardware.",
                })
    
    # Entity Analysis
    total_entities = data["entities"].get("total")
    if total_entities is not None:
        severity = _get_entity_severity(total_entities)
        if severity:
            top_entities = data["entities"].get("top", {})
            top_list = "\n".join([f"  - {name}: {count}" for name, count in list(top_entities.items())[:5]])
            alerts.append({
                "severity": severity,
                "title": f"High Entity Count ({total_entities})",
                "description": f"Total entities: {total_entities}\nTop entities:\n{top_list}",
                "recommendation": "Reduce mob spawning, clear items, or limit chunk loaders.",
            })
    
    # Memory Analysis
    heap_used = data["memory"].get("heap_used_mb", 0)
    heap_committed = data["memory"].get("heap_committed_mb", 1)
    if heap_committed > 0:
        usage_pct = (heap_used / heap_committed) * 100
        severity = _get_heap_severity(usage_pct)
        if severity:
            alerts.append({
                "severity": severity,
                "title": f"High Memory Usage ({usage_pct:.1f}%)",
                "description": f"Heap: {heap_used:.1f}MB / {heap_committed:.1f}MB ({usage_pct:.1f}%)",
                "recommendation": "Increase allocated RAM or reduce memory usage (fewer entities, smaller view distance).",
            })
    
    # Mod Count Warning
    mod_count = len(data.get("mods", {}))
    if mod_count > 100:
        alerts.append({
            "severity": "MEDIUM",
            "title": f"Large Modpack ({mod_count} mods)",
            "description": f"{mod_count} mods detected",
            "recommendation": "Large modpacks can cause performance issues. Consider removing unused mods.",
        })
    
    return alerts


def _get_tps_severity(tps: float) -> str | None:
    """Get severity level for TPS (lower is worse)."""
    if tps <= SEVERITY_THRESHOLDS["tps"]["CRITICAL"]:
        return "CRITICAL"
    elif tps <= SEVERITY_THRESHOLDS["tps"]["HIGH"]:
        return "HIGH"
    elif tps <= SEVERITY_THRESHOLDS["tps"]["MEDIUM"]:
        return "MEDIUM"
    return None


def _get_mspt_severity(mspt: float) -> str | None:
    """Get severity level for MSPT (higher is worse)."""
    if mspt >= SEVERITY_THRESHOLDS["mspt"]["CRITICAL"]:
        return "CRITICAL"
    elif mspt >= SEVERITY_THRESHOLDS["mspt"]["HIGH"]:
        return "HIGH"
    elif mspt >= SEVERITY_THRESHOLDS["mspt"]["MEDIUM"]:
        return "MEDIUM"
    return None


def _get_entity_severity(count: int) -> str | None:
    """Get severity level for entity count (higher is worse)."""
    if count >= SEVERITY_THRESHOLDS["entities"]["CRITICAL"]:
        return "CRITICAL"
    elif count >= SEVERITY_THRESHOLDS["entities"]["HIGH"]:
        return "HIGH"
    elif count >= SEVERITY_THRESHOLDS["entities"]["MEDIUM"]:
        return "MEDIUM"
    return None


def _get_heap_severity(usage_pct: float) -> str | None:
    """Get severity level for heap usage percentage (higher is worse)."""
    if usage_pct >= SEVERITY_THRESHOLDS["heap_usage"]["CRITICAL"]:
        return "CRITICAL"
    elif usage_pct >= SEVERITY_THRESHOLDS["heap_usage"]["HIGH"]:
        return "HIGH"
    elif usage_pct >= SEVERITY_THRESHOLDS["heap_usage"]["MEDIUM"]:
        return "MEDIUM"
    return None


async def analyze_spark_report(url: str) -> dict[str, Any]:
    """Analyze a Spark profiler report from a URL.
    
    Args:
        url: The Spark report URL (will auto-add ?raw=1 if needed)
        
    Returns:
        Dictionary containing analysis results
        
    Raises:
        ValueError: If the URL is invalid or report type is unsupported
        aiohttp.ClientError: If there's a network error
    """
    # Validate URL
    if not _validate_spark_url(url):
        raise ValueError(f"Invalid Spark URL: {url}")
    
    # Ensure ?raw=1 parameter
    raw_url = _ensure_raw_url(url)
    
    # Fetch JSON
    async with aiohttp.ClientSession() as session:
        async with session.get(raw_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                raise ValueError(f"HTTP {resp.status}: {resp.reason}")
            
            raw_json = await resp.json()
    
    # Validate report type
    report_type = raw_json.get("type", "")
    if report_type != "sampler":
        raise ValueError(f"Invalid report type: expected 'sampler', got '{report_type}'")
    
    # Parse the JSON
    parsed_data = _parse_spark_json(raw_json)
    
    # Analyze for issues
    alerts = _analyze_performance(parsed_data)
    
    # Return structured result
    return {
        "summary": parsed_data,
        "alerts": alerts,
    }


def format_discord_report(result: dict[str, Any]) -> str:
    """Format the analysis result for Discord output.
    
    Args:
        result: The result from analyze_spark_report()
        
    Returns:
        Formatted string ready for Discord
    """
    summary = result.get("summary", {})
    alerts = result.get("alerts", [])
    
    # Header
    platform = summary.get("platform", {})
    run = summary.get("run", {})
    
    lines = [
        "📊 **Spark Profile Analysis**",
        f"**Platform:** {platform.get('name')} {platform.get('version')}",
        f"**MC Version:** {platform.get('mc_version')}",
        f"**Duration:** {run.get('duration_seconds', 0):.1f}s",
        "",
    ]
    
    # Performance Metrics
    tps = summary.get("tps", {})
    mspt = summary.get("mspt", {})
    
    lines.append("**Performance:**")
    tps_1m = tps.get("last_1m")
    if tps_1m is not None:
        tps_emoji = "🔴" if tps_1m < 15 else "🟠" if tps_1m < 18 else "🟢"
        lines.append(f"{tps_emoji} TPS (1m): {tps_1m:.1f}/20.0")
    
    if mspt.get("last_1m") and isinstance(mspt["last_1m"], dict):
        mspt_mean = mspt["last_1m"].get("mean")
        if mspt_mean is not None:
            mspt_emoji = "🔴" if mspt_mean > 100 else "🟠" if mspt_mean > 65 else "🟢"
            lines.append(f"{mspt_emoji} MSPT (1m avg): {mspt_mean:.1f}ms")
    
    # Entities
    entities = summary.get("entities", {})
    total_ent = entities.get("total")
    if total_ent is not None:
        ent_emoji = "🔴" if total_ent > 1500 else "🟠" if total_ent > 1000 else "🟢"
        lines.append(f"{ent_emoji} Entities: {total_ent}")
    
    # Memory
    memory = summary.get("memory", {})
    heap_used = memory.get("heap_used_mb", 0)
    heap_committed = memory.get("heap_committed_mb", 0)
    if heap_committed > 0:
        usage_pct = (heap_used / heap_committed) * 100
        mem_emoji = "🔴" if usage_pct > 90 else "🟠" if usage_pct > 80 else "🟢"
        lines.append(f"{mem_emoji} Memory: {heap_used:.0f}MB/{heap_committed:.0f}MB ({usage_pct:.0f}%)")
    
    # Players
    players = summary.get("players")
    if players is not None:
        lines.append(f"👥 Players: {players}")
    
    # Mods
    mods = summary.get("mods", {})
    if mods:
        lines.append(f"⚙️ Mods: {len(mods)}")
    
    lines.append("")
    
    # Alerts
    if alerts:
        lines.append("**⚠️ Issues Detected:**")
        
        # Sort by severity
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        sorted_alerts = sorted(alerts, key=lambda x: severity_order.get(x.get("severity", "LOW"), 99))
        
        for alert in sorted_alerts[:5]:  # Limit to top 5 alerts
            severity = alert.get("severity", "LOW")
            emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(severity, "⚪")
            title = alert.get("title", "Unknown issue")
            lines.append(f"{emoji} **{title}**")
            
            # Add recommendation if space allows
            rec = alert.get("recommendation", "")
            if rec and len("\n".join(lines)) + len(rec) < 1800:  # Leave room
                lines.append(f"  💡 {rec}")
            lines.append("")
    else:
        lines.append("✅ **No significant issues detected!**")
    
    message = "\n".join(lines)
    
    # Truncate if too long
    if len(message) > 2000:
        message = message[:1997] + "..."
    
    return message
