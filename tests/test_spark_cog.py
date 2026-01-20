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
