#!/bin/bash

# MCM Discovery Script
# Handles interactive MCP discovery process

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCM_HOME="${MCM_HOME:-$HOME/.mcm}"
ENGINE="$SCRIPT_DIR/mcm_engine.py"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

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

echo "How would you like to provide your MCPs?"
echo ""
echo "1. Paste a list (names, URLs, or mixed)"
echo "2. Point to a file"
echo "3. Scan my Claude config automatically"
echo ""
read -p "Choose 1-3: " choice

MCP_INPUT_FILE="$MCM_HOME/cache/mcp-input-$$.txt"

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
        CLAUDE_CONFIG="$HOME/.config/claude/mcp_config.json"
        if [[ ! -f "$CLAUDE_CONFIG" ]]; then
            echo "Error: Claude config not found at $CLAUDE_CONFIG"
            exit 1
        fi

        echo "Scanning $CLAUDE_CONFIG..."
        # Extract MCP names from config
        python3 -c "
import json
with open('$CLAUDE_CONFIG') as f:
    config = json.load(f)
mcps = config.get('mcpServers', {}).keys()
for mcp in mcps:
    print(mcp)
" > "$MCP_INPUT_FILE"

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

echo ""
echo -e "${BOLD}🚀 Starting MCP discovery...${NC}"
echo ""

# Run discovery
python3 "$ENGINE" discover "$MCP_INPUT_FILE"

# Clean up
rm -f "$MCP_INPUT_FILE"

echo ""
echo -e "${GREEN}✅ Discovery complete!${NC}"
echo ""
echo "Next steps:"
echo "1. Review: cat $MCM_HOME/registry/index.json"
echo "2. Configure credentials: edit $MCM_HOME/config/credentials.env"
echo "3. Validate: mcm validate"
echo ""
