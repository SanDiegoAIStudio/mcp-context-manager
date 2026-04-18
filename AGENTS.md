# MCP Context Manager Agent Instructions

Read `CLAUDE.md` first. This repo is a shell/Python CLI for optimizing MCP usage and reducing context load.

## Commands

```bash
./install.sh
mcm discover
mcm optimize
mcm status
```

## Rules

- Keep shell scripts portable for macOS/Linux.
- Do not break the `mcm` command surface without updating docs and install flow.
- Treat generated optimized MCP artifacts as user-environment changes; explain them clearly.
- Avoid adding dependencies unless they are genuinely necessary.

