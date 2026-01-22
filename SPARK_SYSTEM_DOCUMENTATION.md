# Spark Analysis System Documentation

## Overview

The Spark analysis system analyzes Minecraft Spark profiler reports to diagnose server performance issues. It uses a multi-stage pipeline with pattern-based diagnosis and proper gating to prevent false positives.

## Architecture

The system is divided into 8 distinct stages across two modules:

### `bot/utils/spark.py` - Stages A & B (Fetching & Normalization)

#### Stage A: URL Handling and Fetching
- **Purpose**: Convert Spark URLs to raw format and fetch JSON
- **Functions**: `_ensure_raw_url()`, `_validate_spark_url()`
- **Input**: Spark profile URL (e.g., `https://spark.lucko.me/abc123`)
- **Output**: Raw Spark JSON dictionary

#### Stage B: Normalization
- **Purpose**: Parse raw Spark JSON into consistent schema
- **Function**: `_parse_spark_json()`
- **Key Features**:
  - Handles missing keys gracefully (all `.get()` calls with defaults)
  - Supports different Spark versions
  - Extracts: platform info, TPS, MSPT, entities, chunks, players, GC, memory, mods
  - Uses `_safe_div()` to prevent division errors
- **Output**: Normalized dictionary with consistent structure

### `bot/utils/pattern_matcher.py` - Stages C-H (Pattern Matching & Diagnosis)

#### Stage C: Pattern Evaluation
- **Purpose**: Match performance patterns against metrics
- **Functions**: `_evaluate_condition()`, `_evaluate_pattern()`, `_match_patterns()`
- **Key Features**:
  - Evaluates patterns from `rules.yml`
  - Supports `any` (OR) and `all` (AND) condition logic
  - Compares metrics against thresholds (e.g., TPS < 18.0)
- **Output**: List of matched patterns with weights and tags

#### Stage D: Mod Detection
- **Purpose**: Identify which mods from rules are installed
- **Function**: `_detect_mods()`
- **Key Principle**: **Detection ≠ Suspicion**
  - Just because a mod is installed doesn't make it a suspect
  - Suspects are determined later by pattern matching
- **Output**: Dictionary of detected mods with metadata

#### Stage E: Suspect Scoring (with Proper Gating)
- **Purpose**: Build list of suspects with confidence scores
- **Function**: `_build_suspects()`
- **Gating Levels**:
  1. **Pattern Weight Gate**: `total_pattern_weight >= MIN_PATTERN_WEIGHT (6)`
     - Prevents showing suspects when only minor issues exist
  2. **Tag Overlap Gate**: Mod tags must overlap with pattern tags
     - Ensures mod is relevant to observed symptoms
  3. **Confidence Gate**: `confidence >= MIN_SUSPECT_CONFIDENCE (55%)`
     - Requires sufficient evidence before reporting
- **Scoring Formula**:
  ```python
  base_confidence = mod_severity * 10          # 10-50
  tag_overlap_bonus = len(matching_tags) * 5   # 0-30
  pattern_bonus = min(30, total_pattern_weight) # 0-30
  confidence = min(100, sum of above)
  ```
- **Output**: Sorted list of suspects (highest confidence first)

#### Stage F: Entity Breakdown Analysis
- **Purpose**: Analyze entity types and attribute to mods
- **Functions**: `_analyze_entity_breakdown()`, `_build_entity_suspects()`
- **Key Fix**: Only creates entity suspects when entity patterns trigger
  ```python
  has_entity_pattern = any("entity" in p.get("id", "").lower() for p in matched_patterns)
  if not has_entity_pattern:
      return []  # Don't show entity suspects without entity pressure
  ```
- **Entity Pattern Matching**:
  - Uses regex to match entity types (e.g., `alexsmobs:*` → `^alexsmobs:.*$`)
  - Properly escapes special characters with `re.escape()`
  - Tracks percentage contribution (only shows mods contributing ≥10%)
- **Output**: Entity analysis with contributor breakdown

#### Stage G: Recommendation Builder
- **Purpose**: Build actionable recommendations
- **Function**: `_build_recommendations()`
- **Sources**:
  1. Mod-specific tweaks from top suspects
  2. Entity-specific tweaks from entity contributors
  3. Common recommendations based on pattern tags
- **Output**: List of up to 10 recommendations

#### Stage H: Discord Formatter
- **Purpose**: Format diagnosis for Discord display
- **Function**: `format_diagnosis_for_discord()`
- **Includes**:
  - Status badge (✅ OK, ⚠️ WARN, 🔴 BAD)
  - Performance metrics with color-coded emojis
  - Top suspects (only when gating conditions met)
  - Known issues for suspected mods
  - Missing data indicators
- **Output**: Formatted string ≤2000 characters

## Key Fixes

### 1. Entity Detection Fixed
**Problem**: Entity suspects showed even without entity pressure
**Solution**: Check for entity patterns before creating entity suspects
```python
has_entity_pattern = any("entity" in p.get("id", "").lower() for p in matched_patterns)
if not has_entity_pattern:
    return []  # Fixed: Don't show entity suspects
```

### 2. Mod Detection ≠ Suspicion
**Problem**: Mods became suspects just by being installed
**Solution**: Three-level gating in `_build_suspects()`
- Gate 1: Require `total_pattern_weight >= 6`
- Gate 2: Require tag overlap between mod and patterns
- Gate 3: Require `confidence >= 55%`

### 3. Improved Scoring
**Problem**: Weak scoring didn't properly combine signals
**Solution**: Enhanced scoring formula combining:
- Mod severity (base)
- Tag overlap (relevance)
- Pattern weight (problem severity)

### 4. Better Regex Escaping
**Problem**: Entity patterns like `iceandfire:*` failed to match
**Solution**: Use `re.escape()` before replacing `*` with `.*`
```python
regex_pattern = re.escape(pattern).replace(r"\*", ".*")
```

## Configuration

### Environment Variables
- `SPARK_RULES_URL`: URL to fetch rules.yml from (optional, defaults to local file)
- `SPARK_DEBUG=1`: Enable debug logging to see:
  - What was extracted from Spark JSON
  - Which patterns matched
  - Which mods were detected
  - Why suspects were or weren't created

### Thresholds (in rules.yml)
```yaml
thresholds:
  tps_warn: 18.0          # TPS below this triggers warnings
  tps_bad: 15.0           # TPS below this is critical
  mspt_warn: 50.0         # MSPT above this is concerning
  mspt_bad: 70.0          # MSPT above this is critical
  entities_warn: 1000     # Entity count warning threshold
  entities_bad: 1500      # Entity count critical threshold
  # ... more thresholds
```

### Pattern Weights
- Weight 5-6: Minor issues (e.g., `low_tps`)
- Weight 8-9: Significant issues (e.g., `bad_tps`, `severe_mspt`)
- Weight 10+: Critical issues (e.g., `severe_chunkgen_spikes`)

Total weight determines overall status:
- `< 8`: OK
- `8-14`: WARN
- `≥ 15`: BAD

## Usage

### Basic Usage
```python
from bot.utils.spark import analyze_spark_report, format_discord_report

# Analyze report
result = await analyze_spark_report("https://spark.lucko.me/abc123")

# Format for Discord
message = format_discord_report(result)
```

### With Debug Logging
```bash
export SPARK_DEBUG=1
python -m bot.main
```

Debug output will show:
```
[SPARK DEBUG] Parsing Spark JSON
[SPARK DEBUG] Detected 45 mods
[SPARK DEBUG] TPS: 17.5
[SPARK DEBUG] MSPT: 62.3
[SPARK DEBUG] Entities: 1250
[PATTERN_MATCHER DEBUG] Matched 2 patterns: ['low_tps', 'high_mspt']
[PATTERN_MATCHER DEBUG] Pattern weight: 11, tags: {'misc'}
[PATTERN_MATCHER DEBUG] Built 1 suspects
```

## Testing

All tests pass (41/41):
```bash
python -m pytest tests/test_pattern_matcher.py -v
```

Key test scenarios:
- Mod detection (exact match, pattern match, no match)
- Pattern evaluation (any/all conditions, thresholds)
- Suspect gating (tag overlap, minimum weight, minimum confidence)
- Entity detection (only with entity patterns)
- Discord formatting (truncation, healthy servers, issues)

## Backward Compatibility

The system maintains backward compatibility:
- `analyze_spark_report()` returns same structure
- `format_discord_report()` has same signature
- Legacy `_analyze_performance()` still works
- All existing bot imports continue to work

## Data Flow Example

1. **Input**: `https://spark.lucko.me/abc123`
2. **Stage A**: Fetch → Raw JSON
3. **Stage B**: Parse → Normalized data
   ```python
   {
     "tps": {"recent": 17.5},
     "tick": {"mspt": 62.3},
     "world": {"entities_total": 1250},
     "mods": {"create": "0.5.1", "mekanism": "10.3.9"}
   }
   ```
4. **Stage C**: Match patterns → `["low_tps", "high_mspt"]` (weight: 11)
5. **Stage D**: Detect mods → `{"create": {...}, "mekanism": {...}}`
6. **Stage E**: Score suspects →
   ```python
   [
     {
       "name": "Create",
       "confidence": 75,
       "reasons": ["Tags match symptoms: automation, ticking_block_entities"]
     }
   ]
   ```
7. **Stage F**: Entity analysis → No entity patterns, skip
8. **Stage G**: Build recommendations → Mod-specific tweaks
9. **Stage H**: Format for Discord → Final message

## Future Improvements

Potential enhancements:
1. Machine learning-based pattern weights
2. Historical data comparison
3. More granular entity analysis
4. Custom pattern rules per server
5. Integration with mod update notifications

## Troubleshooting

### No suspects shown despite issues
- Check pattern weight: May be < 6
- Check tag overlap: Mod tags may not match pattern tags
- Enable `SPARK_DEBUG=1` to see why suspects were filtered

### Entity suspects not showing
- Check if entity patterns matched
- Verify entity count exceeds thresholds
- Check entity type patterns in rules.yml match actual entity IDs

### Mods showing as suspects incorrectly
- Verify pattern weights are appropriate
- Check if tags are too broad
- Adjust MIN_SUSPECT_CONFIDENCE if needed
