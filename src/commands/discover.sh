#!/bin/bash

# MCM Discovery Script
# Handles interactive MCP discovery process

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCM_HOME="${MCM_HOME:-$HOME/.mcm}"
THIS_SCRIPT="$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")"

# Installed copies keep the engine beside this script. A clone keeps it in src/.
if [[ -f "$SCRIPT_DIR/mcm_engine.py" ]]; then
    ENGINE="$SCRIPT_DIR/mcm_engine.py"
elif [[ -f "$SCRIPT_DIR/../mcm_engine.py" ]]; then
    ENGINE="$SCRIPT_DIR/../mcm_engine.py"
else
    printf 'Error: mcm_engine.py was not found next to %s or one folder up.\n' "$THIS_SCRIPT" >&2
    exit 1
fi

# Colors
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
CYAN=$'\033[0;36m'
NC=$'\033[0m'
BOLD=$'\033[1m'

echo -e "${CYAN}🔍 MCP Context Manager - Discovery${NC}\n"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required but not installed."
    exit 1
fi

# Initialize MCM if needed
if [[ ! -d "$MCM_HOME" ]]; then
    echo "Initializing MCM for the first time..."
    mkdir -p "$MCM_HOME"/{config,registry,converted,embeddings,analytics,cache,backups,logs}
fi

mkdir -p "$MCM_HOME/cache"
MCP_INPUT_FILE="$MCM_HOME/cache/mcp-input-$$.txt"
trap 'rm -f "$MCP_INPUT_FILE"' EXIT

if [[ $# -gt 0 ]]; then
    printf '%s\n' "$@" > "$MCP_INPUT_FILE"
elif [ ! -t 0 ]; then
    cat > "$MCP_INPUT_FILE"
else
    echo "How would you like to provide your MCPs?"
    echo ""
    echo "1. Paste a list (names, URLs, or mixed)"
    echo "2. Point to a file"
    echo "3. Scan my Claude config automatically"
    echo ""
    read -p "Choose 1-3: " choice

    case $choice in
        1)
            echo ""
            echo "📋 Paste your MCP list below (press Ctrl+D when done):"
            echo ""
            cat > "$MCP_INPUT_FILE"
            ;;
        2)
            echo ""
            read -p "Path to file: " file_path
            if [[ ! -f "$file_path" ]]; then
                echo "Error: File not found: $file_path"
                exit 1
            fi
            cp "$file_path" "$MCP_INPUT_FILE"
            ;;
        3)
            python3 "$ENGINE" scan-config > "$MCP_INPUT_FILE"

            if [[ ! -s "$MCP_INPUT_FILE" ]]; then
                echo "No MCP servers found in ./.mcp.json or ~/.claude.json"
                exit 1
            fi

            echo "These names will be looked up on npm or GitHub:"
            while IFS= read -r line || [[ -n "${line:-}" ]]; do
                echo "  $line"
            done < "$MCP_INPUT_FILE"

            MCP_COUNT=$(wc -l < "$MCP_INPUT_FILE" | tr -d ' ')
            echo "Found $MCP_COUNT MCPs. Proceed with discovery? (y/n)"
            read -p "> " proceed
            if [[ "$proceed" != "y" ]]; then
                echo "Cancelled."
                exit 0
            fi
            ;;
        *)
            echo "Invalid choice"
            exit 1
            ;;
    esac
fi

has_name=0
while IFS= read -r line || [[ -n "${line:-}" ]]; do
    trimmed="${line#"${line%%[![:space:]]*}"}"
    if [[ -z "$trimmed" || "$trimmed" == \#* ]]; then
        continue
    fi
    has_name=1
    break
done < "$MCP_INPUT_FILE"

if [[ "$has_name" -eq 0 ]]; then
    echo "No MCP names given. Example: mcm discover @modelcontextprotocol/server-filesystem"
    exit 1
fi

echo ""
echo -e "${BOLD}🚀 Starting MCP discovery...${NC}"
echo ""

# Run discovery. 0: every name saved. 2: some saved and some not. Anything else: none.
discover_status=0
python3 "$ENGINE" discover "$MCP_INPUT_FILE" || discover_status=$?

if [[ "$discover_status" -eq 0 ]]; then
    echo ""
    echo -e "${GREEN}✅ Discovery complete!${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Review: cat $MCM_HOME/registry/index.json"
    echo "2. Validate: mcm validate"
    echo ""
elif [[ "$discover_status" -eq 2 ]]; then
    echo "Discovery finished with failures. See the lines marked ✗ above."
    echo ""
    echo "Next steps:"
    echo "1. Review: cat $MCM_HOME/registry/index.json"
    echo "2. Validate: mcm validate"
    echo ""
    exit 2
else
    echo "Discovery failed: no MCP could be read. See the errors above."
    exit 1
fi
