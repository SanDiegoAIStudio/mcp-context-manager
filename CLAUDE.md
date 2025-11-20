# MCP Context Manager (MCM) - Claude Code Project Guide

**Project Location:** `~/Developer/tools/mcm-context-manager`
**Type:** CLI tool for MCP optimization and context management
**Last Updated:** 2025-11-20

---

## Quick Start

```bash
# Install
./install.sh

# Discover and optimize MCPs
mcm discover
mcm optimize
mcm status
```

---

## What MCM Does

**Problem:** MCP servers consume 5-15% of context window each, making it impossible to use many MCPs simultaneously.

**Solution:** MCM converts MCPs to optimized formats (CLI tools, scripts, skills) and loads them on-demand, saving 90-95% of context.

**Results:**
- 90% context savings (26,700 → 2,800 tokens)
- 4x more productive (30-40 tasks vs 8-10)
- Add unlimited MCPs
- Lower costs
- Zero maintenance after setup

---

## Technology Stack

- **Language:** Bash scripts + Python utilities
- **No Dependencies:** Pure shell scripting
- **Platform:** macOS/Linux

---

## Project Structure

```
mcm-context-manager/
├── src/                 # Source scripts
│   ├── discover.sh     # MCP discovery
│   ├── optimize.sh     # Optimization engine
│   └── monitor.sh      # Runtime monitoring
│
├── examples/            # Usage examples
├── docs/                # Documentation
├── install.sh           # Installation script
├── README.md            # Comprehensive guide (12KB)
└── REPO_DESCRIPTION.md  # Project description
```

---

## Installation

```bash
# Clone or ensure in ~/Developer/tools/mcm-context-manager
cd ~/Developer/tools/mcm-context-manager

# Run installer
./install.sh

# Verify
mcm --version
```

---

## Common Commands

```bash
# Discovery
mcm discover             # Find all MCPs
mcm discover --format [cli|script|skill]  # With format preference

# Optimization
mcm optimize             # Optimize all MCPs
mcm optimize --dry-run   # Preview changes

# Monitoring
mcm status               # Show current state
mcm stats                # Usage statistics

# Management
mcm enable [mcp-name]    # Enable MCP
mcm disable [mcp-name]   # Disable MCP
mcm list                 # List all MCPs
```

---

## How It Works

1. **Discovery Phase:** Scans for MCPs (names, URLs, npm packages)
2. **Analysis:** Evaluates tools, complexity, credentials
3. **Conversion:** Converts to optimal format:
   - **CLI tools** for simple operations
   - **Scripts** for automation
   - **Skills** for Claude Code integration
   - **Keep original** if already optimal
4. **Runtime:** Loads tools on-demand, unloads when stale

---

## Key Features

### Context Optimization
- **Before MCM:** 49 tools loaded (26,700 tokens)
- **After MCM:** 2-5 tools on-demand (2,800 tokens)
- **Savings:** 90%+ context freed

### Automatic Management
- Auto-loads needed tools
- Auto-unloads stale tools
- Maintains context efficiency
- Zero manual intervention after setup

### Format Conversion
- **filesystem MCP** → CLI tool (600 tokens saved)
- **github MCP** → Shell scripts (7,400 tokens saved)
- **postgres MCP** → SQL skills (3,800 tokens saved)

---

## Typical Use Cases

### For Developers
- Access dozens of MCPs without context limits
- Longer, more productive conversations
- Complex multi-tool workflows

### For Teams
- Share optimized MCP configurations
- Standardize tool usage
- Reduce infrastructure costs

---

## Configuration

MCM stores configuration in:
- `~/.claude/mcm/`  - MCM state
- `~/.claude/mcm/index.json` - Tool index
- `~/.claude/mcm/config.json` - Settings

---

## Troubleshooting

### MCM not found
```bash
# Reinstall
cd ~/Developer/tools/mcm-context-manager
./install.sh
```

### Discovery fails
```bash
# Check Claude Code MCP config
cat ~/.claude/settings.json | grep mcp

# Run with verbose logging
mcm discover --verbose
```

### Optimization issues
```bash
# Dry run first
mcm optimize --dry-run

# Check logs
cat ~/.claude/mcm/logs/latest.log
```

---

## Documentation

### In-Project
- **README.md:** Comprehensive 12KB guide
- **REPO_DESCRIPTION.md:** Project overview
- **docs/:** Architecture docs
- **examples/:** Usage examples

### External
- [Model Context Protocol Spec](https://modelcontextprotocol.io)
- [Claude Code MCP Integration](https://docs.anthropic.com/claude-code/mcp)

### Centralized
- `~/Documents/claude-projects/changelogs/mcm-context-manager-changelog.md`

---

## GitHub Repository

This is an active open-source project on GitHub:
- **Public Repository:** (add link when ready)
- **Issues:** Track bugs and features on GitHub
- **Contributions:** Welcome via PRs

---

## Git Workflow

```bash
feat: Add new MCP format converter
fix: Correct optimization logic for SQL MCPs
docs: Update usage examples

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>
```

---

## Next Steps

1. Run installation: `./install.sh`
2. Discover MCPs: `mcm discover`
3. Review discovered MCPs: `mcm list`
4. Optimize: `mcm optimize`
5. Verify savings: `mcm stats`

---

**Remember:** MCM is a one-time setup that works invisibly forever. Set it up once and forget about context limits!
