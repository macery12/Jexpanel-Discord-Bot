"""Tests for Spark profiler analyzer."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from bot.utils.spark import (
    _detect_blocking_operations,
    _detect_entity_ai_lag,
    _detect_gc_pressure,
    _detect_redstone_lag,
    _detect_scheduler_abuse,
    _detect_source_cpu_overuse,
    _detect_tile_entity_lag,
    _extract_source_from_method,
    _flatten_call_tree,
    _get_severity,
    _match_known_mod,
    analyze_spark_report,
    format_discord_report,
)


class TestSourceExtraction:
    """Test source detection and extraction logic."""

    def test_extract_mod_with_version(self):
        """Test extracting mod source with version."""
        method = "create@0.5.1::ContraptionEntity.tick"
        source_type, source_name, clean_method = _extract_source_from_method(method)
        
        assert source_type == "mod"
        assert source_name == "create"
        assert clean_method == "ContraptionEntity.tick"

    def test_extract_plugin(self):
        """Test extracting plugin source."""
        method = "EssentialsX::PlayerCommandPreprocessEvent"
        source_type, source_name, clean_method = _extract_source_from_method(method)
        
        assert source_type == "plugin"
        assert source_name == "EssentialsX"
        assert clean_method == "PlayerCommandPreprocessEvent"

    def test_extract_vanilla(self):
        """Test vanilla method without source."""
        method = "net.minecraft.server.MinecraftServer.tick"
        source_type, source_name, clean_method = _extract_source_from_method(method)
        
        assert source_type == "vanilla"
        assert source_name == "minecraft"
        assert clean_method == method

    def test_match_known_mod_create(self):
        """Test matching Create mod."""
        mod_info = _match_known_mod("create")
        
        assert mod_info is not None
        assert mod_info["key"] == "create"
        assert "mechanical stress" in mod_info["issues"]

    def test_match_known_mod_ae2(self):
        """Test matching AE2 mod."""
        mod_info = _match_known_mod("appliedenergistics2")
        
        assert mod_info is not None
        assert mod_info["key"] == "ae2"
        assert "ME network recalculation" in mod_info["issues"]

    def test_match_unknown_mod(self):
        """Test unknown mod returns None."""
        mod_info = _match_known_mod("unknown_mod_xyz")
        
        assert mod_info is None


class TestSeverityCalculation:
    """Test severity threshold calculations."""

    def test_critical_severity(self):
        """Test CRITICAL severity threshold."""
        assert _get_severity(15.0) == "CRITICAL"
        assert _get_severity(10.0) == "CRITICAL"

    def test_high_severity(self):
        """Test HIGH severity threshold."""
        assert _get_severity(7.5) == "HIGH"
        assert _get_severity(5.0) == "HIGH"

    def test_medium_severity(self):
        """Test MEDIUM severity threshold."""
        assert _get_severity(3.5) == "MEDIUM"
        assert _get_severity(2.0) == "MEDIUM"

    def test_low_severity(self):
        """Test LOW severity threshold."""
        assert _get_severity(1.5) == "LOW"
        assert _get_severity(0.5) == "LOW"


class TestCallTreeFlattening:
    """Test call tree parsing and flattening."""

    def test_flatten_simple_tree(self):
        """Test flattening a simple call tree."""
        tree = {
            "name": "create@0.5.1::ContraptionEntity.tick",
            "totalTime": 5.5,
            "times": 100,
            "children": [
                {
                    "name": "create@0.5.1::KineticNetwork.update",
                    "totalTime": 3.2,
                    "times": 80,
                    "children": []
                }
            ]
        }
        
        records = _flatten_call_tree(tree)
        
        assert len(records) == 2
        assert records[0]["source_type"] == "mod"
        assert records[0]["source_name"] == "create"
        assert records[0]["self_time"] == 5.5
        assert records[1]["source_type"] == "mod"
        assert records[1]["source_name"] == "create"

    def test_flatten_plugin_tree(self):
        """Test flattening plugin call tree."""
        tree = {
            "name": "EssentialsX::onPlayerChat",
            "totalTime": 2.3,
            "times": 50,
            "children": []
        }
        
        records = _flatten_call_tree(tree)
        
        assert len(records) == 1
        assert records[0]["source_type"] == "plugin"
        assert records[0]["source_name"] == "EssentialsX"

    def test_flatten_inherits_parent_source(self):
        """Test that children inherit parent source when not specified."""
        tree = {
            "name": "create@0.5.1::ContraptionEntity.tick",
            "totalTime": 5.0,
            "times": 100,
            "children": [
                {
                    "name": "update",  # No source specified
                    "totalTime": 2.0,
                    "times": 50,
                    "children": []
                }
            ]
        }
        
        records = _flatten_call_tree(tree)
        
        assert len(records) == 2
        assert records[1]["source_type"] == "mod"
        assert records[1]["source_name"] == "create"


class TestDetectionRules:
    """Test performance issue detection rules."""

    def test_detect_blocking_io(self):
        """Test detection of blocking I/O operations."""
        records = [
            {
                "full_method": "java.io.FileInputStream.read",
                "method": "read",
                "source_type": "plugin",
                "source_name": "TestPlugin",
                "self_time": 5.5,
                "total_time": 5.5,
                "sample_count": 100,
            }
        ]
        
        alerts = _detect_blocking_operations(records)
        
        assert len(alerts) > 0
        assert "Blocking operation" in alerts[0]["title"]
        assert alerts[0]["severity"] in ["HIGH", "CRITICAL"]

    def test_detect_entity_lag(self):
        """Test detection of entity/AI lag."""
        records = [
            {
                "full_method": "net.minecraft.entity.LivingEntity.tick",
                "method": "tick",
                "source_type": "vanilla",
                "source_name": "minecraft",
                "self_time": 8.0,
                "total_time": 8.0,
                "sample_count": 200,
            }
        ]
        
        alerts = _detect_entity_ai_lag(records)
        
        assert len(alerts) > 0
        assert "Entity/AI" in alerts[0]["title"]

    def test_detect_tile_entity_lag(self):
        """Test detection of tile entity lag."""
        records = [
            {
                "full_method": "mekanism@10.3.9::TileEntityMekanism.tick",
                "method": "tick",
                "source_type": "mod",
                "source_name": "mekanism",
                "self_time": 6.0,
                "total_time": 6.0,
                "sample_count": 150,
            }
        ]
        
        alerts = _detect_tile_entity_lag(records)
        
        # Should detect and potentially match known mod
        assert len(alerts) > 0

    def test_detect_redstone_lag(self):
        """Test detection of redstone lag."""
        records = [
            {
                "full_method": "net.minecraft.block.PistonBlock.neighborChanged",
                "method": "neighborChanged",
                "source_type": "vanilla",
                "source_name": "minecraft",
                "self_time": 4.5,
                "total_time": 4.5,
                "sample_count": 100,
            }
        ]
        
        alerts = _detect_redstone_lag(records)
        
        assert len(alerts) > 0
        title_lower = alerts[0]["title"].lower()
        assert "redstone" in title_lower or "mechanical" in title_lower

    def test_detect_scheduler_abuse(self):
        """Test detection of scheduler abuse."""
        records = [
            {
                "full_method": "TestPlugin::BukkitRunnable.run",
                "method": "run",
                "source_type": "plugin",
                "source_name": "TestPlugin",
                "self_time": 12.0,
                "total_time": 12.0,
                "sample_count": 300,
            }
        ]
        
        alerts = _detect_scheduler_abuse(records)
        
        assert len(alerts) > 0
        assert "scheduler" in alerts[0]["title"].lower() or "task" in alerts[0]["title"].lower()

    def test_detect_gc_pressure(self):
        """Test detection of GC pressure."""
        records = [
            {
                "full_method": "java.util.ArrayList.grow",
                "method": "grow",
                "source_type": "vanilla",
                "source_name": "minecraft",
                "self_time": 7.0,
                "total_time": 7.0,
                "sample_count": 200,
            }
        ]
        
        alerts = _detect_gc_pressure(records)
        
        assert len(alerts) > 0
        assert "allocation" in alerts[0]["title"].lower() or "memory" in alerts[0]["title"].lower()

    def test_detect_source_cpu_overuse(self):
        """Test detection of CPU overuse by source."""
        sources = [
            {
                "type": "mod",
                "name": "create",
                "self_time": 15.5,
                "total_time": 15.5,
                "sample_count": 500,
            },
            {
                "type": "plugin",
                "name": "EssentialsX",
                "self_time": 3.2,
                "total_time": 3.2,
                "sample_count": 100,
            },
        ]
        
        alerts = _detect_source_cpu_overuse(sources)
        
        assert len(alerts) >= 1
        assert alerts[0]["source_name"] == "create"
        assert alerts[0]["severity"] == "CRITICAL"


class TestAnalyzeSparkReport:
    """Test the main analyze_spark_report function."""

    @pytest.mark.asyncio
    async def test_invalid_url(self):
        """Test handling of invalid URLs."""
        with pytest.raises(ValueError, match="Invalid URL"):
            await analyze_spark_report("not-a-url")

    @pytest.mark.asyncio
    async def test_empty_report_id(self):
        """Test handling of URLs without report ID."""
        with pytest.raises(ValueError, match="Cannot extract report ID"):
            await analyze_spark_report("https://spark.lucko.me/")
        
        with pytest.raises(ValueError, match="Cannot extract report ID"):
            await analyze_spark_report("https://spark.lucko.me")

    @pytest.mark.asyncio
    async def test_valid_url_parsing(self):
        """Test URL parsing and conversion to raw JSON."""
        test_data = {
            "metadata": {
                "platform": {
                    "name": "Paper",
                    "version": "1.20.1",
                    "minecraftVersion": "1.20.1",
                },
                "duration": 30.0,
                "samplerMode": "cpu",
            },
            "threads": [
                {
                    "name": "Server thread",
                    "totalTime": 100000,
                    "children": [
                        {
                            "name": "net.minecraft.server.MinecraftServer.tick",
                            "totalTime": 100000,
                            "children": [
                                {
                                    "name": "create@0.5.1::ContraptionEntity.tick",
                                    "totalTime": 15000,
                                    "children": []
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        
        async def mock_json():
            return test_data
        
        mock_response = Mock()
        mock_response.status = 200
        mock_response.json = mock_json
        
        async def mock_get(*args, **kwargs):
            return mock_response
        
        class MockSession:
            async def __aenter__(self):
                return self
            
            async def __aexit__(self, *args):
                pass
            
            def get(self, *args, **kwargs):
                class MockContext:
                    async def __aenter__(ctx_self):
                        return mock_response
                    async def __aexit__(ctx_self, *args):
                        pass
                return MockContext()
        
        with patch("aiohttp.ClientSession", MockSession):
            result = await analyze_spark_report("https://spark.lucko.me/test123")
        
        assert "summary" in result
        assert "top_sources" in result
        assert "alerts" in result
        assert result["summary"]["platform"] == "Paper 1.20.1"
        assert result["summary"]["mc_version"] == "1.20.1"
        assert result["summary"]["duration"] == 30.0

    @pytest.mark.asyncio
    async def test_http_error_handling(self):
        """Test handling of HTTP errors."""
        mock_response = Mock()
        mock_response.status = 404
        
        class MockSession:
            async def __aenter__(self):
                return self
            
            async def __aexit__(self, *args):
                pass
            
            def get(self, *args, **kwargs):
                class MockContext:
                    async def __aenter__(ctx_self):
                        return mock_response
                    async def __aexit__(ctx_self, *args):
                        pass
                return MockContext()
        
        with patch("aiohttp.ClientSession", MockSession):
            with pytest.raises(ValueError, match="Failed to fetch report"):
                await analyze_spark_report("https://spark.lucko.me/invalid")

    @pytest.mark.asyncio
    async def test_wrong_report_type(self):
        """Test handling of reports without sampler data."""
        test_data = {
            "metadata": {},
            # Missing sampler section
        }
        
        async def mock_json():
            return test_data
        
        mock_response = Mock()
        mock_response.status = 200
        mock_response.json = mock_json
        
        class MockSession:
            async def __aenter__(self):
                return self
            
            async def __aexit__(self, *args):
                pass
            
            def get(self, *args, **kwargs):
                class MockContext:
                    async def __aenter__(ctx_self):
                        return mock_response
                    async def __aexit__(ctx_self, *args):
                        pass
                return MockContext()
        
        with patch("aiohttp.ClientSession", MockSession):
            with pytest.raises(ValueError, match="Invalid Spark report"):
                await analyze_spark_report("https://spark.lucko.me/invalid123")

    @pytest.mark.asyncio
    async def test_empty_threadgroups(self):
        """Test handling of empty threads array."""
        test_data = {
            "metadata": {
                "platform": {
                    "name": "Forge",
                    "version": "47.4.0",
                    "minecraftVersion": "1.20.1",
                },
                "duration": 30.0,
            },
            "threads": []  # Empty threads array
        }
        
        async def mock_json():
            return test_data
        
        mock_response = Mock()
        mock_response.status = 200
        mock_response.json = mock_json
        
        class MockSession:
            async def __aenter__(self):
                return self
            
            async def __aexit__(self, *args):
                pass
            
            def get(self, *args, **kwargs):
                class MockContext:
                    async def __aenter__(ctx_self):
                        return mock_response
                    async def __aexit__(ctx_self, *args):
                        pass
                return MockContext()
        
        with patch("aiohttp.ClientSession", MockSession):
            # Should raise error about no profiler data
            with pytest.raises(ValueError, match="No profiler data"):
                await analyze_spark_report("https://spark.lucko.me/empty")

    @pytest.mark.asyncio
    async def test_threadgroups_parsing(self):
        """Test parsing of Spark threads format."""
        test_data = {
            "metadata": {
                "platform": {
                    "name": "Forge",
                    "version": "47.4.0",
                    "minecraftVersion": "1.20.1",
                },
                "duration": 60.0,
                "samplerMode": "cpu",
            },
            "threads": [
                {
                    "name": "Server thread",
                    "totalTime": 100000,
                    "children": [
                        {
                            "name": "net.minecraft.server.MinecraftServer.tick",
                            "totalTime": 50000,
                            "children": [
                                {
                                    "name": "create@0.5.1::ContraptionEntity.tick",
                                    "totalTime": 20000,
                                    "children": []
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        
        async def mock_json():
            return test_data
        
        mock_response = Mock()
        mock_response.status = 200
        mock_response.json = mock_json
        
        class MockSession:
            async def __aenter__(self):
                return self
            
            async def __aexit__(self, *args):
                pass
            
            def get(self, *args, **kwargs):
                class MockContext:
                    async def __aenter__(ctx_self):
                        return mock_response
                    async def __aexit__(ctx_self, *args):
                        pass
                return MockContext()
        
        with patch("aiohttp.ClientSession", MockSession):
            result = await analyze_spark_report("https://spark.lucko.me/test")
            
            # Should successfully parse threads format
            assert "summary" in result
            assert "top_sources" in result
            assert len(result["top_sources"]) > 0
            # Should have detected create mod
            assert any(s["name"] == "create" for s in result["top_sources"])

    @pytest.mark.asyncio
    async def test_multiple_threadgroups(self):
        """Test handling of multiple thread groups."""
        test_data = {
            "metadata": {
                "platform": {
                    "name": "Paper",
                    "version": "1.20.1",
                    "minecraftVersion": "1.20.1",
                },
                "duration": 30.0,
            },
            "threads": [
                {
                    "name": "Server thread",
                    "totalTime": 90000,
                    "children": [
                        {
                            "name": "net.minecraft.server.level.ServerLevel.tick",
                            "totalTime": 45000,
                            "children": []
                        }
                    ]
                },
                {
                    "name": "Async Chat Thread",
                    "totalTime": 10000,
                    "children": [
                        {
                            "name": "io.papermc.paper.chat.ChatProcessor.process",
                            "totalTime": 5000,
                            "children": []
                        }
                    ]
                }
            ]
        }
        
        async def mock_json():
            return test_data
        
        mock_response = Mock()
        mock_response.status = 200
        mock_response.json = mock_json
        
        class MockSession:
            async def __aenter__(self):
                return self
            
            async def __aexit__(self, *args):
                pass
            
            def get(self, *args, **kwargs):
                class MockContext:
                    async def __aenter__(ctx_self):
                        return mock_response
                    async def __aexit__(ctx_self, *args):
                        pass
                return MockContext()
        
        with patch("aiohttp.ClientSession", MockSession):
            result = await analyze_spark_report("https://spark.lucko.me/arrays")
            
            # Should successfully handle multiple threads
            assert "summary" in result
            assert "top_sources" in result
            # Should have aggregated the values correctly
            assert len(result["top_sources"]) > 0


class TestDiscordFormatting:
    """Test Discord message formatting."""

    def test_basic_formatting(self):
        """Test basic message formatting."""
        result = {
            "summary": {
                "platform": "Paper 1.20.1",
                "mc_version": "1.20.1",
                "duration": 30.0,
                "sampler": "cpu",
            },
            "top_sources": [
                {"type": "mod", "name": "create", "self_time": 15.5},
                {"type": "plugin", "name": "EssentialsX", "self_time": 5.2},
                {"type": "vanilla", "name": "minecraft", "self_time": 3.1},
            ],
            "alerts": [
                {
                    "severity": "CRITICAL",
                    "title": "High CPU usage: create",
                    "source_type": "mod",
                    "source_name": "create",
                    "evidence": ["15.5% total CPU time"],
                    "recommendation": "Reduce contraption complexity",
                }
            ],
        }
        
        message = format_discord_report(result)
        
        assert len(message) <= 2000
        assert "Spark Profile Analysis" in message
        assert "Paper 1.20.1" in message
        assert "create" in message
        assert "🔴" in message  # CRITICAL emoji
        assert "⚙️" in message  # mod emoji

    def test_no_alerts_formatting(self):
        """Test formatting when no alerts are detected."""
        result = {
            "summary": {
                "platform": "Paper 1.20.1",
                "mc_version": "1.20.1",
                "duration": 30.0,
                "sampler": "cpu",
            },
            "top_sources": [
                {"type": "vanilla", "name": "minecraft", "self_time": 1.5},
            ],
            "alerts": [],
        }
        
        message = format_discord_report(result)
        
        assert "No significant performance issues detected" in message or "✅" in message

    def test_truncation_for_long_content(self):
        """Test that very long content is truncated."""
        # Create a result with many alerts
        alerts = [
            {
                "severity": "HIGH",
                "title": f"Issue {i}" * 20,  # Long title
                "source_type": "mod",
                "source_name": f"mod{i}",
                "evidence": [f"Evidence {i}"],
                "recommendation": "Fix this issue by doing something" * 10,  # Long recommendation
            }
            for i in range(20)
        ]
        
        result = {
            "summary": {
                "platform": "Paper 1.20.1",
                "mc_version": "1.20.1",
                "duration": 30.0,
                "sampler": "cpu",
            },
            "top_sources": [],
            "alerts": alerts,
        }
        
        message = format_discord_report(result)
        
        # Should be under 2000 characters
        assert len(message) <= 2000

    def test_emoji_presence(self):
        """Test that appropriate emojis are used."""
        result = {
            "summary": {
                "platform": "Paper 1.20.1",
                "mc_version": "1.20.1",
                "duration": 30.0,
                "sampler": "cpu",
            },
            "top_sources": [
                {"type": "mod", "name": "create", "self_time": 10.0},
                {"type": "plugin", "name": "EssentialsX", "self_time": 5.0},
            ],
            "alerts": [
                {
                    "severity": "CRITICAL",
                    "title": "Critical issue",
                    "source_type": "mod",
                    "source_name": "create",
                    "evidence": [],
                    "recommendation": "Fix it",
                },
                {
                    "severity": "HIGH",
                    "title": "High issue",
                    "source_type": "plugin",
                    "source_name": "EssentialsX",
                    "evidence": [],
                    "recommendation": "Fix it",
                },
                {
                    "severity": "MEDIUM",
                    "title": "Medium issue",
                    "source_type": "vanilla",
                    "source_name": "minecraft",
                    "evidence": [],
                    "recommendation": "Fix it",
                },
            ],
        }
        
        message = format_discord_report(result)
        
        # Check for severity emojis
        assert "🔴" in message  # CRITICAL
        assert "🟠" in message  # HIGH
        assert "🟡" in message  # MEDIUM
        
        # Check for type emojis
        assert "⚙️" in message  # mod
        assert "🔌" in message  # plugin
