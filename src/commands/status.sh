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
    echo ""
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

mcps = data.get("mcps", [])
print("Discovered MCPs: %d" % len(mcps))
print("")

inspected = 0
tool_total = 0
token_total = 0
for mcp in mcps:
    name = mcp.get("name", "")
    if mcp.get("inspected"):
        tool_count = mcp.get("tool_count", 0)
        context_tokens = mcp.get("context_tokens", 0)
        inspected += 1
        tool_total += tool_count
        token_total += context_tokens
        print(f"  ✓ {name:<40} {tool_count:>3} tools  ~{context_tokens} tokens")
    else:
        print(f"  · {name:<40} not inspected")

if inspected == 0:
    print("No server inspected yet. Run: mcm inspect <package>")
else:
    print(
        "Inspected %d of %d: %d tools, about %d tokens of tool definitions."
        % (inspected, len(mcps), tool_total, token_total)
    )
PY
    if [[ $? -ne 0 ]]; then
        exit 1
    fi
else
    echo "No MCPs discovered yet."
    echo "Run 'mcm discover' to get started."
fi

echo ""
echo "Config: $MCM_HOME/config/mcm-config.json"
echo "Logs:   $MCM_HOME/logs/"
echo ""
