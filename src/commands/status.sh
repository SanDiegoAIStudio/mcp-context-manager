#!/bin/bash
# MCM Status - Show current MCM state

MCM_HOME="${MCM_HOME:-$HOME/.mcm}"

if [[ ! -d "$MCM_HOME" ]]; then
    echo "MCM not initialized. Run 'mcm discover' first."
    exit 1
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎯 MCM STATUS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Show discovered MCPs
if [[ -f "$MCM_HOME/registry/index.json" ]]; then
    MCP_COUNT=$(python3 -c "import json; f=open('$MCM_HOME/registry/index.json'); d=json.load(f); print(len(d.get('mcps', [])))")
    echo ""
    echo "Discovered MCPs: $MCP_COUNT"
    echo ""

    python3 -c "
import json
with open('$MCM_HOME/registry/index.json') as f:
    data = json.load(f)
for mcp in data.get('mcps', []):
    print(f\"  ✓ {mcp['name']:<20} {mcp['tool_count']:>3} tools → {mcp['format']}\")
"
else
    echo "No MCPs discovered yet."
    echo "Run 'mcm discover' to get started."
fi

echo ""
echo "Config: $MCM_HOME/config/mcm-config.json"
echo "Logs:   $MCM_HOME/logs/"
echo ""
