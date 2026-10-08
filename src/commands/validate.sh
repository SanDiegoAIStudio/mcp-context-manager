#!/bin/bash
# MCM Validate - Test all MCPs

set -euo pipefail

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

def as_count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return value


def invalid(path):
    print(
        "The registry index is not valid JSON: %s. Move it aside and run discover again."
        % path
    )
    sys.exit(1)


path = sys.argv[1]
try:
    with open(path) as handle:
        data = json.load(handle)
except json.JSONDecodeError:
    invalid(path)

if not isinstance(data, dict) or not isinstance(data.get("mcps", []), list):
    invalid(path)

for mcp in data.get("mcps", []):
    if not isinstance(mcp, dict):
        continue
    name = mcp.get("name", "")
    if mcp.get("inspected"):
        print("✓ %s: inspected, %s tools" % (name, as_count(mcp.get("tool_count", 0))))
    else:
        print("· %s: not inspected (run: mcm inspect %s)" % (name, name))
PY

echo ""
echo "validate lists what MCM has saved. It does not start servers; mcm inspect does."
