"""Pattern-matching diagnosis system for Spark profiler data.

This module provides a rule-driven system for diagnosing Minecraft server performance
issues based on normalized Spark profiler data.

Architecture (Stages C-H from spark.py):
- Stage C: Pattern evaluation - match performance patterns against thresholds
- Stage D: Mod detection - identify which mods from rules are installed
- Stage E: Suspect scoring - gate suspects by patterns, calculate confidence
- Stage F: Entity breakdown - analyze entity sources and attribute to mods
- Stage G: Recommendation builder - build actionable recommendations
- Stage H: Discord formatter - format output for Discord

Key improvements:
1. Proper gating: Suspects only shown when patterns match AND tags overlap
2. Fixed entity detection: Only attributes entity suspects when entity patterns trigger
3. Better scoring: Combines multiple signals (severity, tag overlap, pattern weight)
4. Threshold enforcement: Minimum pattern weight (6) and confidence (55%) required

The system uses YAML rules to:
- Define performance thresholds
- Detect installed mods
- Evaluate server performance patterns  
- Match symptoms to suspected causes
- Generate actionable recommendations
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# Debug logging (enabled via SPARK_DEBUG=1 environment variable)
_logger = logging.getLogger(__name__)
_debug_enabled = os.environ.get("SPARK_DEBUG", "").strip() == "1"

def _debug_log(message: str, data: Any = None) -> None:
    """Log debug message if SPARK_DEBUG=1."""
    if _debug_enabled:
        if data is not None:
            _logger.info(f"[PATTERN_MATCHER DEBUG] {message}: {data}")
        else:
            _logger.info(f"[PATTERN_MATCHER DEBUG] {message}")


# Minimum thresholds for suspect reporting
MIN_PATTERN_WEIGHT = 6  # Require meaningful patterns (not just minor issues)
MIN_SUSPECT_CONFIDENCE = 55  # Require at least 55% confidence to report suspect


# =============================================================================
# Rules Loading
# =============================================================================

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


# =============================================================================
# Helper Functions
# =============================================================================

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


# =============================================================================
# STAGE D: Mod Detection
# =============================================================================

def _detect_mods(parsed_data: dict[str, Any], rules: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Detect which mods from the rules are present in the parsed data.
    
    IMPORTANT: Detection does NOT mean suspicion. A mod being installed doesn't
    make it a suspect. Suspects are determined later by pattern matching.
    
    Args:
        parsed_data: Normalized Spark data
        rules: Loaded rules dictionary
        
    Returns:
        Dictionary of detected mods {rule_key: {mod_data + detected_name + version}}
    """
    detected = {}
    mods_in_data = parsed_data.get("mods", {})
    
    if not mods_in_data:
        _debug_log("No mods found in data")
        return detected
    
    mod_rules = rules.get("mods", {})
    
    # Check each mod in the data against each rule
    for mod_id, mod_version in mods_in_data.items():
        for rule_key, rule_data in mod_rules.items():
            # First try exact modid match (if available in rule)
            rule_modid = rule_data.get("modid")
            if rule_modid and rule_modid == mod_id:
                detected[rule_key] = {
                    **rule_data,
                    "detected_name": mod_id,
                    "version": mod_version,
                }
                break  # Move to next mod
            
            # Fall back to pattern matching
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
    
    _debug_log(f"Detected {len(detected)} mods with rules", list(detected.keys())[:5])
    return detected


# =============================================================================
# STAGE C: Pattern Evaluation
# =============================================================================

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
    
    Patterns are performance signatures (e.g., "low_tps", "high_mspt", "entity_pressure")
    that trigger when specific metrics exceed thresholds.
    
    Args:
        parsed_data: Normalized Spark data
        rules: Loaded rules dictionary
        
    Returns:
        List of matched patterns with their data (id, weight, tags, explanation)
    """
    matched = []
    patterns = rules.get("patterns", [])
    thresholds = rules.get("thresholds", {})
    
    for pattern in patterns:
        if _evaluate_pattern(pattern, parsed_data, thresholds):
            matched.append(pattern)
    
    _debug_log(f"Matched {len(matched)} patterns", [p.get("id") for p in matched])
    return matched


# =============================================================================
# STAGE E: Suspect Scoring (with proper gating)
# =============================================================================

def _build_suspects(
    detected_mods: dict[str, Any], matched_patterns: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build a list of suspects with confidence scores.
    
    KEY FIX: Proper gating ensures suspects are only shown when:
    1. At least one pattern is matched (performance issue exists)
    2. Total pattern weight >= MIN_PATTERN_WEIGHT (meaningful issues, not minor)
    3. Mod tags overlap with matched pattern tags (mod is relevant to symptoms)
    4. Calculated confidence >= MIN_SUSPECT_CONFIDENCE (sufficient evidence)
    
    This prevents the bug where mods show as suspects just by being installed.
    
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
    
    # GATE 1: Don't show suspects if there's insufficient evidence of problems
    # Require at least MIN_PATTERN_WEIGHT (default 6) - one meaningful pattern
    if total_pattern_weight < MIN_PATTERN_WEIGHT:
        _debug_log(f"Pattern weight too low ({total_pattern_weight} < {MIN_PATTERN_WEIGHT}), no suspects")
        return []
    
    _debug_log(f"Pattern weight: {total_pattern_weight}, tags: {pattern_tags}")
    
    # Score each detected mod
    for mod_key, mod_data in detected_mods.items():
        mod_tags = set(mod_data.get("tags", []))
        matching_tags = mod_tags & pattern_tags
        
        # GATE 2: Mod is present but doesn't match any symptoms
        if not matching_tags:
            _debug_log(f"Mod {mod_key} has no matching tags, skipping")
            continue
        
        # Calculate confidence score
        # Base: severity (1-5) * 10 = 10-50
        base_confidence = mod_data.get("severity", 3) * 10
        
        # Bonus for tag overlap (each matching tag adds credibility)
        tag_overlap_bonus = len(matching_tags) * 5
        
        # Bonus proportional to pattern weight (stronger patterns = more confidence)
        pattern_bonus = min(30, total_pattern_weight)
        
        confidence = min(100, base_confidence + tag_overlap_bonus + pattern_bonus)
        
        # GATE 3: Require minimum confidence threshold to report as suspect
        if confidence < MIN_SUSPECT_CONFIDENCE:
            _debug_log(f"Mod {mod_key} confidence too low ({confidence} < {MIN_SUSPECT_CONFIDENCE}), skipping")
            continue
        
        # Build reasons list
        reasons = []
        if matching_tags:
            tag_list = ', '.join(sorted(matching_tags)[:3])
            reasons.append(f"Tags match symptoms: {tag_list}")
        
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
    
    _debug_log(f"Built {len(suspects)} suspects")
    return suspects


# =============================================================================
# STAGE G: Recommendation Builder
# =============================================================================

def _build_recommendations(
    detected_mods: dict[str, Any],
    matched_patterns: list[dict[str, Any]],
    suspects: list[dict[str, Any]],
    rules: dict[str, Any],
    entity_analysis: dict[str, Any] | None = None,
) -> list[str]:
    """Build list of actionable recommendations.
    
    Args:
        detected_mods: Dictionary of detected mods
        matched_patterns: List of matched patterns
        suspects: List of suspects
        rules: Loaded rules dictionary
        entity_analysis: Entity breakdown analysis (optional)
        
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
    
    # Add entity-specific tweaks if we have entity contributors
    if entity_analysis and entity_analysis.get("contributors"):
        entity_rules = rules.get("entities", {})
        mod_sources = entity_rules.get("mod_sources", {})
        
        for mod_key in entity_analysis["contributors"].keys():
            if mod_key in mod_sources:
                source_tweaks = mod_sources[mod_key].get("tweaks", [])
                for tweak in source_tweaks[:2]:  # Limit entity tweaks
                    if tweak not in added:
                        # Find mod display name
                        mod_name = mod_key
                        if mod_key in detected_mods:
                            mod_name = detected_mods[mod_key].get("display_name", mod_key)
                        
                        recommendations.append(f"**{mod_name} (entities)**: {tweak}")
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


# =============================================================================
# STAGE F: Entity Breakdown Analysis
# =============================================================================

def _analyze_entity_breakdown(
    parsed_data: dict[str, Any], detected_mods: dict[str, Any], rules: dict[str, Any]
) -> dict[str, Any]:
    """Analyze entity breakdown to identify mods contributing to entity counts.
    
    This function maps entity types (e.g., "alexsmobs:elephant") to the mods that
    add them, allowing us to attribute entity load to specific mods.
    
    Args:
        parsed_data: Normalized Spark data
        detected_mods: Dictionary of detected mods
        rules: Loaded rules dictionary
        
    Returns:
        Dictionary with entity analysis results:
        - total_entities: Total entity count
        - contributors: Mods contributing >=10% of entities with counts and types
        - thresholds: Entity thresholds from rules
    """
    entity_data = parsed_data.get("entities", {})
    top_entities = entity_data.get("top", {})
    total_entities = entity_data.get("total", 0)
    
    if not top_entities or not total_entities:
        _debug_log("No entity data available for breakdown")
        return {}
    
    # Get entity rules from rules.yml
    entity_rules = rules.get("entities", {})
    mod_sources = entity_rules.get("mod_sources", {})
    entity_thresholds = entity_rules.get("thresholds", {})
    
    # Track which mods are contributing entities
    mod_entity_contributions = {}
    
    for entity_type, count in top_entities.items():
        # Check each mod_source for matching entity patterns
        for mod_key, source_data in mod_sources.items():
            match_entities = source_data.get("match_entities", [])
            
            for pattern in match_entities:
                # Convert wildcard pattern to regex
                # e.g., "alexsmobs:*" -> "^alexsmobs:.*$"
                # Escape special regex characters except *
                regex_pattern = re.escape(pattern).replace(r"\*", ".*")
                regex_pattern = f"^{regex_pattern}$"
                
                if re.match(regex_pattern, entity_type, re.IGNORECASE):
                    if mod_key not in mod_entity_contributions:
                        mod_entity_contributions[mod_key] = {
                            "count": 0,
                            "types": [],
                            "why": source_data.get("why", ""),
                            "tweaks": source_data.get("tweaks", []),
                        }
                    mod_entity_contributions[mod_key]["count"] += count
                    mod_entity_contributions[mod_key]["types"].append(
                        {"type": entity_type, "count": count}
                    )
                    break  # Don't double-count
    
    # Calculate percentages and filter significant contributors
    significant_contributors = {}
    for mod_key, contribution in mod_entity_contributions.items():
        percentage = (contribution["count"] / total_entities) * 100
        if percentage >= 10:  # Only show mods contributing ≥10% of entities
            significant_contributors[mod_key] = {
                **contribution,
                "percentage": percentage,
            }
    
    _debug_log(f"Entity contributors: {len(significant_contributors)}", list(significant_contributors.keys()))
    
    return {
        "total_entities": total_entities,
        "contributors": significant_contributors,
        "thresholds": entity_thresholds,
    }


def _build_entity_suspects(
    entity_analysis: dict[str, Any],
    detected_mods: dict[str, Any],
    matched_patterns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build suspects list from entity analysis.
    
    KEY FIX: Only create entity suspects when entity patterns are triggered.
    This prevents showing entity suspects when there's no actual entity pressure.
    
    Args:
        entity_analysis: Entity breakdown analysis results
        detected_mods: Dictionary of detected mods
        matched_patterns: List of matched patterns
        
    Returns:
        List of suspects based on entity contributions (empty if no entity pressure)
    """
    suspects = []
    contributors = entity_analysis.get("contributors", {})
    total_entities = entity_analysis.get("total_entities", 0)
    
    # CRITICAL FIX: Check if entity patterns triggered
    # Only show entity suspects when entity_pressure or severe_entity_pressure patterns match
    has_entity_pattern = any(
        "entity" in p.get("id", "").lower() for p in matched_patterns
    )
    
    if not has_entity_pattern:
        _debug_log("No entity patterns matched, skipping entity suspects")
        return suspects  # Don't add entity suspects without entity pressure
    
    _debug_log(f"Entity patterns matched, processing {len(contributors)} contributors")
    
    for mod_key, contribution in contributors.items():
        # Check if mod is detected
        if mod_key not in detected_mods:
            continue
        
        mod_data = detected_mods[mod_key]
        percentage = contribution.get("percentage", 0)
        
        # Calculate confidence based on percentage contribution
        # Higher percentage = higher confidence
        base_confidence = min(80, int(percentage * 1.5))  # Cap at 80%
        
        # Boost if entity patterns are severe
        pattern_boost = 0
        for pattern in matched_patterns:
            if "severe_entity" in pattern.get("id", ""):
                pattern_boost = 10
                break
            elif "entity" in pattern.get("id", ""):
                pattern_boost = 5
        
        confidence = min(100, base_confidence + pattern_boost)
        
        # Build reasons
        entity_count = contribution['count']
        reasons = [
            f"Contributing {percentage:.1f}% of total entities "
            f"({entity_count}/{total_entities})"
        ]
        
        if contribution.get("why"):
            reasons.append(contribution["why"])
        
        suspects.append({
            "name": mod_data.get("display_name", mod_key),
            "type": "mod",
            "confidence": confidence,
            "reasons": reasons,
            "tags": mod_data.get("tags", []),
            "mod_key": mod_key,
            "entity_contribution": contribution,
        })
    
    return suspects


# =============================================================================
# Main Diagnosis Orchestrator
# =============================================================================

def diagnose(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Run the pattern matcher on normalized Spark data.
    
    Orchestrates the full diagnosis pipeline (Stages C-G):
    - Stage C: Evaluate patterns against data
    - Stage D: Detect installed mods  
    - Stage E: Score suspects (with proper gating)
    - Stage F: Analyze entity breakdown
    - Stage G: Build recommendations
    
    Args:
        parsed_data: Normalized dict from _parse_spark_json
        
    Returns:
        Diagnosis object with:
        - overall_status: "ok", "warn", or "bad"
        - signals: list of matched pattern IDs/explanations
        - suspects: ranked list with confidence scores (properly gated)
        - recommendations: actionable steps
        - missing_data: fields that would help diagnosis
        - known_issues: known issues from detected mods
        - entity_analysis: entity breakdown analysis (if available)
    """
    _debug_log("Starting diagnosis")
    rules = _load_rules()
    
    # Stage D: Detect mods present
    detected_mods = _detect_mods(parsed_data, rules)
    
    # Stage C: Match patterns
    matched_patterns = _match_patterns(parsed_data, rules)
    
    # Stage F: Analyze entity breakdown
    entity_analysis = _analyze_entity_breakdown(parsed_data, detected_mods, rules)
    
    # Build signals list
    signals = [
        f"{p.get('id', 'unknown')}: {p.get('explanation', 'No explanation')}"
        for p in matched_patterns
    ]
    
    # Stage E: Build suspects list (with proper gating)
    suspects = _build_suspects(detected_mods, matched_patterns)
    
    # Add entity-based suspects if we have significant entity contributors
    # AND entity patterns triggered (fixes entity detection bug)
    if entity_analysis and entity_analysis.get("contributors"):
        entity_suspects = _build_entity_suspects(
            entity_analysis, detected_mods, matched_patterns
        )
        # Merge with existing suspects
        existing_mod_keys = {s.get("mod_key"): i for i, s in enumerate(suspects)}
        for entity_suspect in entity_suspects:
            mod_key = entity_suspect.get("mod_key")
            if mod_key in existing_mod_keys:
                # Merge entity data into existing suspect
                idx = existing_mod_keys[mod_key]
                existing = suspects[idx]
                
                # Add entity-specific reasons
                entity_reasons = [r for r in entity_suspect.get("reasons", []) 
                                 if r not in existing.get("reasons", [])]
                existing["reasons"].extend(entity_reasons)
                
                # Boost confidence if entity contribution is significant
                entity_conf = entity_suspect.get("confidence", 0)
                if entity_conf > existing.get("confidence", 0):
                    # Use weighted average, favoring the higher confidence
                    existing["confidence"] = int(
                        (existing["confidence"] * 0.6) + (entity_conf * 0.4)
                    )
                
                # Add entity contribution data
                existing["entity_contribution"] = entity_suspect.get("entity_contribution")
            else:
                # New suspect from entity analysis
                suspects.append(entity_suspect)
        # Re-sort by confidence
        suspects.sort(key=lambda x: x["confidence"], reverse=True)
    
    # Stage G: Build recommendations
    recommendations = _build_recommendations(
        detected_mods, matched_patterns, suspects, rules, entity_analysis
    )
    
    # Extract known issues from suspects
    known_issues = []
    for suspect in suspects[:5]:  # Top 5 suspects
        mod_key = suspect.get("mod_key")
        if mod_key and mod_key in detected_mods:
            mod_data = detected_mods[mod_key]
            mod_name = mod_data.get("display_name", mod_key)
            issues = mod_data.get("known_issues", [])
            if issues:
                known_issues.append({
                    "mod": mod_name,
                    "issues": issues[:3]  # Limit to 3 issues per mod
                })
    
    # Identify missing data
    missing_data = _identify_missing_data(parsed_data, matched_patterns)
    
    # Determine overall status
    overall_status = _determine_overall_status(matched_patterns)
    
    _debug_log("Diagnosis complete", {
        "status": overall_status,
        "signals": len(signals),
        "suspects": len(suspects),
        "recommendations": len(recommendations),
    })
    
    return {
        "overall_status": overall_status,
        "signals": signals,
        "suspects": suspects,
        "recommendations": recommendations,
        "missing_data": missing_data,
        "known_issues": known_issues,
        "entity_analysis": entity_analysis,
    }


# =============================================================================
# STAGE H: Discord Formatter
# =============================================================================

def format_diagnosis_for_discord(diagnosis: dict[str, Any], parsed_data: dict[str, Any]) -> str:
    """Format diagnosis output for Discord.
    
    Stage H: Formats the complete diagnosis into a Discord-friendly message with:
    - Server status and platform info
    - Performance metrics with color-coded emojis
    - Top suspects (only when properly gated)
    - Known issues for suspected mods
    - Missing data indicators
    
    Args:
        diagnosis: Result from diagnose()
        parsed_data: The original parsed data
        
    Returns:
        Formatted string ready for Discord
    """
    lines = []
    
    # Header with platform info
    platform = _safe_get(parsed_data, "platform", {})
    run = _safe_get(parsed_data, "run", {})
    
    lines.append("📊 **Spark Profile Analysis**")
    platform_name = platform.get('name', 'Unknown')
    platform_ver = platform.get('version', 'Unknown')
    lines.append(f"**Platform:** {platform_name} {platform_ver}")
    lines.append(f"**MC Version:** {platform.get('mc_version', 'Unknown')}")
    lines.append(f"**Duration:** {run.get('duration_seconds', 0):.1f}s")
    lines.append("")
    
    # Status headline
    status = diagnosis["overall_status"]
    status_emoji = {"ok": "✅", "warn": "⚠️", "bad": "🔴"}
    lines.append(f"{status_emoji.get(status, '⚪')} **Server Status: {status.upper()}**")
    lines.append("")
    
    # Performance Metrics
    lines.append("**Performance:**")
    
    # TPS
    tps_1m = _safe_get(parsed_data, "tps.last_1m")
    if tps_1m is not None:
        tps_emoji = "🔴" if tps_1m < 15 else "🟠" if tps_1m < 18 else "🟢"
        lines.append(f"{tps_emoji} TPS (1m): {tps_1m:.1f}/20.0")
    
    # MSPT
    mspt_data = _safe_get(parsed_data, "mspt.last_1m")
    if mspt_data and isinstance(mspt_data, dict):
        mspt_mean = mspt_data.get("mean")
        if mspt_mean is not None:
            mspt_emoji = "🔴" if mspt_mean > 70 else "🟠" if mspt_mean > 50 else "🟢"
            lines.append(f"{mspt_emoji} MSPT (1m avg): {mspt_mean:.1f}ms")
    
    # Entities
    entities_total = _safe_get(parsed_data, "entities.total")
    if entities_total is not None:
        ent_emoji = "🔴" if entities_total > 1500 else "🟠" if entities_total > 1000 else "🟢"
        lines.append(f"{ent_emoji} Entities: {entities_total}")
    
    # Memory
    heap_used = _safe_get(parsed_data, "memory.heap_used_mb", 0)
    heap_committed = _safe_get(parsed_data, "memory.heap_committed_mb", 0)
    if heap_committed > 0:
        usage_pct = (heap_used / heap_committed) * 100
        mem_emoji = "🔴" if usage_pct > 90 else "🟠" if usage_pct > 80 else "🟢"
        mem_text = f"{heap_used:.0f}MB/{heap_committed:.0f}MB ({usage_pct:.0f}%)"
        lines.append(f"{mem_emoji} Memory: {mem_text}")
    
    # Players
    players = _safe_get(parsed_data, "players")
    if players is not None:
        lines.append(f"👥 Players: {players}")
    
    # Mods
    mods = _safe_get(parsed_data, "mods", {})
    if mods:
        lines.append(f"⚙️ Mods: {len(mods)}")
    
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
    
    # Known issues instead of recommendations
    known_issues = diagnosis.get("known_issues", [])
    if known_issues:
        lines.append("**⚠️ Known Issues:**")
        for issue_group in known_issues[:3]:  # Limit to top 3 mods
            mod_name = issue_group.get("mod", "Unknown")
            issues = issue_group.get("issues", [])
            if issues:
                lines.append(f"**{mod_name}:**")
                lines.extend(f"  • {issue}" for issue in issues)
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
