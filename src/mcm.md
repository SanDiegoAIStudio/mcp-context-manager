---
description: MCP Context Manager - Automated MCP discovery and optimization
---

Execute the MCP Context Manager command.

**Available Commands:**
- `/mcm discover` - Discover and optimize your MCPs (first-time setup)
- `/mcm status` - Show current MCP status and context usage
- `/mcm validate` - Validate all discovered MCPs
- `/mcm help` - Show detailed help

**Instructions:**
- For `/mcm discover`, ask the user for MCP names, npm packages or GitHub URLs (or use the ones they already gave), then run `bash ~/.claude/scripts/mcm/main.sh discover <name> [<name> ...]` and show the output.
- For `/mcm status`, `/mcm validate` and `/mcm help`, run `bash ~/.claude/scripts/mcm/main.sh <command>` and show the output.

**Example Execution:**
For `/mcm discover`:
- Ask the user for MCP names, npm packages or GitHub URLs when they have not already given them
- Execute: `bash ~/.claude/scripts/mcm/main.sh discover <name> [<name> ...]`
- Display the output to the user

For `/mcm status`, `/mcm validate`, and `/mcm help`:
- Execute: `bash ~/.claude/scripts/mcm/main.sh <command>`
- Display the output to the user

**Note:** The first time running `/mcm discover`, the system will:
1. Create the `~/.mcm/` directory structure
2. Discover and analyze each named MCP
3. Convert to optimal formats
4. Save results to the registry
