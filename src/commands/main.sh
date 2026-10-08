#!/bin/bash

# MCP Context Manager (MCM) - Main Entry Point
# This script orchestrates all MCM functionality

set -euo pipefail

MCM_HOME="${MCM_HOME:-$HOME/.mcm}"

# Follow symbolic links so sibling scripts resolve next to this file.
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
    LINK_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    TARGET="$(readlink "$SOURCE")"
    case "$TARGET" in
        /*)
            SOURCE="$TARGET"
            ;;
        *)
            SOURCE="$LINK_DIR/$TARGET"
            ;;
    esac
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
THIS_SCRIPT="$SCRIPT_DIR/$(basename "$SOURCE")"

# Installed copies keep the engine beside this script. A clone keeps it in src/.
if [[ -f "$SCRIPT_DIR/mcm_engine.py" ]]; then
    MCM_ENGINE="$SCRIPT_DIR/mcm_engine.py"
elif [[ -f "$SCRIPT_DIR/../mcm_engine.py" ]]; then
    MCM_ENGINE="$SCRIPT_DIR/../mcm_engine.py"
else
    printf 'Error: mcm_engine.py was not found next to %s or one folder up.\n' "$THIS_SCRIPT" >&2
    exit 1
fi

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

# Route commands
case "${1:-help}" in
    discover)
        exec "$SCRIPT_DIR/discover.sh" "${@:2}"
        ;;
    inspect)
        exec python3 "$MCM_ENGINE" inspect "${@:2}"
        ;;
    status)
        exec "$SCRIPT_DIR/status.sh" "${@:2}"
        ;;
    validate)
        exec "$SCRIPT_DIR/validate.sh" "${@:2}"
        ;;
    -h|--help|help)
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
