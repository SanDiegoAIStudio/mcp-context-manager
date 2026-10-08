#!/bin/bash

# MCM (MCP Context Manager) - Installation Script
# This script sets up MCM for Claude Code

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCM_HOME="${MCM_HOME:-$HOME/.mcm}"
CLAUDE_DIR="$HOME/.claude"

# Colors
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
CYAN=$'\033[0;36m'
RED=$'\033[0;31m'
NC=$'\033[0m'
BOLD=$'\033[1m'

echo -e "${CYAN}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  MCP Context Manager (MCM) - Installation"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${NC}"

# Check dependencies
echo "Checking dependencies..."

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 is required but not installed${NC}"
    echo "  Install from: https://www.python.org/downloads/"
    exit 1
fi

py_version_line="$(python3 --version 2>&1 || true)"
py_version="${py_version_line#Python }"
py_version="${py_version%%[[:space:]]*}"
py_major="${py_version%%.*}"
py_rest="${py_version#*.}"
py_minor="${py_rest%%.*}"
py_ok=0
if [[ "$py_major" =~ ^[0-9]+$ && "$py_minor" =~ ^[0-9]+$ ]]; then
    if [[ "$py_major" -gt 3 || ( "$py_major" -eq 3 && "$py_minor" -ge 9 ) ]]; then
        py_ok=1
    fi
fi
if [[ "$py_ok" -ne 1 ]]; then
    echo -e "${RED}✗ Python 3.9 or newer is required (found ${py_version})${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python 3${NC} ($(python3 --version))"

if ! command -v git &> /dev/null; then
    echo -e "${RED}✗ Git is required but not installed${NC}"
    echo "  Install from: https://git-scm.com/downloads"
    exit 1
fi
echo -e "${GREEN}✓ Git${NC}"

echo ""
echo -e "${GREEN}✓ Python standard library only, nothing to install${NC}"

# Create Claude Code directories
echo ""
echo "Setting up Claude Code integration..."
mkdir -p "$CLAUDE_DIR/commands"
mkdir -p "$CLAUDE_DIR/scripts/mcm"

# Copy files to Claude directories
cp "$SCRIPT_DIR/src/mcm.md" "$CLAUDE_DIR/commands/"
cp "$SCRIPT_DIR/src/mcm_engine.py" "$CLAUDE_DIR/scripts/mcm/"
cp "$SCRIPT_DIR/src/commands/"*.sh "$CLAUDE_DIR/scripts/mcm/"

# Make scripts executable
chmod +x "$CLAUDE_DIR/scripts/mcm/"*.sh
chmod +x "$CLAUDE_DIR/scripts/mcm/"*.py

echo -e "${GREEN}✓ Claude Code integration${NC}"

# Create MCM directories
echo ""
echo "Creating MCM directory structure..."
mkdir -p "$MCM_HOME"/{config,registry,converted,embeddings,analytics,cache,backups,logs}
mkdir -p "$MCM_HOME/converted/skills"
echo -e "${GREEN}✓ Directory structure${NC} ($MCM_HOME)"

# Create default config
if [[ ! -f "$MCM_HOME/config/mcm-config.json" ]]; then
    cat > "$MCM_HOME/config/mcm-config.json" <<EOF
{
  "version": "1.0.0",
  "strategy": "balanced",
  "confidence_threshold": 0.7,
  "max_tool_budget_percent": 40,
  "auto_unload_after_messages": 3,
  "pinned_mcps": [],
  "created_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "updated_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EOF
    echo -e "${GREEN}✓ Created config${NC}"
else
    echo -e "${YELLOW}⚠ Config already exists (skipped)${NC}"
fi

# Create example MCP list
cat > "$MCM_HOME/cache/mcp-list-example.txt" <<'EOF'
# Example MCP list
# Paste lines like these when you run /mcm discover.
# Use full npm package names. A plain name is looked up on npm exactly as written.

# npm packages
@modelcontextprotocol/server-filesystem
@modelcontextprotocol/server-memory
@playwright/mcp

# GitHub repository URLs
https://github.com/modelcontextprotocol/servers
EOF

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}✅ MCM Installation Complete!${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BOLD}Next steps:${NC}"
echo ""
echo "1. In Claude Code, type: ${CYAN}/mcm discover${NC}"
echo "2. Paste your MCP list (see example: $MCM_HOME/cache/mcp-list-example.txt)"
echo "3. Wait for discovery to finish (a few seconds per name)"
echo "4. Validate: ${CYAN}/mcm validate${NC}"
echo ""
echo "For help: ${CYAN}/mcm help${NC} (in Claude Code)"
echo ""
echo -e "${YELLOW}Tip: Run ${CYAN}cat $MCM_HOME/cache/mcp-list-example.txt${YELLOW} to see example formats${NC}"
echo ""
