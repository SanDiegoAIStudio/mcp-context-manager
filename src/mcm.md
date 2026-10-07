---
description: MCP Context Manager - Automated MCP discovery and optimization
---

Execute the MCP Context Manager command.

**Available Commands:**
- `/mcm discover` - Look up MCP servers by npm package or GitHub URL
- `/mcm inspect <package>` - Start a server outside the conversation and list its tools
- `/mcm status` - Show saved servers and inspected tool counts
- `/mcm validate` - List what MCM has saved
- `/mcm help` - Show detailed help

**Instructions:**
- For `/mcm discover`, ask the user for MCP names, npm packages or GitHub URLs (or use the ones they already gave), then run `bash ~/.claude/scripts/mcm/main.sh discover <name> [<name> ...]` and show the output.
- For `/mcm inspect <package>`, before running it, tell the user that it runs that package's own code on their machine, the same as installing it, and ask them to confirm. Only after they say yes in this conversation run `bash ~/.claude/scripts/mcm/main.sh inspect <package> --yes`, adding ` -- <server args>` when the server needs arguments (for example a folder for the filesystem server). Never pass --yes without that yes.
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
