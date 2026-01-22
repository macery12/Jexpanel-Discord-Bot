"""Spark profiler report analyzer for Minecraft servers.

Analyzes Spark profiler reports to detect performance issues.

Architecture:
- Stage A: URL handling and JSON fetching
- Stage B: Normalization of raw Spark JSON into consistent schema
- Stage C-H: Pattern matching, suspect detection, recommendations (via pattern_matcher)

The parser is resilient to missing keys and version differences in Spark JSON.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import aiohttp

from .pattern_matcher import diagnose, format_diagnosis_for_discord

# Debug logging (enabled via SPARK_DEBUG=1 environment variable)
_logger = logging.getLogger(__name__)
_debug_enabled = os.environ.get("SPARK_DEBUG", "").strip() == "1"

def _debug_log(message: str, data: Any = None) -> None:
    """Log debug message if SPARK_DEBUG=1."""
    if _debug_enabled:
        if data is not None:
            _logger.info(f"[SPARK DEBUG] {message}: {data}")
        else:
            _logger.info(f"[SPARK DEBUG] {message}")

# Legacy severity thresholds (kept for backward compatibility with _analyze_performance)
# The new pattern matcher uses thresholds from rules.yml
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


# =============================================================================
# STAGE A: URL Handling and Fetching
# =============================================================================


# =============================================================================
# STAGE A: URL Handling and Fetching
# =============================================================================

def _ensure_raw_url(url: str) -> str:
    """Ensure the Spark URL has ?raw=1 parameter.
    
    Args:
        url: Original Spark URL
        
    Returns:
        URL with ?raw=1 parameter added
    """
    parts = urlparse(url)
    qs = parse_qs(parts.query, keep_blank_values=True)
    qs["raw"] = ["1"]
    new_query = urlencode(qs, doseq=True)
    return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))


def _validate_spark_url(url: str) -> bool:
    """Validate that this is a Spark profiler URL.
    
    Args:
        url: URL to validate
        
    Returns:
        True if URL appears to be a valid Spark profiler URL
    """
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


# =============================================================================
# STAGE B: Normalization - Parse raw Spark JSON into consistent schema
# =============================================================================

def _safe_div(numerator: float | int, denominator: float | int, default: float = 0.0) -> float:
    """Safely divide two numbers, returning default if denominator is 0.
    
    Args:
        numerator: Top number
        denominator: Bottom number
        default: Value to return if denominator is 0
        
    Returns:
        numerator / denominator, or default if division impossible
    """
    try:
        if denominator == 0:
            return default
        return float(numerator) / float(denominator)
    except (TypeError, ValueError, ZeroDivisionError):
        return default


def _parse_spark_json(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse raw Spark JSON into a normalized structure.
    
    This function extracts metrics from Spark's JSON format and normalizes them
    into a consistent schema that the pattern matcher can use. It handles missing
    keys gracefully and adapts to different Spark versions.
    
    The normalized structure includes:
    - platform: Server platform information (name, version, MC version)
    - run: Profile run metadata (duration, ticks, avg TPS)
    - tps: TPS metrics (last_1m, last_5m, last_15m, recent, average)
    - mspt: MSPT/tick time metrics (last_1m, last_5m)
    - tick: Derived tick metrics for pattern matching (mspt, spike_mspt)
    - players: Player count
    - player: Player metrics for pattern matching (online)
    - entities: Entity data (total, top breakdown)
    - world: World metrics (loaded_chunks, entities_total, tile_entities_total)
    - gc: Garbage collection data (young, old, raw collector data)
    - memory: Memory metrics (heap_used_mb, heap_committed_mb)
    - mods: Dictionary of installed mods (modid -> version)
    
    Args:
        raw: Raw Spark JSON dictionary from API
        
    Returns:
        Normalized dictionary with consistent schema
    """
    _debug_log("Parsing Spark JSON")
    
    # Extract top-level sections with safe defaults
    meta = raw.get("metadata") or {}
    platform = meta.get("platformStatistics") or {}
    sources = meta.get("sources") or {}
    
    # Platform info
    platform_info = meta.get("platform") or {}
    
    # Run info - calculate duration and average TPS
    start = meta.get("startTime") or 0
    end = meta.get("endTime") or 0
    duration = _safe_div(end - start, 1000) if start and end else 0.0
    ticks = meta.get("numberOfTicks") or 0
    avg_tps = round(_safe_div(ticks, duration), 2) if duration > 0 else 0.0
    
    # TPS / MSPT sections
    tps = platform.get("tps") or {}
    mspt = platform.get("mspt") or {}
    
    # World data (entities, chunks, tile entities)
    world = platform.get("world") or {}
    entity_counts = world.get("entityCounts") or {}
    
    # Sort entities by count and take top 10
    if entity_counts:
        top_entities = dict(sorted(entity_counts.items(), key=lambda x: x[1], reverse=True)[:10])
    else:
        top_entities = {}
    
    # GC data
    gc = platform.get("gc") or {}
    
    # Memory - heap section
    memory_data = platform.get("memory") or {}
    heap = memory_data.get("heap") or {}
    
    # Mods - filter out built-in sources
    # Sources format: {modid: {name: str, version: str, builtIn: bool}, ...}
    mods = {}
    for mod_id, info in (sources or {}).items():
        if isinstance(info, dict) and not info.get("builtIn", False):
            mods[mod_id] = info.get("version")
    
    _debug_log(f"Detected {len(mods)} mods")
    
    # Extract tick metrics for pattern matching
    tick_mspt = None
    tick_spike_mspt = None
    mspt_1m = mspt.get("last1m")
    if mspt_1m and isinstance(mspt_1m, dict):
        tick_mspt = mspt_1m.get("mean")
        tick_spike_mspt = mspt_1m.get("max")
    
    # Get recent TPS (preferring last1m, fallback to calculated average)
    tps_recent = tps.get("last1m")
    if tps_recent is None:
        tps_recent = avg_tps
    
    # Calculate average TPS from 5m and 15m windows
    tps_5m = tps.get("last5m")
    tps_15m = tps.get("last15m")
    if tps_5m is not None and tps_15m is not None:
        tps_average = (tps_5m + tps_15m) / 2
    else:
        tps_average = tps_recent
    
    # Extract world metrics (used by patterns)
    world_loaded_chunks = world.get("totalChunks")
    world_entities_total = world.get("totalEntities")
    world_tile_entities_total = world.get("totalBlockEntities")
    
    # Parse GC data - try to identify young vs old gen collectors
    gc_young = None
    gc_old = None
    if gc:
        for collector_name, collector_data in gc.items():
            if not isinstance(collector_data, dict):
                continue
            
            name_lower = collector_name.lower()
            collections = collector_data.get("total", 0)
            
            # Young gen indicators
            if any(keyword in name_lower for keyword in ["young", "scavenge", "copy", "parnew"]):
                gc_young = collections
            # Old gen indicators
            elif any(keyword in name_lower for keyword in ["old", "marksweep", "cms", "g1", "tenured"]):
                gc_old = collections
    
    _debug_log("TPS", tps_recent)
    _debug_log("MSPT", tick_mspt)
    _debug_log("Entities", world_entities_total)
    _debug_log("Chunks", world_loaded_chunks)
    
    # Build normalized structure
    normalized = {
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
            "recent": tps_recent,  # For pattern matching
            "average": tps_average,  # For pattern matching
        },
        "mspt": {
            "last_1m": mspt.get("last1m"),
            "last_5m": mspt.get("last5m"),
        },
        "tick": {
            "mspt": tick_mspt,  # For pattern matching
            "spike_mspt": tick_spike_mspt,  # For pattern matching
        },
        "players": platform.get("playerCount"),
        "player": {
            "online": platform.get("playerCount"),  # For pattern matching
        },
        "entities": {
            "total": world.get("totalEntities"),
            "top": top_entities,
        },
        "world": {
            "loaded_chunks": world_loaded_chunks,  # For pattern matching
            "entities_total": world_entities_total,  # For pattern matching
            "tile_entities_total": world_tile_entities_total,  # For pattern matching
        },
        "gc": {
            "young": gc_young,  # For pattern matching
            "old": gc_old,  # For pattern matching
            **gc,  # Keep original GC data
        },
        "memory": {
            "heap_used_mb": round(_safe_div(heap.get("used", 0), 1024 * 1024), 1),
            "heap_committed_mb": round(_safe_div(heap.get("committed", 0), 1024 * 1024), 1),
        },
        "mods": mods,
    }
    
    return normalized


# =============================================================================
# Legacy Analysis (kept for backward compatibility)
# These functions provide simple threshold-based alerts.
# The new system uses pattern_matcher.diagnose() instead.
# =============================================================================

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


# =============================================================================
# Main Entry Points
# =============================================================================

async def analyze_spark_report(url: str) -> dict[str, Any]:
    """Analyze a Spark profiler report from a URL.
    
    Main entry point for Spark analysis. Fetches the report, normalizes it,
    and runs pattern-based diagnosis.
    
    Args:
        url: The Spark report URL (will auto-add ?raw=1 if needed)
        
    Returns:
        Dictionary containing:
        - summary: Normalized Spark data
        - alerts: Legacy threshold-based alerts (for backward compatibility)
        - diagnosis: Pattern-based diagnosis from pattern_matcher
        
    Raises:
        ValueError: If the URL is invalid or report type is unsupported
        aiohttp.ClientError: If there's a network error
    """
    _debug_log(f"Analyzing Spark report: {url}")
    
    # Validate URL
    if not _validate_spark_url(url):
        raise ValueError(f"Invalid Spark URL: {url}")
    
    # Ensure ?raw=1 parameter
    raw_url = _ensure_raw_url(url)
    _debug_log(f"Fetching from: {raw_url}")
    
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
    
    # Parse the JSON (Stage B: Normalization)
    parsed_data = _parse_spark_json(raw_json)
    
    # Run legacy analysis (for backward compatibility)
    alerts = _analyze_performance(parsed_data)
    
    # Run pattern matcher (Stages C-H: Pattern matching, suspect detection, etc.)
    _debug_log("Running pattern matcher")
    diagnosis = diagnose(parsed_data)
    _debug_log("Diagnosis complete", {
        "status": diagnosis.get("overall_status"),
        "signals": len(diagnosis.get("signals", [])),
        "suspects": len(diagnosis.get("suspects", [])),
    })
    
    # Return structured result
    return {
        "summary": parsed_data,
        "alerts": alerts,
        "diagnosis": diagnosis,
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
    diagnosis = result.get("diagnosis", {})
    
    # If we have a diagnosis, use the new formatter
    if diagnosis:
        # Get the diagnosis-specific message
        diagnosis_message = format_diagnosis_for_discord(diagnosis, summary)
        
        # Add legacy alerts section if there are any unique alerts
        if alerts:
            diagnosis_message += "\n**⚠️ Additional Issues:**\n"
            for alert in alerts[:3]:  # Limit to 3
                severity = alert.get("severity", "LOW")
                emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(severity, "⚪")
                title = alert.get("title", "Unknown issue")
                diagnosis_message += f"{emoji} {title}\n"
        
        # Truncate if too long
        if len(diagnosis_message) > 2000:
            diagnosis_message = diagnosis_message[:1997] + "..."
        
        return diagnosis_message
    
    # Fallback to old formatter if no diagnosis
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
