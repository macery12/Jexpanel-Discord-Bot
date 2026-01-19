# Spark Profiler Analyzer

The Spark profiler analyzer is a comprehensive performance diagnostic tool for Minecraft servers that analyzes Spark profiler reports to identify performance bottlenecks.

## Features

- **Multi-platform Support**: Analyzes Paper/Spigot plugins, Forge/Fabric mods, and vanilla Minecraft
- **Comprehensive Detection**: Identifies 7 categories of performance issues:
  - Source CPU overuse (mods/plugins consuming excessive resources)
  - Main-thread blocking operations (I/O, network, database)
  - Entity and AI overload
  - Block entity lag (tile entities)
  - Redstone and mechanical contraptions
  - Scheduler task abuse
  - GC and memory allocation pressure

- **Known Mod Intelligence**: Built-in knowledge base of common mods like Create, AE2, Mekanism, Thermal, etc. with specific recommendations
- **Actionable Recommendations**: Provides clear, specific guidance for resolving detected issues
- **Discord Integration**: Formatted output designed for Discord with emoji indicators and character limits

## Usage

### Discord Command

Use the `/spark` command in Discord:

```
/spark <url>
```

**Parameters:**
- `url`: The Spark profiler report URL (e.g., `https://spark.lucko.me/abc123`)

**Example:**
```
/spark https://spark.lucko.me/Rwfnmh4DqT
```

The bot will analyze the report and return a formatted message showing:
- Platform and Minecraft version
- Profile duration
- Top CPU consumers (mods/plugins/vanilla)
- Detected performance issues with severity levels
- Specific recommendations for each issue

### Programmatic Usage

```python
from bot.utils.spark import analyze_spark_report, format_discord_report

# Analyze a Spark report
result = await analyze_spark_report("https://spark.lucko.me/abc123")

# Format for Discord
message = format_discord_report(result)
```

## Output Structure

The analyzer returns a dictionary with the following structure:

```python
{
  "summary": {
    "platform": "Paper 1.20.1",      # Server platform and version
    "mc_version": "1.20.1",          # Minecraft version
    "duration": 30.0,                # Profile duration in seconds
    "sampler": "cpu"                 # Sampler type
  },
  "top_sources": [                   # Top CPU consumers
    {
      "type": "mod|plugin|vanilla",  # Source type
      "name": "create",              # Source name
      "self_time": 15.5              # CPU percentage
    }
  ],
  "alerts": [                        # Detected issues
    {
      "severity": "CRITICAL",        # CRITICAL, HIGH, MEDIUM, or LOW
      "title": "High CPU usage: create",
      "source_type": "mod",
      "source_name": "create",
      "evidence": [                  # Supporting data
        "15.5% total CPU time"
      ],
      "recommendation": "..."        # Actionable advice
    }
  ]
}
```

## Severity Levels

- 🔴 **CRITICAL** (>10% CPU): Immediate action required
- 🟠 **HIGH** (5-10% CPU): Significant performance impact
- 🟡 **MEDIUM** (2-5% CPU): Moderate performance impact
- 🟢 **LOW** (<2% CPU): Minor performance impact

## Detection Logic

### Source Classification

The analyzer automatically identifies the source of methods:
- **Mods**: Methods containing `@` version markers (e.g., `create@0.5.1::MethodName`)
- **Plugins**: Methods with `::` separator without version
- **Vanilla**: Everything else

### Known Mod Signatures

The analyzer includes knowledge of common mods:
- **Create**: Mechanical contraptions, kinetic networks
- **Applied Energistics 2**: ME networks, autocrafting
- **Mekanism**: Tile entities, gas/fluid simulation
- **Thermal**: Machine ticking, item/fluid transport
- **Botania**: Mana spreaders, flower ticking
- **Immersive Engineering**: Multiblocks, wire networks
- **Ender IO**: Conduit networks
- **IndustrialCraft**: E-net calculation

## Error Handling

The analyzer gracefully handles:
- Invalid URLs
- Expired or deleted reports
- Network failures
- Wrong report types (e.g., health reports instead of profiler reports)
- Malformed JSON

All errors return user-friendly messages explaining the issue.

## Testing

Run the test suite:

```bash
python -m pytest tests/test_spark.py tests/test_spark_cog.py -v
```

Test coverage includes:
- URL validation
- Source detection logic
- Severity calculations
- All detection rules
- Discord formatting
- Error handling
- Command integration

## Contributing

When adding new mod signatures, update `KNOWN_MOD_SIGNATURES` in `bot/utils/spark.py`:

```python
"modid": {
    "patterns": ["modid", "alternative_name"],
    "issues": ["common issue 1", "common issue 2"],
    "recommendations": "How to fix these issues",
}
```
