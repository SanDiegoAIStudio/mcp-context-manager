#!/bin/bash

# MCP Context Manager (MCM) - Main Entry Point
# This script orchestrates all MCM functionality

set -euo pipefail

MCM_HOME="${MCM_HOME:-$HOME/.mcm}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
CYAN=$'\033[0;36m'
NC=$'\033[0m' # No Color
BOLD=$'\033[1m'

# Helper functions
info() {
    echo -e "${CYAN}ℹ${NC}  $1"
}

success() {
    echo -e "${GREEN}✓${NC}  $1"
}

error() {
    echo -e "${RED}✗${NC}  $1" >&2
}

warning() {
    echo -e "${YELLOW}⚠${NC}  $1"
}

heading() {
    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}$1${NC}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Initialize MCM directory structure
init_mcm() {
    mkdir -p "$MCM_HOME"/{config,registry,converted,embeddings,analytics,cache,backups,logs}
    mkdir -p "$MCM_HOME"/converted/skills

    # Create default config if doesn't exist
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
    fi

    # Create preferences file
    if [[ ! -f "$MCM_HOME/config/preferences.json" ]]; then
        cat > "$MCM_HOME/config/preferences.json" <<EOF
{
  "analytics_enabled": true,
  "auto_optimize": true,
  "learning_enabled": true,
  "verbose_logging": false
}
EOF
    fi

    # Create credentials template
    if [[ ! -f "$MCM_HOME/config/credentials.env" ]]; then
        cat > "$MCM_HOME/config/credentials.env" <<EOF
# MCP Context Manager - Credentials
# Fill in your API keys and tokens below

# GitHub (for GitHub MCP)
# Get token from: https://github.com/settings/tokens
# Needs scopes: repo, read:org
GITHUB_TOKEN=

# Add MCP-specific credentials below:
# Format: KEY=value (no spaces around =)

EOF
    fi
}

# Route commands
case "${1:-help}" in
    discover)
        exec "$SCRIPT_DIR/discover.sh" "${@:2}"
        ;;
    inspect)
        exec python3 "$SCRIPT_DIR/mcm_engine.py" inspect "${@:2}"
        ;;
    status)
        exec "$SCRIPT_DIR/status.sh" "${@:2}"
        ;;
    validate)
        exec "$SCRIPT_DIR/validate.sh" "${@:2}"
        ;;
    help)
        cat <<EOF
${BOLD}MCP Context Manager (MCM)${NC}

Usage: mcm <command> [options]

${BOLD}Commands:${NC}
  discover        Discover and optimize MCPs (first-time setup)
  inspect <pkg>   Start a server outside the conversation and list its tools
  status          Show saved servers and inspected tool counts
  validate        List what MCM has saved
  help            Show this help message

${BOLD}Examples:${NC}
  mcm discover
  mcm status
  mcm validate
  mcm inspect @modelcontextprotocol/server-filesystem -- /tmp

${BOLD}Documentation:${NC}
  Full docs: cat ~/.claude/commands/mcm.md
  Or use /mcm in Claude Code for interactive help

${BOLD}Directories:${NC}
  Config:    $MCM_HOME/config/
  MCPs:      $MCM_HOME/converted/
  Logs:      $MCM_HOME/logs/

EOF
        ;;
    *)
        error "Unknown command: $1"
        echo "Run 'mcm help' for usage information"
        exit 1
        ;;
esac
