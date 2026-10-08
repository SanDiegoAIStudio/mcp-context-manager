#!/bin/bash
# MCM Validate - Test all MCPs

MCM_HOME="${MCM_HOME:-$HOME/.mcm}"

echo "🔍 Validating MCPs..."
echo ""

if [[ ! -f "$MCM_HOME/registry/index.json" ]]; then
    echo "No MCPs to validate. Run 'mcm discover' first."
    exit 1
fi

python3 - "$MCM_HOME/registry/index.json" <<'PY'
import json
import sys

with open(sys.argv[1]) as handle:
    data = json.load(handle)

for mcp in data.get("mcps", []):
    name = mcp.get("name", "")
    if mcp.get("inspected"):
        print("✓ %s: inspected, %s tools" % (name, mcp.get("tool_count", 0)))
    else:
        print("· %s: not inspected (run: mcm inspect %s)" % (name, name))
PY

echo ""
echo "validate lists what MCM has saved. It does not start servers; mcm inspect does."
