#!/bin/bash

# MCM Installation Script

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCM_HOME="${MCM_HOME:-$HOME/.mcm}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 Installing MCP Context Manager (MCM)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check dependencies
echo "Checking dependencies..."

if ! command -v python3 &> /dev/null; then
    echo "✗ Python 3 is required but not installed"
    echo "  Install from: https://www.python.org/downloads/"
    exit 1
fi
echo "✓ Python 3"

if ! command -v git &> /dev/null; then
    echo "✗ Git is required but not installed"
    echo "  Install from: https://git-scm.com/downloads"
    exit 1
fi
echo "✓ Git"

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
python3 -m pip install --user requests >/dev/null 2>&1 || true
echo "✓ Python packages"

# Create MCM directories
echo ""
echo "Creating MCM directory structure..."
mkdir -p "$MCM_HOME"/{config,registry,converted,embeddings,analytics,cache,backups,logs}
mkdir -p "$MCM_HOME"/converted/skills
echo "✓ Directory structure created at $MCM_HOME"

# Create default config
if [[ ! -f "$MCM_HOME/config/mcm-config.json" ]]; then
    cat > "$MCM_HOME/config/mcm-config.json" <<'EOF'
{
  "version": "1.0.0",
  "strategy": "balanced",
  "confidence_threshold": 0.7,
  "max_tool_budget_percent": 40,
  "auto_unload_after_messages": 3,
  "pinned_mcps": []
}
EOF
    echo "✓ Created config"
fi

# Create credentials template
if [[ ! -f "$MCM_HOME/config/credentials.env" ]]; then
    cat > "$MCM_HOME/config/credentials.env" <<'EOF'
# MCP Context Manager - Credentials
# Fill in your API keys below

# Exa.ai (for better MCP discovery)
# Get key from: https://exa.ai
EXA_API_KEY=

# GitHub (for GitHub MCP)
# Get from: https://github.com/settings/tokens
GITHUB_TOKEN=

# Add other MCP credentials as needed
EOF
    echo "✓ Created credentials template"
fi

# Make scripts executable
chmod +x "$SCRIPT_DIR"/*.sh "$SCRIPT_DIR"/*.py 2>/dev/null || true

# Create symlink if possible
if [[ -w /usr/local/bin ]]; then
    ln -sf "$SCRIPT_DIR/main.sh" /usr/local/bin/mcm 2>/dev/null || true
    echo "✓ Created 'mcm' command"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ MCM Installation Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Next steps:"
echo "1. In Claude Code, type: /mcm discover"
echo "2. Follow the prompts to add your MCPs"
echo "3. Fill in credentials if needed"
echo ""
echo "For help: /mcm (in Claude Code)"
echo ""
