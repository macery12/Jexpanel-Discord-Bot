"""Tests for Spark cog."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import discord
import pytest
from discord.ext import commands

from bot.cogs.spark import SparkCog


class TestSparkCog:
    """Test Spark Discord command cog."""

    @pytest.fixture
    def bot(self):
        """Create a mock bot instance."""
        return Mock(spec=commands.Bot)

    @pytest.fixture
    def cog(self, bot):
        """Create a SparkCog instance."""
        return SparkCog(bot)

    @pytest.fixture
    def interaction(self):
        """Create a mock Discord interaction."""
        inter = AsyncMock(spec=discord.Interaction)
        inter.response = AsyncMock()
        inter.followup = AsyncMock()
        return inter

    @pytest.mark.asyncio
    async def test_spark_command_success(self, cog, interaction):
        """Test successful Spark report analysis."""
        mock_result = {
            "summary": {
                "platform": "Paper 1.20.1",
                "mc_version": "1.20.1",
                "duration": 30.0,
                "sampler": "cpu",
            },
            "top_sources": [
                {"type": "mod", "name": "create", "self_time": 15.5},
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

        with patch("bot.cogs.spark.analyze_spark_report", new_callable=AsyncMock) as mock_analyze:
            mock_analyze.return_value = mock_result
            
            with patch("bot.cogs.spark.format_discord_report") as mock_format:
                mock_format.return_value = "Test formatted message"
                
                await cog.spark_analyze.callback(cog, interaction, "https://spark.lucko.me/test123")
                
                # Verify defer was called
                interaction.response.defer.assert_called_once()
                
                # Verify analyze was called with correct URL
                mock_analyze.assert_called_once_with("https://spark.lucko.me/test123")
                
                # Verify format was called with result
                mock_format.assert_called_once_with(mock_result)
                
                # Verify followup was sent
                interaction.followup.send.assert_called_once_with("Test formatted message")

    @pytest.mark.asyncio
    async def test_spark_command_invalid_url(self, cog, interaction):
        """Test handling of invalid URL."""
        with patch("bot.cogs.spark.analyze_spark_report", new_callable=AsyncMock) as mock_analyze:
            mock_analyze.side_effect = ValueError("Invalid URL provided")
            
            await cog.spark_analyze.callback(cog, interaction, "not-a-url")
            
            # Verify defer was called
            interaction.response.defer.assert_called_once()
            
            # Verify error message was sent
            interaction.followup.send.assert_called_once()
            call_args = interaction.followup.send.call_args
            assert "Error analyzing Spark report" in call_args[0][0]
            assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_spark_command_fetch_error(self, cog, interaction):
        """Test handling of fetch errors."""
        with patch("bot.cogs.spark.analyze_spark_report", new_callable=AsyncMock) as mock_analyze:
            mock_analyze.side_effect = ValueError("Failed to fetch report: HTTP 404")
            
            await cog.spark_analyze.callback(cog, interaction, "https://spark.lucko.me/invalid")
            
            # Verify error message was sent
            interaction.followup.send.assert_called_once()
            call_args = interaction.followup.send.call_args
            assert "Error analyzing Spark report" in call_args[0][0]
            assert "404" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_spark_command_unexpected_error(self, cog, interaction):
        """Test handling of unexpected errors."""
        with patch("bot.cogs.spark.analyze_spark_report", new_callable=AsyncMock) as mock_analyze:
            mock_analyze.side_effect = Exception("Unexpected error")
            
            await cog.spark_analyze.callback(cog, interaction, "https://spark.lucko.me/test")
            
            # Verify error message was sent
            interaction.followup.send.assert_called_once()
            call_args = interaction.followup.send.call_args
            assert "Unexpected error" in call_args[0][0]
            assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_spark_auto_command_success(self, cog, interaction):
        """Test successful automated Spark profiling."""
        interaction.user = Mock()
        interaction.user.id = 123456

        mock_result = {
            "summary": {
                "platform": "Paper 1.20.1",
                "mc_version": "1.20.1",
                "duration": 30.0,
                "sampler": "cpu",
            },
            "top_sources": [],
            "alerts": [],
        }

        with patch("bot.cogs.spark.resolve_identifier_and_panel", new_callable=AsyncMock) as mock_resolve, \
             patch("bot.cogs.spark.get_user_token_for_panel", new_callable=AsyncMock) as mock_token, \
             patch("bot.cogs.spark.PteroClient") as mock_client_class, \
             patch("bot.cogs.spark.send_console_command", new_callable=AsyncMock) as mock_send_cmd, \
             patch("bot.cogs.spark.fetch_recent_logs", new_callable=AsyncMock) as mock_fetch_logs, \
             patch("bot.cogs.spark.analyze_spark_report", new_callable=AsyncMock) as mock_analyze, \
             patch("bot.cogs.spark.format_discord_report") as mock_format, \
             patch("bot.cogs.spark.asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
             patch("bot.cogs.spark.settings") as mock_settings:

            # Mock configuration
            mock_settings.spark_auto_command = "/spark profiler start --timeout 30 --interval 1"
            
            # Mock resolve
            mock_resolve.return_value = ("test-uuid-1234", "https://panel.example.com")
            
            # Mock token
            mock_token.return_value = "test-token-abc"
            
            # Mock client
            mock_client = Mock()
            mock_ws_info = {
                "data": {
                    "socket": "wss://panel.example.com/ws/test",
                    "token": "ws-token-xyz"
                }
            }
            mock_client.websocket_info = AsyncMock(return_value=mock_ws_info)
            mock_client_class.return_value = mock_client
            
            # Mock logs with Spark URL
            mock_fetch_logs.return_value = [
                "[INFO] Starting profiler...",
                "[INFO] Profiling complete!",
                "[INFO] View the report: https://spark.lucko.me/r9wZHyblRk"
            ]
            
            # Mock analysis
            mock_analyze.return_value = mock_result
            mock_format.return_value = "Test formatted message"
            
            await cog.spark_auto.callback(cog, interaction, "test-server")
            
            # Verify defer was called
            interaction.response.defer.assert_called_once()
            
            # Verify resolve was called
            mock_resolve.assert_called_once_with(123456, "test-server")
            
            # Verify token was fetched
            assert mock_token.call_count >= 1
            
            # Verify command was sent
            mock_send_cmd.assert_called_once()
            
            # Verify sleep was called with timeout + buffer
            mock_sleep.assert_called_once_with(35)  # 30 + 5
            
            # Verify logs were fetched
            mock_fetch_logs.assert_called_once()
            
            # Verify analysis was called with extracted URL
            mock_analyze.assert_called_once_with("https://spark.lucko.me/r9wZHyblRk")
            
            # Verify messages were sent
            assert interaction.followup.send.call_count >= 2

    @pytest.mark.asyncio
    async def test_spark_auto_command_no_url_in_logs(self, cog, interaction):
        """Test handling when Spark URL is not found in logs."""
        interaction.user = Mock()
        interaction.user.id = 123456

        with patch("bot.cogs.spark.resolve_identifier_and_panel", new_callable=AsyncMock) as mock_resolve, \
             patch("bot.cogs.spark.get_user_token_for_panel", new_callable=AsyncMock) as mock_token, \
             patch("bot.cogs.spark.PteroClient") as mock_client_class, \
             patch("bot.cogs.spark.send_console_command", new_callable=AsyncMock), \
             patch("bot.cogs.spark.fetch_recent_logs", new_callable=AsyncMock) as mock_fetch_logs, \
             patch("bot.cogs.spark.asyncio.sleep", new_callable=AsyncMock), \
             patch("bot.cogs.spark.settings") as mock_settings:

            # Mock configuration
            mock_settings.spark_auto_command = "/spark profiler start --timeout 30 --interval 1"
            
            # Mock resolve
            mock_resolve.return_value = ("test-uuid-1234", "https://panel.example.com")
            
            # Mock token
            mock_token.return_value = "test-token-abc"
            
            # Mock client
            mock_client = Mock()
            mock_ws_info = {
                "data": {
                    "socket": "wss://panel.example.com/ws/test",
                    "token": "ws-token-xyz"
                }
            }
            mock_client.websocket_info = AsyncMock(return_value=mock_ws_info)
            mock_client_class.return_value = mock_client
            
            # Mock logs without Spark URL
            mock_fetch_logs.return_value = [
                "[INFO] Starting profiler...",
                "[ERROR] Failed to generate profile!"
            ]
            
            await cog.spark_auto.callback(cog, interaction, "test-server")
            
            # Verify defer was called
            interaction.response.defer.assert_called_once()
            
            # Verify error message was sent
            assert interaction.followup.send.call_count >= 2
            last_call_args = interaction.followup.send.call_args_list[-1]
            assert "Could not find Spark profiler URL" in last_call_args[0][0]
            assert last_call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_spark_auto_command_server_not_found(self, cog, interaction):
        """Test handling when server is not found."""
        interaction.user = Mock()
        interaction.user.id = 123456

        with patch("bot.cogs.spark.resolve_identifier_and_panel", new_callable=AsyncMock) as mock_resolve:
            # Mock resolve returning None
            mock_resolve.return_value = (None, None)
            
            await cog.spark_auto.callback(cog, interaction, "nonexistent-server")
            
            # Verify defer was called
            interaction.response.defer.assert_called_once()
            
            # Verify error message was sent
            interaction.followup.send.assert_called_once()
            call_args = interaction.followup.send.call_args
            assert "Server not found" in call_args[0][0]
            assert call_args[1]["ephemeral"] is True

