#!/bin/bash

# MCM (MCP Context Manager) - Installation Script
# This script sets up MCM for Claude Code

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCM_HOME="${MCM_HOME:-$HOME/.mcm}"
CLAUDE_DIR="$HOME/.claude"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'
BOLD='\033[1m'

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
echo -e "${GREEN}✓ Python 3${NC} ($(python3 --version))"

if ! command -v git &> /dev/null; then
    echo -e "${RED}✗ Git is required but not installed${NC}"
    echo "  Install from: https://git-scm.com/downloads"
    exit 1
fi
echo -e "${GREEN}✓ Git${NC}"

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
python3 -m pip install --user --quiet requests 2>/dev/null || {
    echo -e "${YELLOW}⚠ Could not install 'requests' library${NC}"
    echo "  You may need to install it manually: pip install requests"
}
echo -e "${GREEN}✓ Python packages${NC}"

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
    cat > "$MCM_HOME/config/mcm-config.json" <<'EOF'
{
  "version": "1.0.0",
  "strategy": "balanced",
  "confidence_threshold": 0.7,
  "max_tool_budget_percent": 40,
  "auto_unload_after_messages": 3,
  "pinned_mcps": [],
  "created_at": "'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'",
  "updated_at": "'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'"
}
EOF
    echo -e "${GREEN}✓ Created config${NC}"
else
    echo -e "${YELLOW}⚠ Config already exists (skipped)${NC}"
fi

# Create credentials template
if [[ ! -f "$MCM_HOME/config/credentials.env" ]]; then
    cat > "$MCM_HOME/config/credentials.env" <<'EOF'
# MCP Context Manager - Credentials
# Fill in your API keys below

# Exa.ai (for better MCP discovery)
# Get key from: https://exa.ai
EXA_API_KEY=

# GitHub (for GitHub MCP)
# Get token from: https://github.com/settings/tokens
# Needs scopes: repo, read:org
GITHUB_TOKEN=

# Add other MCP-specific credentials as needed
# Format: KEY=value (no spaces around =)

EOF
    echo -e "${GREEN}✓ Created credentials template${NC}"
else
    echo -e "${YELLOW}⚠ Credentials file already exists (skipped)${NC}"
fi

# Create example MCP list
cat > "$MCM_HOME/cache/mcp-list-example.txt" <<'EOF'
# Example MCP List
# You can paste this format when running /mcm discover

# Simple names
filesystem
github
postgres

# npm packages
@modelcontextprotocol/server-slack
@modelcontextprotocol/server-playwright

# GitHub URLs
https://github.com/modelcontextprotocol/servers

# Mixed formats work too!
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
echo "3. Wait for discovery to complete (2-5 minutes)"
echo "4. Add credentials if needed: ${CYAN}code $MCM_HOME/config/credentials.env${NC}"
echo "5. Validate: ${CYAN}/mcm validate${NC}"
echo ""
echo "For help: ${CYAN}/mcm help${NC} (in Claude Code)"
echo ""
echo -e "${YELLOW}Tip: Run ${CYAN}cat $MCM_HOME/cache/mcp-list-example.txt${YELLOW} to see example formats${NC}"
echo ""
