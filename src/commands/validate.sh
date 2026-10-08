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

path = sys.argv[1]
try:
    with open(path) as handle:
        data = json.load(handle)
except json.JSONDecodeError:
    print(
        "The registry index is not valid JSON: %s. Move it aside and run discover again."
        % path
    )
    sys.exit(1)

for mcp in data.get("mcps", []):
    name = mcp.get("name", "")
    if mcp.get("inspected"):
        print("✓ %s: inspected, %s tools" % (name, mcp.get("tool_count", 0)))
    else:
        print("· %s: not inspected (run: mcm inspect %s)" % (name, name))
PY
if [[ $? -ne 0 ]]; then
    exit 1
fi

echo ""
echo "validate lists what MCM has saved. It does not start servers; mcm inspect does."
