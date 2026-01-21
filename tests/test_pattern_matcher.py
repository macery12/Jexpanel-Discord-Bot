"""Tests for pattern_matcher module."""

from __future__ import annotations

import os

# Ensure no SPARK_RULES_URL is set for tests to use local file
if "SPARK_RULES_URL" in os.environ:
    del os.environ["SPARK_RULES_URL"]

from bot.utils.pattern_matcher import (
    _build_recommendations,
    _build_suspects,
    _detect_mods,
    _determine_overall_status,
    _evaluate_condition,
    _evaluate_pattern,
    _identify_missing_data,
    _load_rules,
    _match_patterns,
    _matches_mod,
    _safe_get,
    diagnose,
    format_diagnosis_for_discord,
)


class TestSafeGet:
    """Test safe dictionary access with dot notation."""

    def test_simple_get(self):
        """Test getting a simple value."""
        data = {"key": "value"}
        assert _safe_get(data, "key") == "value"

    def test_nested_get(self):
        """Test getting a nested value."""
        data = {"level1": {"level2": {"level3": "value"}}}
        assert _safe_get(data, "level1.level2.level3") == "value"

    def test_missing_key(self):
        """Test getting a missing key returns default."""
        data = {"key": "value"}
        assert _safe_get(data, "missing") is None
        assert _safe_get(data, "missing", "default") == "default"

    def test_missing_nested_key(self):
        """Test getting a missing nested key returns default."""
        data = {"level1": {"level2": "value"}}
        assert _safe_get(data, "level1.level3") is None
        assert _safe_get(data, "level1.level2.level3") is None

    def test_non_dict_value(self):
        """Test getting from non-dict value returns default."""
        data = {"key": "string"}
        assert _safe_get(data, "key.subkey") is None


class TestModMatching:
    """Test mod detection and matching."""

    def test_exact_match(self):
        """Test exact mod name matching."""
        assert _matches_mod("create", "create")

    def test_case_insensitive_match(self):
        """Test case-insensitive matching."""
        assert _matches_mod("Create", "create")
        assert _matches_mod("CREATE", "create")

    def test_substring_match(self):
        """Test substring matching."""
        assert _matches_mod("appliedenergistics2", "applied")
        assert _matches_mod("minecolonies", "mine")
        assert _matches_mod("minecolonies", "colonies")

    def test_regex_match(self):
        """Test regex pattern matching."""
        assert _matches_mod("minecolonies", r"regex:(?i)mine\s*colonies")
        assert _matches_mod("mine colonies", r"regex:(?i)mine\s*colonies")
        assert _matches_mod("MineColonies", r"regex:(?i)mine\s*colonies")

    def test_no_match(self):
        """Test when mod doesn't match."""
        assert not _matches_mod("create", "mekanism")
        assert not _matches_mod("botania", "create")


class TestModDetection:
    """Test mod detection from parsed data."""

    def test_detect_single_mod(self):
        """Test detecting a single mod."""
        parsed_data = {
            "mods": {
                "create": "0.5.1",
            }
        }
        rules = _load_rules()
        detected = _detect_mods(parsed_data, rules)
        
        assert "create" in detected
        assert detected["create"]["detected_name"] == "create"
        assert detected["create"]["version"] == "0.5.1"

    def test_detect_multiple_mods(self):
        """Test detecting multiple mods."""
        parsed_data = {
            "mods": {
                "create": "0.5.1",
                "mekanism": "10.3.9",
            }
        }
        rules = _load_rules()
        detected = _detect_mods(parsed_data, rules)
        
        assert "create" in detected
        assert "mekanism" in detected

    def test_detect_mod_with_variant_name(self):
        """Test detecting mod with different naming."""
        parsed_data = {
            "mods": {
                "appliedenergistics2": "12.9.0",
            }
        }
        rules = _load_rules()
        detected = _detect_mods(parsed_data, rules)
        
        # Should match "ae2" rule
        assert "applied_energistics_2" in detected

    def test_no_mods(self):
        """Test when no mods are present."""
        parsed_data = {"mods": {}}
        rules = _load_rules()
        detected = _detect_mods(parsed_data, rules)
        
        assert len(detected) == 0


class TestConditionEvaluation:
    """Test pattern condition evaluation."""

    def test_greater_than(self):
        """Test > operator."""
        condition = {"metric": "tps.recent", "op": ">", "value": 15.0}
        parsed_data = {"tps": {"recent": 18.0}}
        thresholds = {}
        
        assert _evaluate_condition(condition, parsed_data, thresholds) is True

    def test_less_than(self):
        """Test < operator."""
        condition = {"metric": "tps.recent", "op": "<", "value": 18.0}
        parsed_data = {"tps": {"recent": 15.0}}
        thresholds = {}
        
        assert _evaluate_condition(condition, parsed_data, thresholds) is True

    def test_threshold_reference(self):
        """Test using value_ref to reference thresholds."""
        condition = {"metric": "tps.recent", "op": "<", "value_ref": "thresholds.tps_warn"}
        parsed_data = {"tps": {"recent": 17.0}}
        thresholds = {"tps_warn": 18.0}
        
        assert _evaluate_condition(condition, parsed_data, thresholds) is True

    def test_missing_metric(self):
        """Test condition with missing metric returns False."""
        condition = {"metric": "tps.recent", "op": "<", "value": 18.0}
        parsed_data = {"tps": {}}
        thresholds = {}
        
        assert _evaluate_condition(condition, parsed_data, thresholds) is False

    def test_invalid_comparison(self):
        """Test condition with non-numeric values returns False."""
        condition = {"metric": "platform.name", "op": ">", "value": 10.0}
        parsed_data = {"platform": {"name": "Forge"}}
        thresholds = {}
        
        assert _evaluate_condition(condition, parsed_data, thresholds) is False


class TestPatternEvaluation:
    """Test pattern matching logic."""

    def test_pattern_with_any_conditions(self):
        """Test pattern with 'any' conditions (OR logic)."""
        pattern = {
            "id": "low_tps",
            "conditions": {
                "any": [
                    {"metric": "tps.recent", "op": "<", "value": 18.0},
                ]
            }
        }
        parsed_data = {"tps": {"recent": 15.0}}
        thresholds = {}
        
        assert _evaluate_pattern(pattern, parsed_data, thresholds) is True

    def test_pattern_with_all_conditions(self):
        """Test pattern with 'all' conditions (AND logic)."""
        pattern = {
            "id": "severe_lag",
            "conditions": {
                "all": [
                    {"metric": "tps.recent", "op": "<", "value": 15.0},
                    {"metric": "tick.mspt", "op": ">", "value": 70.0},
                ]
            }
        }
        parsed_data = {"tps": {"recent": 14.0}, "tick": {"mspt": 75.0}}
        thresholds = {}
        
        assert _evaluate_pattern(pattern, parsed_data, thresholds) is True

    def test_pattern_not_matching(self):
        """Test pattern that doesn't match."""
        pattern = {
            "id": "low_tps",
            "conditions": {
                "any": [
                    {"metric": "tps.recent", "op": "<", "value": 15.0},
                ]
            }
        }
        parsed_data = {"tps": {"recent": 20.0}}
        thresholds = {}
        
        assert _evaluate_pattern(pattern, parsed_data, thresholds) is False


class TestPatternMatching:
    """Test complete pattern matching."""

    def test_match_low_tps_pattern(self):
        """Test matching low TPS pattern."""
        parsed_data = {
            "tps": {"recent": 16.0},
            "tick": {"mspt": 55.0},
        }
        rules = _load_rules()
        matched = _match_patterns(parsed_data, rules)
        
        # Should match "low_tps" pattern
        pattern_ids = [p.get("id") for p in matched]
        assert "low_tps" in pattern_ids

    def test_match_high_mspt_pattern(self):
        """Test matching high MSPT pattern."""
        parsed_data = {
            "tps": {"recent": 19.0},
            "tick": {"mspt": 65.0},
        }
        rules = _load_rules()
        matched = _match_patterns(parsed_data, rules)
        
        # Should match "high_mspt" pattern
        pattern_ids = [p.get("id") for p in matched]
        assert "high_mspt" in pattern_ids

    def test_no_patterns_match(self):
        """Test when no patterns match."""
        parsed_data = {
            "tps": {"recent": 20.0},
            "tick": {"mspt": 40.0},
        }
        rules = _load_rules()
        matched = _match_patterns(parsed_data, rules)
        
        assert len(matched) == 0


class TestSuspectBuilding:
    """Test suspect list building."""

    def test_build_suspects_with_matching_tags(self):
        """Test building suspects when tags match."""
        detected_mods = {
            "create": {
                "display_name": "Create",
                "severity": 5,  # Higher severity
                "tags": ["automation", "ticking_block_entities", "machines"],  # More tags
            }
        }
        matched_patterns = [
            {
                "id": "tile_entity_pressure",
                "weight": 8,
                "tags": ["ticking_block_entities", "machines"],  # 2 matching tags
            }
        ]
        
        suspects = _build_suspects(detected_mods, matched_patterns)
        
        assert len(suspects) == 1
        assert suspects[0]["name"] == "Create"
        assert suspects[0]["type"] == "mod"
        assert suspects[0]["confidence"] >= 55  # Should meet minimum confidence

    def test_build_suspects_without_matching_tags(self):
        """Test building suspects when tags don't match."""
        detected_mods = {
            "botania": {
                "display_name": "Botania",
                "severity": 3,
                "tags": ["automation", "magic"],
            }
        }
        matched_patterns = [
            {
                "id": "entity_pressure",
                "weight": 6,
                "tags": ["entities", "mobs"],
            }
        ]
        
        suspects = _build_suspects(detected_mods, matched_patterns)
        
        # Mod is present but doesn't match symptoms, so should be empty
        assert len(suspects) == 0

    def test_build_suspects_low_pattern_weight(self):
        """Test that suspects are not shown when pattern weight is too low."""
        detected_mods = {
            "create": {
                "display_name": "Create",
                "severity": 4,
                "tags": ["automation", "ticking_block_entities"],
            }
        }
        matched_patterns = [
            {
                "id": "minor_issue",
                "weight": 3,  # Below threshold of 6
                "tags": ["ticking_block_entities"],
            }
        ]
        
        suspects = _build_suspects(detected_mods, matched_patterns)
        
        # Pattern weight too low, should not show suspects even with matching tags
        assert len(suspects) == 0

    def test_suspects_sorted_by_confidence(self):
        """Test that suspects are sorted by confidence."""
        detected_mods = {
            "create": {
                "display_name": "Create",
                "severity": 4,
                "tags": ["ticking_block_entities"],
            },
            "minecolonies": {
                "display_name": "MineColonies",
                "severity": 5,
                "tags": ["ai_pathfinding", "entities"],
            }
        }
        matched_patterns = [
            {
                "id": "entity_pressure",
                "weight": 9,
                "tags": ["entities", "ai_pathfinding"],
            }
        ]
        
        suspects = _build_suspects(detected_mods, matched_patterns)
        
        # MineColonies should be first (higher severity + better tag match)
        assert len(suspects) >= 1
        if len(suspects) > 1:
            assert suspects[0]["confidence"] >= suspects[1]["confidence"]


class TestRecommendations:
    """Test recommendation building."""

    def test_build_recommendations_from_suspects(self):
        """Test building recommendations from suspects."""
        detected_mods = {
            "create": {
                "display_name": "Create",
                "tweaks": [
                    "Reduce contraption complexity",
                    "Reduce belt/funnel throughput",
                ],
            }
        }
        suspects = [
            {
                "name": "Create",
                "mod_key": "create",
                "confidence": 75,
            }
        ]
        matched_patterns = []
        rules = _load_rules()
        
        recommendations = _build_recommendations(detected_mods, matched_patterns, suspects, rules)
        
        assert len(recommendations) > 0
        assert any("Create" in rec for rec in recommendations)


class TestMissingData:
    """Test missing data identification."""

    def test_identify_missing_tps(self):
        """Test identifying missing TPS data."""
        parsed_data = {
            "tick": {"mspt": 65.0},
        }
        matched_patterns = []
        
        missing = _identify_missing_data(parsed_data, matched_patterns)
        
        assert "TPS" in " ".join(missing)

    def test_identify_missing_entities(self):
        """Test identifying missing entity data."""
        parsed_data = {
            "tps": {"last_1m": 18.0},
            "tick": {"mspt": 55.0},
        }
        matched_patterns = []
        
        missing = _identify_missing_data(parsed_data, matched_patterns)
        
        assert "entity" in " ".join(missing).lower()


class TestOverallStatus:
    """Test overall status determination."""

    def test_status_ok_no_patterns(self):
        """Test OK status when no patterns match."""
        matched_patterns = []
        
        status = _determine_overall_status(matched_patterns)
        
        assert status == "ok"

    def test_status_warn_moderate_weight(self):
        """Test WARN status with moderate pattern weight."""
        matched_patterns = [
            {"id": "low_tps", "weight": 5},
            {"id": "high_mspt", "weight": 4},
        ]
        
        status = _determine_overall_status(matched_patterns)
        
        assert status == "warn"

    def test_status_bad_high_weight(self):
        """Test BAD status with high pattern weight."""
        matched_patterns = [
            {"id": "bad_tps", "weight": 8},
            {"id": "severe_mspt", "weight": 9},
        ]
        
        status = _determine_overall_status(matched_patterns)
        
        assert status == "bad"


class TestDiagnose:
    """Test the main diagnose function."""

    def test_diagnose_healthy_server(self):
        """Test diagnosing a healthy server."""
        parsed_data = {
            "tps": {"recent": 20.0},
            "tick": {"mspt": 40.0},
            "mods": {},
        }
        
        diagnosis = diagnose(parsed_data)
        
        assert diagnosis["overall_status"] == "ok"
        assert len(diagnosis["signals"]) == 0
        assert len(diagnosis["suspects"]) == 0

    def test_diagnose_low_tps_server(self):
        """Test diagnosing a server with low TPS."""
        parsed_data = {
            "tps": {"recent": 16.0},
            "tick": {"mspt": 60.0},
            "mods": {},
        }
        
        diagnosis = diagnose(parsed_data)
        
        assert diagnosis["overall_status"] in ["warn", "bad"]
        assert len(diagnosis["signals"]) > 0

    def test_diagnose_with_suspected_mod(self):
        """Test diagnosing with a suspected mod."""
        parsed_data = {
            "tps": {"recent": 17.0},
            "tick": {"mspt": 60.0},
            "world": {"tile_entities_total": 2500},
            "mods": {
                "create": "0.5.1",
            },
        }
        
        diagnosis = diagnose(parsed_data)
        
        assert len(diagnosis["suspects"]) > 0
        assert any("Create" in s["name"] for s in diagnosis["suspects"])
        assert len(diagnosis["recommendations"]) > 0


class TestDiscordFormatting:
    """Test Discord message formatting."""

    def test_format_healthy_diagnosis(self):
        """Test formatting a healthy diagnosis."""
        diagnosis = {
            "overall_status": "ok",
            "signals": [],
            "suspects": [],
            "recommendations": [],
            "missing_data": [],
        }
        parsed_data = {
            "tps": {"last_1m": 20.0},
            "tick": {"mspt": 45.0},
        }
        
        message = format_diagnosis_for_discord(diagnosis, parsed_data)
        
        assert "OK" in message
        assert len(message) <= 2000

    def test_format_with_suspects(self):
        """Test formatting with suspects."""
        diagnosis = {
            "overall_status": "warn",
            "signals": ["low_tps: Server TPS is below healthy threshold."],
            "suspects": [
                {
                    "name": "Create",
                    "type": "mod",
                    "confidence": 75,
                    "reasons": ["Tags match symptoms: automation, ticking_block_entities"],
                }
            ],
            "recommendations": [
                "**Create**: Reduce contraption complexity",
            ],
            "missing_data": [],
        }
        parsed_data = {
            "tps": {"last_1m": 17.0},
            "tick": {"mspt": 60.0},
        }
        
        message = format_diagnosis_for_discord(diagnosis, parsed_data)
        
        assert "WARN" in message
        assert "Create" in message
        assert len(message) <= 2000

    def test_format_truncates_long_messages(self):
        """Test that very long messages are truncated."""
        # Create a diagnosis with many suspects and recommendations
        suspects = [
            {
                "name": f"Mod{i}",
                "type": "mod",
                "confidence": 50 + i,
                "reasons": ["Long reason " * 20],
            }
            for i in range(20)
        ]
        recommendations = [f"Long recommendation {i} " * 30 for i in range(20)]
        
        diagnosis = {
            "overall_status": "bad",
            "signals": ["signal " * 50 for _ in range(10)],
            "suspects": suspects,
            "recommendations": recommendations,
            "missing_data": ["data " * 50 for _ in range(10)],
        }
        parsed_data = {
            "tps": {"last_1m": 10.0},
            "tick": {"mspt": 120.0},
        }
        
        message = format_diagnosis_for_discord(diagnosis, parsed_data)
        
        # Should be truncated to 2000 characters
        assert len(message) <= 2000
