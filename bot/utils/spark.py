"""Spark profiler report analyzer for Minecraft servers.

Analyzes Spark profiler reports to detect performance issues in
Paper/Spigot plugins, Forge/Fabric mods, and vanilla Minecraft.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import aiohttp

# Known mod signatures and their performance characteristics
KNOWN_MOD_SIGNATURES = {
    "create": {
        "patterns": ["create", "contraption", "kinetic"],
        "issues": ["mechanical stress", "kinetic networks", "block entity ticking"],
        "recommendations": (
            "Reduce contraption complexity, limit rotation propagation chains, "
            "decrease kinetic network size"
        ),
    },
    "ae2": {
        "patterns": ["appliedenergistics2", "ae2", "appeng"],
        "issues": ["ME network recalculation", "crafting CPU load", "channel calculation"],
        "recommendations": (
            "Optimize ME network layout, reduce autocrafting complexity, "
            "use storage buses efficiently"
        ),
    },
    "mekanism": {
        "patterns": ["mekanism"],
        "issues": ["tile ticking", "gas/fluid simulation", "transmitter networks"],
        "recommendations": (
            "Reduce machine count, optimize pipe networks, "
            "disable advanced features in config"
        ),
    },
    "thermal": {
        "patterns": ["thermal", "cofh"],
        "issues": ["machine ticking", "item/fluid transport"],
        "recommendations": "Consolidate machines, optimize item ducts, reduce chunk loading",
    },
    "botania": {
        "patterns": ["botania"],
        "issues": ["mana spreader and burst logic", "flower ticking"],
        "recommendations": "Reduce spreader count, optimize mana generation, consolidate flowers",
    },
    "immersiveengineering": {
        "patterns": ["immersiveengineering", "ie"],
        "issues": ["multiblock ticking", "wire networks"],
        "recommendations": (
            "Reduce multiblock count, optimize wire networks, consolidate power generation"
        ),
    },
    "enderio": {
        "patterns": ["enderio"],
        "issues": ["conduit networks", "machine ticking"],
        "recommendations": "Simplify conduit layouts, reduce machine density",
    },
    "industrialcraft": {
        "patterns": ["ic2", "industrialcraft"],
        "issues": ["e-net calculation", "machine updates"],
        "recommendations": "Optimize power network, reduce active machines",
    },
}

# Severity thresholds (percentage of total CPU time)
SEVERITY_THRESHOLDS = {
    "CRITICAL": 10.0,
    "HIGH": 5.0,
    "MEDIUM": 2.0,
    "LOW": 0.0,
}


def _get_severity(percentage: float) -> str:
    """Determine severity level based on CPU percentage."""
    if percentage >= SEVERITY_THRESHOLDS["CRITICAL"]:
        return "CRITICAL"
    elif percentage >= SEVERITY_THRESHOLDS["HIGH"]:
        return "HIGH"
    elif percentage >= SEVERITY_THRESHOLDS["MEDIUM"]:
        return "MEDIUM"
    else:
        return "LOW"


def _extract_source_from_method(method: str) -> tuple[str, str, str]:
    """Extract source information from a method name.
    
    Returns:
        tuple of (source_type, source_name, clean_method)
        where source_type is one of: "mod", "plugin", "vanilla"
    """
    # Check for :: separator (indicates source)
    if "::" in method:
        source_part, method_part = method.split("::", 1)
        
        # Check if source contains @ (mod with version)
        if "@" in source_part:
            # It's a mod - strip version
            mod_id = source_part.split("@")[0]
            return ("mod", mod_id, method_part)
        else:
            # It's a plugin
            return ("plugin", source_part, method_part)
    
    # No source information - classify as vanilla
    return ("vanilla", "minecraft", method)


def _match_known_mod(source_name: str) -> dict[str, Any] | None:
    """Match a source name against known mod signatures."""
    source_lower = source_name.lower()
    
    for mod_key, mod_data in KNOWN_MOD_SIGNATURES.items():
        for pattern in mod_data["patterns"]:
            if pattern in source_lower:
                return {"key": mod_key, **mod_data}
    
    return None


def _flatten_call_tree(
    node: dict[str, Any], parent_source: tuple[str, str] | None = None
) -> list[dict[str, Any]]:
    """Recursively flatten the Spark call tree into analyzable records.
    
    Args:
        node: A node from the Spark profiler call tree
        parent_source: Optional tuple of (source_type, source_name) from parent
        
    Returns:
        List of flattened records with source information
    """
    records = []
    
    # Get method name
    method = node.get("name", "")
    
    # Extract source information
    source_type, source_name, clean_method = _extract_source_from_method(method)
    
    # If no source found in this node, inherit from parent
    if source_type == "vanilla" and parent_source:
        source_type, source_name = parent_source
    
    # Create record for this node
    # Handle cases where totalTime or times might be arrays/lists (some Spark formats)
    total_time_raw = node.get("totalTime", 0.0)
    times_raw = node.get("times", 0)
    
    # If they're lists, take the first element or sum them
    if isinstance(total_time_raw, list):
        total_time = sum(total_time_raw) if total_time_raw else 0.0
    else:
        total_time = float(total_time_raw) if total_time_raw else 0.0
    
    if isinstance(times_raw, list):
        times = sum(times_raw) if times_raw else 0
    else:
        times = int(times_raw) if times_raw else 0
    
    record = {
        "method": clean_method,
        "full_method": method,
        "source_type": source_type,
        "source_name": source_name,
        "self_time": total_time,
        "total_time": total_time,
        "sample_count": times,
    }
    records.append(record)
    
    # Process children
    children = node.get("children", [])
    for child in children:
        child_records = _flatten_call_tree(child, (source_type, source_name))
        records.extend(child_records)
    
    return records


def _aggregate_by_source(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate CPU time by source (plugin/mod/vanilla)."""
    source_map: dict[tuple[str, str], dict[str, Any]] = {}
    
    for record in records:
        key = (record["source_type"], record["source_name"])
        
        if key not in source_map:
            source_map[key] = {
                "type": record["source_type"],
                "name": record["source_name"],
                "self_time": 0.0,
                "total_time": 0.0,
                "sample_count": 0,
            }
        
        source_map[key]["self_time"] += record["self_time"]
        source_map[key]["total_time"] += record["total_time"]
        source_map[key]["sample_count"] += record["sample_count"]
    
    # Sort by self_time descending
    sources = sorted(source_map.values(), key=lambda x: x["self_time"], reverse=True)
    
    return sources


def _detect_blocking_operations(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect main-thread blocking operations."""
    alerts = []
    
    blocking_patterns = [
        (r"java\.io\.", "File I/O on main thread"),
        (r"java\.net\.", "Network I/O on main thread"),
        (r"java\.sql\.|jdbc", "Database operations on main thread"),
        (r"Files\.(read|write)", "Synchronous file access"),
        (r"Socket\.(read|write|connect)", "Synchronous socket operations"),
    ]
    
    for record in records:
        method = record["full_method"]
        
        for pattern, description in blocking_patterns:
            if re.search(pattern, method, re.IGNORECASE):
                if record["self_time"] >= 1.0:  # Only alert if significant time
                    alerts.append({
                        "severity": _get_severity(record["self_time"]),
                        "title": f"Blocking operation: {description}",
                        "source_type": record["source_type"],
                        "source_name": record["source_name"],
                        "evidence": [f"{record['full_method']}: {record['self_time']:.2f}%"],
                        "recommendation": (
                            "Move blocking I/O operations to async tasks or separate threads "
                            "to prevent server lag"
                        ),
                    })
                break
    
    return alerts


def _detect_entity_ai_lag(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect entity, AI, and tick overload."""
    alerts = []
    
    entity_patterns = [
        (r"Entity\.tick|LivingEntity\.tick|Mob\.tick", "Heavy entity ticking"),
        (r"PathNavigation|pathfinding", "Pathfinding overhead"),
        (r"goalSelector|Brain\.tick", "AI goal processing"),
        (r"ai\.behavior|ai\.goal", "AI behavior execution"),
    ]
    
    total_entity_time = 0.0
    evidence_list = []
    
    for record in records:
        method = record["full_method"]
        
        for pattern, _ in entity_patterns:
            if re.search(pattern, method, re.IGNORECASE):
                total_entity_time += record["self_time"]
                if record["self_time"] >= 1.0:
                    evidence_list.append(f"{record['method']}: {record['self_time']:.2f}%")
                break
    
    if total_entity_time >= SEVERITY_THRESHOLDS["MEDIUM"]:
        alerts.append({
            "severity": _get_severity(total_entity_time),
            "title": "Entity/AI performance impact",
            "source_type": "vanilla",
            "source_name": "minecraft",
            "evidence": evidence_list[:5],  # Limit to top 5
            "recommendation": (
                "Reduce mob caps, limit entity-dense farms, disable advanced mob AI "
                "features, or use mob limiter plugins"
            ),
        })
    
    return alerts


def _detect_tile_entity_lag(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect modded tile/block entity lag."""
    alerts = []
    
    tile_patterns = [
        r"BlockEntity\.tick",
        r"TileEntity",
        r"capability",
        r"IItemHandler",
        r"IEnergyStorage",
    ]
    
    # Group by source
    source_tile_time: dict[tuple[str, str], float] = {}
    source_evidence: dict[tuple[str, str], list[str]] = {}
    
    for record in records:
        method = record["full_method"]
        
        for pattern in tile_patterns:
            if re.search(pattern, method, re.IGNORECASE):
                key = (record["source_type"], record["source_name"])
                source_tile_time[key] = source_tile_time.get(key, 0.0) + record["self_time"]
                
                if key not in source_evidence:
                    source_evidence[key] = []
                if record["self_time"] >= 0.5:
                    source_evidence[key].append(f"{record['method']}: {record['self_time']:.2f}%")
                break
    
    # Create alerts for significant sources
    for (source_type, source_name), time_pct in source_tile_time.items():
        if time_pct >= SEVERITY_THRESHOLDS["MEDIUM"]:
            # Check for known mod
            mod_info = _match_known_mod(source_name) if source_type == "mod" else None
            
            title = f"Block entity lag from {source_name}"
            recommendation = (
                "Reduce block entity count, consolidate machines, or optimize chunk loading"
            )
            
            if mod_info:
                title = f"Block entity lag: {mod_info['issues'][0]}"
                recommendation = mod_info["recommendations"]
            
            alerts.append({
                "severity": _get_severity(time_pct),
                "title": title,
                "source_type": source_type,
                "source_name": source_name,
                "evidence": source_evidence[(source_type, source_name)][:5],
                "recommendation": recommendation,
            })
    
    return alerts


def _detect_redstone_lag(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect redstone and mechanical lag."""
    alerts = []
    
    redstone_patterns = [
        r"piston",
        r"observer",
        r"redstone",
        r"RedstoneTorch",
        r"mechanical",
    ]
    
    total_redstone_time = 0.0
    evidence_list = []
    
    for record in records:
        method = record["full_method"]
        
        for pattern in redstone_patterns:
            if re.search(pattern, method, re.IGNORECASE):
                total_redstone_time += record["self_time"]
                if record["self_time"] >= 0.5:
                    evidence_list.append(f"{record['method']}: {record['self_time']:.2f}%")
                break
    
    if total_redstone_time >= SEVERITY_THRESHOLDS["MEDIUM"]:
        alerts.append({
            "severity": _get_severity(total_redstone_time),
            "title": "Redstone/mechanical contraption lag",
            "source_type": "vanilla",
            "source_name": "minecraft",
            "evidence": evidence_list[:5],
            "recommendation": (
                "Simplify redstone circuits, reduce observer usage, limit piston "
                "contraptions, or use Create mod optimizations"
            ),
        })
    
    return alerts


def _detect_scheduler_abuse(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect scheduler and task abuse."""
    alerts = []
    
    scheduler_patterns = [
        r"BukkitRunnable",
        r"BukkitScheduler",
        r"TickEvent",
        r"ServerTickEvent",
        r"repeatingTask",
    ]
    
    # Group by source
    source_scheduler_time: dict[tuple[str, str], float] = {}
    source_evidence: dict[tuple[str, str], list[str]] = {}
    
    for record in records:
        method = record["full_method"]
        
        for pattern in scheduler_patterns:
            if re.search(pattern, method, re.IGNORECASE):
                key = (record["source_type"], record["source_name"])
                source_scheduler_time[key] = (
                    source_scheduler_time.get(key, 0.0) + record["self_time"]
                )
                
                if key not in source_evidence:
                    source_evidence[key] = []
                if record["self_time"] >= 0.5:
                    source_evidence[key].append(f"{record['method']}: {record['self_time']:.2f}%")
                break
    
    # Create alerts for significant sources
    for (source_type, source_name), time_pct in source_scheduler_time.items():
        if time_pct >= SEVERITY_THRESHOLDS["HIGH"]:
            alerts.append({
                "severity": _get_severity(time_pct),
                "title": f"Excessive scheduler/task usage by {source_name}",
                "source_type": source_type,
                "source_name": source_name,
                "evidence": source_evidence[(source_type, source_name)][:5],
                "recommendation": (
                    "Review repeating tasks, increase task intervals, or batch operations "
                    "to reduce tick overhead"
                ),
            })
    
    return alerts


def _detect_gc_pressure(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect GC and allocation pressure."""
    alerts = []
    
    gc_patterns = [
        r"ArrayList\.grow",
        r"HashMap\.resize",
        r"ByteBuffer\.allocate",
        r"Unsafe\.allocate",
        r"\[\]\.clone",
        r"StringBuilder\.append",
    ]
    
    total_allocation_time = 0.0
    evidence_list = []
    
    for record in records:
        method = record["full_method"]
        
        for pattern in gc_patterns:
            if re.search(pattern, method, re.IGNORECASE):
                total_allocation_time += record["self_time"]
                if record["self_time"] >= 0.5:
                    evidence_list.append(f"{record['method']}: {record['self_time']:.2f}%")
                break
    
    if total_allocation_time >= SEVERITY_THRESHOLDS["HIGH"]:
        alerts.append({
            "severity": _get_severity(total_allocation_time),
            "title": "High allocation/memory pressure",
            "source_type": "vanilla",
            "source_name": "minecraft",
            "evidence": evidence_list[:5],
            "recommendation": (
                "Investigate object pooling, reduce collection resizing, or increase "
                "initial capacity of frequently-grown collections"
            ),
        })
    
    return alerts


def _detect_source_cpu_overuse(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect individual sources consuming excessive CPU."""
    alerts = []
    
    # Report top 5 sources
    for source in sources[:5]:
        severity = _get_severity(source["self_time"])
        
        # Skip if not at least MEDIUM
        if source["self_time"] < SEVERITY_THRESHOLDS["MEDIUM"]:
            continue
        
        # Check for known mod
        mod_info = None
        if source["type"] == "mod":
            mod_info = _match_known_mod(source["name"])
        
        title = f"High CPU usage: {source['name']}"
        recommendation = f"Investigate {source['name']} configuration and reduce its workload"
        
        if mod_info:
            title = f"High CPU: {source['name']} ({', '.join(mod_info['issues'][:2])})"
            recommendation = mod_info["recommendations"]
        
        alerts.append({
            "severity": severity,
            "title": title,
            "source_type": source["type"],
            "source_name": source["name"],
            "evidence": [f"{source['self_time']:.2f}% total CPU time"],
            "recommendation": recommendation,
        })
    
    return alerts


async def analyze_spark_report(url: str) -> dict[str, Any]:
    """Analyze a Spark profiler report URL.
    
    Args:
        url: Spark profiler report URL (e.g., https://spark.lucko.me/...)
        
    Returns:
        Dictionary containing analysis results suitable for Discord reporting.
        
    Raises:
        ValueError: If URL is invalid or report cannot be fetched
    """
    # Validate URL
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Invalid URL provided")

    # Construct raw full JSON URL for Lucko
    if "spark.lucko.me" in parsed.netloc or "sparkprofile" in url:
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) > 0 and path_parts[-1]:
            report_id = path_parts[-1]
            json_url = f"https://spark.lucko.me/{report_id}?raw=1&full=true"
        else:
            raise ValueError("Cannot extract report ID from URL")
    else:
        json_url = url

    # Fetch the report JSON
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(json_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    raise ValueError(f"Failed to fetch report: HTTP {response.status}")
                data = await response.json()
    except Exception as e:
        raise ValueError(f"Failed to fetch or parse report JSON: {e}") from e

    if not data:
        raise ValueError("Empty report data")

    # Determine sampler type
    sampler_type = data.get("type")  # top-level
    if not sampler_type and "samplerMetadata" in data:
        sampler_type = data["samplerMetadata"].get("type", "")

    if sampler_type != "sampler":
        raise ValueError(f"Invalid report type: expected 'sampler', got '{sampler_type}'")

    # Extract platform info
    metadata = data.get("metadata", {})
    platform_info = metadata.get("platform", {})
    platform_name = platform_info.get("name", "Unknown")
    platform_version = platform_info.get("version", "Unknown")
    mc_version = platform_info.get("minecraftVersion", "Unknown")

    # Extract sampler info
    sampler_metadata = data.get("samplerMetadata", {})
    start_time = sampler_metadata.get("startTime", 0)
    end_time = sampler_metadata.get("endTime", 0)
    # If endTime missing, fallback to duration 0
    duration_sec = ((end_time - start_time) / 1000.0) if (end_time and start_time) else 0.0
    sampler_mode = sampler_metadata.get("samplerMode", "cpu")

    summary = {
        "platform": f"{platform_name} {platform_version}",
        "mc_version": mc_version,
        "duration": duration_sec,
        "sampler": sampler_mode,
    }

    # Parse threads
    threads = data.get("threads", [])
    all_records = []

    def get_thread_roots(thread: dict) -> list[dict]:
        """Extract root nodes from thread, handling both rootNodes and rootNode."""
        # Check rootNodes first (plural, used in full JSON format)
        if "rootNodes" in thread:
            nodes = thread["rootNodes"]
            if nodes is not None:
                return nodes if isinstance(nodes, list) else [nodes]
        # Fallback to rootNode (singular, used in basic format)
        if "rootNode" in thread:
            node = thread["rootNode"]
            if node is not None:
                return [node]
        # Some Spark formats: thread itself might be the root node
        # Check if thread has the fields that would make it a valid node
        if "children" in thread and "times" in thread:
            # Thread is structured as a call tree node itself
            return [thread]
        return []

    for thread in threads:
        # Check server/main thread first
        thread_name = thread.get("name", "").lower()
        if "server" in thread_name or "main" in thread_name:
            roots = get_thread_roots(thread)
            for root in roots:
                records = _flatten_call_tree(root)
                all_records.extend(records)

    # If still empty, fallback to all threads
    if not all_records:
        for thread in threads:
            roots = get_thread_roots(thread)
            for root in roots:
                records = _flatten_call_tree(root)
                all_records.extend(records)

    if not all_records:
        # Provide helpful debugging info
        if not threads:
            raise ValueError("No threads found in report")
        
        # Check what fields the threads actually have
        thread_info = []
        for i, thread in enumerate(threads[:3]):  # Check first 3 threads
            thread_keys = list(thread.keys())
            thread_info.append(f"Thread {i} ({thread.get('name', 'unnamed')}): {thread_keys}")
        
        debug_msg = "No call tree records found in report. " + "; ".join(thread_info)
        raise ValueError(debug_msg)

    # Calculate total time from the first record (usually the root)
    # In Spark, the first record is typically the root with total profiling time
    total_time = all_records[0]["total_time"] if all_records else 1.0
    
    # If total_time is still 0, use sum of all top-level times
    if total_time == 0:
        total_time = sum(r["total_time"] for r in all_records)
    
    # Avoid division by zero
    if total_time == 0:
        total_time = 1.0
    
    # Convert absolute times to percentages relative to total profiling time
    for record in all_records:
        record["self_time"] = (record["self_time"] / total_time) * 100.0
        record["total_time"] = (record["total_time"] / total_time) * 100.0

    # Aggregate by source
    top_sources = _aggregate_by_source(all_records)

    # Run detection rules
    alerts = []
    alerts.extend(_detect_source_cpu_overuse(top_sources))
    alerts.extend(_detect_blocking_operations(all_records))
    alerts.extend(_detect_entity_ai_lag(all_records))
    alerts.extend(_detect_tile_entity_lag(all_records))
    alerts.extend(_detect_redstone_lag(all_records))
    alerts.extend(_detect_scheduler_abuse(all_records))
    alerts.extend(_detect_gc_pressure(all_records))

    # Sort alerts by severity
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    alerts.sort(key=lambda a: severity_order.get(a["severity"], 999))

    return {
        "summary": summary,
        "top_sources": top_sources[:10],  # top 10 sources
        "alerts": alerts,
    }



def format_discord_report(result: dict[str, Any]) -> str:
    """Format analysis results as a Discord-ready message.
    
    Args:
        result: Analysis result dictionary from analyze_spark_report()
        
    Returns:
        Formatted string suitable for Discord (under 2000 characters)
    """
    # Emoji mapping
    severity_emoji = {
        "CRITICAL": "🔴",
        "HIGH": "🟠",
        "MEDIUM": "🟡",
        "LOW": "🟢",
    }
    
    type_emoji = {
        "mod": "⚙️",
        "plugin": "🔌",
        "vanilla": "📦",
    }
    
    summary = result.get("summary", {})
    top_sources = result.get("top_sources", [])
    alerts = result.get("alerts", [])
    
    # Build message
    lines = []
    lines.append("**📊 Spark Profile Analysis**")
    lines.append(f"Platform: {summary.get('platform', 'Unknown')}")
    lines.append(
        f"MC: {summary.get('mc_version', 'Unknown')} | "
        f"Duration: {summary.get('duration', 0):.1f}s"
    )
    lines.append("")
    
    # Top sources
    if top_sources:
        lines.append("**Top CPU Consumers:**")
        for i, source in enumerate(top_sources[:5], 1):
            emoji = type_emoji.get(source["type"], "")
            lines.append(f"{i}. {emoji} {source['name']}: {source['self_time']:.1f}%")
        lines.append("")
    
    # Alerts
    if alerts:
        lines.append("**⚠️ Issues Detected:**")
        
        # Limit alerts to fit in Discord limit
        displayed_alerts = 0
        for alert in alerts[:8]:  # Max 8 alerts
            severity = alert.get("severity", "LOW")
            emoji = severity_emoji.get(severity, "")
            title = alert.get("title", "Unknown issue")
            
            # Create compact alert line
            alert_line = f"{emoji} **{title}**"
            
            # Add source if not vanilla
            if alert.get("source_type") != "vanilla":
                source_emoji = type_emoji.get(alert["source_type"], "")
                alert_line += f" ({source_emoji} {alert['source_name']})"
            
            lines.append(alert_line)
            
            # Add recommendation (truncated if needed)
            rec = alert.get("recommendation", "")
            if rec:
                rec_short = rec[:100] + "..." if len(rec) > 100 else rec
                lines.append(f"  → {rec_short}")
            
            displayed_alerts += 1
        
        if len(alerts) > displayed_alerts:
            lines.append(f"  ... and {len(alerts) - displayed_alerts} more issues")
    else:
        lines.append("✅ No significant performance issues detected")
    
    # Join and ensure under 2000 chars
    message = "\n".join(lines)
    
    if len(message) > 2000:
        # Truncate and add indicator
        message = message[:1950] + "\n\n... (truncated)"
    
    return message
