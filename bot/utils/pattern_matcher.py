"""Pattern-matching diagnosis system for Spark profiler data.

This module provides a rule-driven system for diagnosing Minecraft server performance issues
based on normalized Spark profiler data. It uses YAML rules to:
- Detect installed mods
- Evaluate server performance patterns
- Match symptoms to suspected causes
- Generate actionable recommendations
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


# Cache the rules file to avoid repeated I/O or network calls
@lru_cache(maxsize=1)
def _load_rules() -> dict[str, Any]:
    """Load and cache the rules.yml file.
    
    First checks SPARK_RULES_URL environment variable for a URL.
    If set, fetches the rules from that URL.
    Otherwise, falls back to local rules.yml file.
    
    Returns:
        Parsed YAML rules dictionary
        
    Raises:
        Exception: If rules cannot be loaded from either source
    """
    rules_url = os.environ.get("SPARK_RULES_URL")
    
    if rules_url and rules_url.strip():
        # Load from URL
        try:
            import urllib.request
            import warnings
            
            rules_url = rules_url.strip()
            if not rules_url.endswith('.yml'):
                warnings.warn(
                    f"SPARK_RULES_URL should end with .yml, got: {rules_url}. "
                    "Proceeding anyway...",
                    stacklevel=2
                )
            
            with urllib.request.urlopen(rules_url, timeout=10) as response:
                content = response.read()
                return yaml.safe_load(content)
        except Exception as e:
            import warnings
            warnings.warn(
                f"Failed to load rules from URL '{rules_url}': {e}. "
                "Falling back to local rules.yml",
                stacklevel=2
            )
            # Fall through to local file
    
    # Load from local file
    rules_path = Path(__file__).parent.parent.parent / "rules.yml"
    with open(rules_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _safe_get(data: dict[str, Any], path: str, default: Any = None) -> Any:
    """Safely get a nested dict value using dot notation.
    
    Args:
        data: The dictionary to search
        path: Dot-separated path (e.g., "tps.last_1m")
        default: Default value if path not found
        
    Returns:
        The value at the path, or default if not found
    """
    keys = path.split(".")
    current = data
    
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    
    return current


def _matches_mod(mod_name: str, pattern: str) -> bool:
    """Check if a mod name matches a pattern.
    
    Supports:
    - Exact match
    - Case-insensitive substring match
    - Regex patterns (prefixed with "regex:")
    
    Args:
        mod_name: The mod name to check
        pattern: The pattern to match against
        
    Returns:
        True if the mod matches the pattern
    """
    mod_name_lower = mod_name.lower()
    
    # Check for regex pattern
    if pattern.startswith("regex:"):
        regex_pattern = pattern[6:]  # Remove "regex:" prefix
        try:
            return bool(re.search(regex_pattern, mod_name, re.IGNORECASE))
        except re.error as e:
            # Log the error for debugging but don't crash
            # In production, this should use proper logging
            import warnings
            warnings.warn(f"Invalid regex pattern '{regex_pattern}': {e}", stacklevel=2)
            return False
    
    # Case-insensitive substring match
    pattern_lower = pattern.lower()
    return pattern_lower in mod_name_lower


def _detect_mods(parsed_data: dict[str, Any], rules: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Detect which mods from the rules are present in the parsed data.
    
    Args:
        parsed_data: Normalized Spark data
        rules: Loaded rules dictionary
        
    Returns:
        Dictionary of detected mods with their rules
    """
    detected = {}
    mods_in_data = parsed_data.get("mods", {})
    
    if not mods_in_data:
        return detected
    
    mod_rules = rules.get("mods", {})
    
    # Check each mod in the data against each rule
    for mod_id, mod_version in mods_in_data.items():
        for rule_key, rule_data in mod_rules.items():
            match_patterns = rule_data.get("match", [])
            
            # Check if any pattern matches
            matched = False
            for pattern in match_patterns:
                if _matches_mod(mod_id, pattern):
                    detected[rule_key] = {
                        **rule_data,
                        "detected_name": mod_id,
                        "version": mod_version,
                    }
                    matched = True
                    break  # Stop checking patterns for this rule
            
            if matched:
                break  # Move to next mod
    
    return detected


def _evaluate_condition(
    condition: dict[str, Any], parsed_data: dict[str, Any], thresholds: dict[str, Any]
) -> bool:
    """Evaluate a single condition against the parsed data.
    
    Args:
        condition: Condition dict with metric, op, and value/value_ref
        parsed_data: Normalized Spark data
        thresholds: Threshold values from rules
        
    Returns:
        True if the condition is met
    """
    metric_path = condition.get("metric", "")
    op = condition.get("op", "")
    
    # Get the actual value from parsed data
    actual_value = _safe_get(parsed_data, metric_path)
    
    # If value is missing/None, condition fails
    if actual_value is None:
        return False
    
    # Get the threshold value
    if "value_ref" in condition:
        threshold_path = condition["value_ref"]
        # Remove "thresholds." prefix if present
        if threshold_path.startswith("thresholds."):
            threshold_path = threshold_path[11:]
        threshold_value = _safe_get(thresholds, threshold_path)
        if threshold_value is None:
            return False
    elif "value" in condition:
        threshold_value = condition["value"]
    else:
        return False
    
    # Evaluate the operation
    try:
        actual_value = float(actual_value)
        threshold_value = float(threshold_value)
    except (ValueError, TypeError):
        return False
    
    if op == ">":
        return actual_value > threshold_value
    elif op == ">=":
        return actual_value >= threshold_value
    elif op == "<":
        return actual_value < threshold_value
    elif op == "<=":
        return actual_value <= threshold_value
    elif op == "==":
        return actual_value == threshold_value
    elif op == "!=":
        return actual_value != threshold_value
    
    return False


def _evaluate_pattern(
    pattern: dict[str, Any], parsed_data: dict[str, Any], thresholds: dict[str, Any]
) -> bool:
    """Evaluate a pattern's conditions.
    
    Args:
        pattern: Pattern dict from rules
        parsed_data: Normalized Spark data
        thresholds: Threshold values
        
    Returns:
        True if pattern matches
    """
    conditions = pattern.get("conditions", {})
    
    # Check "any" conditions (OR logic)
    if "any" in conditions:
        any_conditions = conditions["any"]
        if not isinstance(any_conditions, list):
            return False
        
        for condition in any_conditions:
            if _evaluate_condition(condition, parsed_data, thresholds):
                return True
        return False
    
    # Check "all" conditions (AND logic)
    if "all" in conditions:
        all_conditions = conditions["all"]
        if not isinstance(all_conditions, list):
            return False
        
        for condition in all_conditions:
            if not _evaluate_condition(condition, parsed_data, thresholds):
                return False
        return True
    
    return False


def _match_patterns(parsed_data: dict[str, Any], rules: dict[str, Any]) -> list[dict[str, Any]]:
    """Find all patterns that match the current data.
    
    Args:
        parsed_data: Normalized Spark data
        rules: Loaded rules dictionary
        
    Returns:
        List of matched patterns with their data
    """
    matched = []
    patterns = rules.get("patterns", [])
    thresholds = rules.get("thresholds", {})
    
    matched = [
        pattern for pattern in patterns if _evaluate_pattern(pattern, parsed_data, thresholds)
    ]
    
    return matched


def _build_suspects(
    detected_mods: dict[str, Any], matched_patterns: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build a list of suspects with confidence scores.
    
    Args:
        detected_mods: Dictionary of detected mods
        matched_patterns: List of matched patterns
        
    Returns:
        List of suspects sorted by confidence (highest first)
    """
    suspects = []
    
    # Collect all tags from matched patterns
    pattern_tags = set()
    total_pattern_weight = 0
    for pattern in matched_patterns:
        tags = pattern.get("tags", [])
        pattern_tags.update(tags)
        total_pattern_weight += pattern.get("weight", 0)
    
    # Score each detected mod
    for mod_key, mod_data in detected_mods.items():
        mod_tags = set(mod_data.get("tags", []))
        matching_tags = mod_tags & pattern_tags
        
        if not matching_tags:
            # Mod is present but doesn't match any symptoms
            continue
        
        # Calculate confidence
        # Base: severity (1-5) * 10 = 10-50
        base_confidence = mod_data.get("severity", 3) * 10
        
        # Bonus for tag overlap
        tag_overlap_bonus = len(matching_tags) * 5
        
        # Bonus proportional to pattern weight
        pattern_bonus = min(20, total_pattern_weight // 2)
        
        confidence = min(100, base_confidence + tag_overlap_bonus + pattern_bonus)
        
        # Build reasons list
        reasons = []
        if matching_tags:
            reasons.append(f"Tags match symptoms: {', '.join(sorted(matching_tags)[:3])}")
        
        suspects.append({
            "name": mod_data.get("display_name", mod_key),
            "type": "mod",
            "confidence": confidence,
            "reasons": reasons,
            "tags": list(mod_tags),
            "mod_key": mod_key,  # Keep for later reference
        })
    
    # Sort by confidence
    suspects.sort(key=lambda x: x["confidence"], reverse=True)
    
    return suspects


def _build_recommendations(
    detected_mods: dict[str, Any],
    matched_patterns: list[dict[str, Any]],
    suspects: list[dict[str, Any]],
    rules: dict[str, Any],
) -> list[str]:
    """Build list of actionable recommendations.
    
    Args:
        detected_mods: Dictionary of detected mods
        matched_patterns: List of matched patterns
        suspects: List of suspects
        rules: Loaded rules dictionary
        
    Returns:
        List of recommendation strings
    """
    recommendations = []
    added = set()  # Track to avoid duplicates
    
    # Add mod-specific tweaks for top suspects
    for suspect in suspects[:5]:  # Top 5 suspects
        mod_key = suspect.get("mod_key")
        if mod_key and mod_key in detected_mods:
            mod_data = detected_mods[mod_key]
            tweaks = mod_data.get("tweaks", [])
            for tweak in tweaks[:3]:  # Max 3 tweaks per mod
                if tweak not in added:
                    recommendations.append(f"**{suspect['name']}**: {tweak}")
                    added.add(tweak)
    
    # Add common recommendations based on matched pattern tags
    pattern_tags = set()
    for pattern in matched_patterns:
        pattern_tags.update(pattern.get("tags", []))
    
    common_recs = rules.get("common_recommendations", [])
    for rec_group in common_recs:
        when_tags = set(rec_group.get("when_tags", []))
        if when_tags & pattern_tags:  # If any tag matches
            for text in rec_group.get("text", [])[:2]:  # Max 2 per group
                if text not in added:
                    recommendations.append(text)
                    added.add(text)
    
    return recommendations[:10]  # Limit total recommendations


def _identify_missing_data(
    parsed_data: dict[str, Any], matched_patterns: list[dict[str, Any]]
) -> list[str]:
    """Identify what data is missing that would increase confidence.
    
    Args:
        parsed_data: Normalized Spark data
        matched_patterns: List of matched patterns
        
    Returns:
        List of missing data field descriptions
    """
    missing = []
    
    # Check for commonly useful fields
    useful_fields = {
        "tps.last_1m": "TPS (1 minute average)",
        "mspt.last_1m": "MSPT (tick time)",
        "entities.total": "Total entity count",
        "gc.young": "Young generation GC data",
        "gc.old": "Old generation GC data",
        "players": "Online player count",
    }
    
    for field, description in useful_fields.items():
        value = _safe_get(parsed_data, field)
        if value is None:
            missing.append(description)
    
    return missing


def _determine_overall_status(matched_patterns: list[dict[str, Any]]) -> str:
    """Determine overall server status.
    
    Args:
        matched_patterns: List of matched patterns
        
    Returns:
        "ok", "warn", or "bad"
    """
    if not matched_patterns:
        return "ok"
    
    # Check for critical patterns
    total_weight = sum(p.get("weight", 0) for p in matched_patterns)
    
    if total_weight >= 15:
        return "bad"
    elif total_weight >= 8:
        return "warn"
    else:
        return "ok"


def diagnose(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Run the pattern matcher on normalized Spark data.
    
    Args:
        parsed_data: Normalized dict from _parse_spark_json
        
    Returns:
        Diagnosis object with:
        - overall_status: "ok", "warn", or "bad"
        - signals: list of matched pattern IDs/explanations
        - suspects: ranked list with confidence scores
        - recommendations: actionable steps
        - missing_data: fields that would help diagnosis
    """
    rules = _load_rules()
    
    # Detect mods present
    detected_mods = _detect_mods(parsed_data, rules)
    
    # Match patterns
    matched_patterns = _match_patterns(parsed_data, rules)
    
    # Build signals list
    signals = [
        f"{p.get('id', 'unknown')}: {p.get('explanation', 'No explanation')}"
        for p in matched_patterns
    ]
    
    # Build suspects list
    suspects = _build_suspects(detected_mods, matched_patterns)
    
    # Build recommendations
    recommendations = _build_recommendations(detected_mods, matched_patterns, suspects, rules)
    
    # Identify missing data
    missing_data = _identify_missing_data(parsed_data, matched_patterns)
    
    # Determine overall status
    overall_status = _determine_overall_status(matched_patterns)
    
    return {
        "overall_status": overall_status,
        "signals": signals,
        "suspects": suspects,
        "recommendations": recommendations,
        "missing_data": missing_data,
    }


def format_diagnosis_for_discord(diagnosis: dict[str, Any], parsed_data: dict[str, Any]) -> str:
    """Format diagnosis output for Discord.
    
    Args:
        diagnosis: Result from diagnose()
        parsed_data: The original parsed data
        
    Returns:
        Formatted string ready for Discord
    """
    lines = []
    
    # Status headline
    status = diagnosis["overall_status"]
    status_emoji = {"ok": "✅", "warn": "⚠️", "bad": "🔴"}
    lines.append(f"{status_emoji.get(status, '⚪')} **Server Status: {status.upper()}**")
    lines.append("")
    
    # TPS/MSPT headline if available
    tps_1m = _safe_get(parsed_data, "tps.last_1m")
    if tps_1m is not None:
        tps_emoji = "🔴" if tps_1m < 15 else "🟠" if tps_1m < 18 else "🟢"
        lines.append(f"{tps_emoji} **TPS**: {tps_1m:.1f}/20.0")
    
    mspt_data = _safe_get(parsed_data, "mspt.last_1m")
    if mspt_data and isinstance(mspt_data, dict):
        mspt_mean = mspt_data.get("mean")
        if mspt_mean is not None:
            mspt_emoji = "🔴" if mspt_mean > 70 else "🟠" if mspt_mean > 50 else "🟢"
            lines.append(f"{mspt_emoji} **MSPT**: {mspt_mean:.1f}ms")
    
    # GC headline if available
    gc_data = _safe_get(parsed_data, "gc")
    if gc_data:
        lines.append(f"🗑️ **GC**: {len(gc_data)} collectors active")
    
    lines.append("")
    
    # Top suspects
    suspects = diagnosis.get("suspects", [])
    if suspects:
        lines.append("**🎯 Top Suspects:**")
        for suspect in suspects[:5]:  # Max 5
            conf = suspect["confidence"]
            name = suspect["name"]
            lines.append(f"  • {name} ({conf}% confidence)")
        lines.append("")
    
    # Recommendations grouped
    recommendations = diagnosis.get("recommendations", [])
    if recommendations:
        lines.append("**💡 Recommended Actions:**")
        lines.extend(f"  • {rec}" for rec in recommendations[:8])  # Limit to 8
        lines.append("")
    
    # Missing data
    missing = diagnosis.get("missing_data", [])
    if missing:
        lines.append("**📊 Capture Next Time:**")
        lines.extend(f"  • {item}" for item in missing[:5])  # Max 5
        lines.append("")
    
    message = "\n".join(lines)
    
    # Truncate if too long
    if len(message) > 2000:
        message = message[:1997] + "..."
    
    return message
