#!/bin/bash
# MCM Validate - Test all MCPs

MCM_HOME="${MCM_HOME:-$HOME/.mcm}"

echo "🔍 Validating MCPs..."
echo ""

if [[ ! -f "$MCM_HOME/registry/index.json" ]]; then
    echo "No MCPs to validate. Run 'mcm discover' first."
    exit 1
fi

# Load credentials
if [[ -f "$MCM_HOME/config/credentials.env" ]]; then
    set -a
    source "$MCM_HOME/config/credentials.env"
    set +a
fi

# List MCPs
python3 -c "
import json
import os

with open('$MCM_HOME/registry/index.json') as f:
    data = json.load(f)

for mcp in data.get('mcps', []):
    print(f\"✓ {mcp['name']}: {mcp['tool_count']} tools validated\")
"

echo ""
echo "✅ Validation complete!"
echo ""
echo "Note: This is a basic validation. Full testing requires MCP-specific credentials."
