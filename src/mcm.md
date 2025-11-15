---
description: MCP Context Manager - Automated MCP discovery and optimization
---

Execute the MCP Context Manager command.

**Available Commands:**
- `/mcm discover` - Discover and optimize your MCPs (first-time setup)
- `/mcm status` - Show current MCP status and context usage
- `/mcm validate` - Validate all discovered MCPs
- `/mcm search <query>` - Search for tools by capability
- `/mcm reload <mcp>` - Reload a specific MCP
- `/mcm optimize` - Get optimization suggestions
- `/mcm stats` - View usage analytics
- `/mcm config` - Adjust MCM settings
- `/mcm help` - Show detailed help

**Instructions:**
1. Run the MCM main script with the provided subcommand and arguments
2. Use the Bash tool to execute: `~/.claude/scripts/mcm/main.sh [subcommand] [args...]`
3. Display the output to the user
4. If the command is `discover`, guide the user through the interactive process
5. If the command requires additional input, prompt the user appropriately

**Example Execution:**
For `/mcm discover`:
- Execute: `bash ~/.claude/scripts/mcm/main.sh discover`
- Follow any interactive prompts from the script
- Display results and next steps to the user

For `/mcm status`:
- Execute: `bash ~/.claude/scripts/mcm/main.sh status`
- Display the MCP status information

**Note:** The first time running `/mcm discover`, the system will:
1. Create the `~/.mcm/` directory structure
2. Prompt for MCP input (paste, file, or scan)
3. Discover and analyze each MCP
4. Convert to optimal formats
5. Save results to the registry

After setup, MCM works automatically in the background.
