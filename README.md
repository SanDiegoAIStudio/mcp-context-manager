# MCP Context Manager (MCM)

**Experimental MCP discovery, inspection, and offline context organization for Claude Code**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## 🎯 The Problem

Model Context Protocol (MCP) servers extend Claude Code with powerful tools — but as the MCP ecosystem grows, **users lose visibility and control**.

Once you enable multiple MCPs, it becomes difficult to answer basic questions:

* What tools do I actually have?
* Which MCPs are worth keeping enabled?
* How complex is this MCP before I turn it on?
* Why does my workflow feel cluttered or opaque?

MCP tool schemas can be large, verbose, and hard to reason about, and today they are mostly **all-or-nothing** from the user’s perspective.

---

## 🧠 What MCM Is

**MCP Context Manager (MCM)** is an **experimental utility for Claude Code** that helps you:

* Discover MCP servers from names, packages, or URLs
* Inspect and summarize MCP tools *outside your active conversation*
* Organize MCP metadata locally for comparison and reference
* Interact with MCP information via `/mcm` slash commands

MCM shifts MCP understanding **out of the prompt and into a local workspace**, so you can reason about tools intentionally instead of blindly enabling them.

---

## 🚫 What MCM Is Not

To be explicit:

* ❌ It does **not** dynamically load or unload MCP tools
* ❌ It does **not** change Claude’s internal MCP token usage
* ❌ It does **not** intercept, rewrite, or proxy MCP servers
* ❌ It does **not** enforce on-demand tool injection

Those capabilities would require **host-level support in Claude Code**, not local scripts.

MCM is an **inspection and organization layer**, not a runtime optimizer.

---

## ✨ What MCM Actually Does

### One-time setup

* Installs a `/mcm` slash command into Claude Code
* Creates a local workspace at `~/.mcm`
* Enables Claude Code to run MCP analysis scripts locally

### Ongoing use

* MCPs are **discovered and indexed**, not loaded as tools
* Tool schemas are summarized and stored locally
* You can search, review, and compare MCP capabilities
* Large MCP definitions don’t need to live in your prompt history

Think of MCM as an **MCP audit and exploration toolkit**.

---

## 🧪 Why This Is Useful

As MCP servers grow in number and complexity, blindly enabling them becomes risky.

MCM helps you:

* Decide *which MCPs are worth enabling*
* Understand *what tools exist before using them*
* Keep MCP exploration **out of your main working context**
* Avoid trial-and-error with unfamiliar or oversized MCPs

Even without runtime control, this improves **clarity, confidence, and workflow hygiene**.

---

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/SanDiegoAIStudio/mcp-context-manager.git
cd mcp-context-manager
./install.sh
```

The installer copies the `/mcm` slash command to `~/.claude/commands/mcm.md`, the scripts to `~/.claude/scripts/mcm/`, and creates the workspace at `~/.mcm/`.

### Discover MCPs

In **Claude Code**, type:

```
/mcm discover
```

Paste MCP names, packages, or URLs (any format).
MCM will analyze them and store results locally.

From a terminal:

```bash
bash ~/.claude/scripts/mcm/main.sh discover @modelcontextprotocol/server-filesystem
```

Results land in `~/.mcm/registry/index.json`. `bash ~/.claude/scripts/mcm/main.sh status` lists them.

## Inspect a server's tools

- `mcm inspect <package>` starts the server with `npx -y` in a temporary folder, asks it for its tools, and stops it after 30 seconds at most.
- The stop reaches the server and the processes it started, unless one of them starts its own session; such a process can keep running after inspect returns.
- It prints "This runs <package>'s own code on your machine, the same as installing it." and asks before starting, unless you pass --yes.
- It passes only PATH, HOME, USER, LANG and TMPDIR from your environment.
- It saves tool names, descriptions cut to 200 characters and schema sizes.
- Status and validate show real counts only for inspected servers and "not inspected" for the rest.
- The token figure is the tool definitions' characters divided by 4.
- If a first run times out while npx is still downloading the package, run it again.

```bash
bash ~/.claude/scripts/mcm/main.sh inspect @modelcontextprotocol/server-filesystem -- /tmp
```

---

## 📊 How It Works (High Level)

1. `/mcm` commands invoke local shell scripts
2. Scripts call a Python analysis engine
3. MCP metadata is fetched from npm and GitHub
4. Package and repository details are written to `~/.mcm/`
5. Claude references structured summaries instead of raw schemas

This moves MCP reasoning from **prompt-time → offline-time**.

---

## What MCM sends

* discover sends each name you give it to registry.npmjs.org. For a package whose repository is on GitHub, it sends the owner/repo to api.github.com (with GITHUB_TOKEN if you set it) and reads the repository's package.json from raw.githubusercontent.com.
* inspect sends nothing to MCM's lookups, and npx downloads the package from the npm registry.
* MCM uses no search service. The only key it reads is GITHUB_TOKEN, and only for api.github.com.
* Nothing else leaves your machine: no file contents, no paths and no config. Each request is printed as it happens.
* A name must look like an npm package, a GitHub repository URL or a plain name; anything else is skipped and nothing is sent for it.
* A redirect to another host is refused, so a token or key never follows one.

---

## Known limits

- discover saves package and repository details only. Real tool counts come from mcm inspect, which runs the server.

---

## ⚠️ Project Status

**Early-stage / experimental**

* Command routing may require refinement
* Heuristics are evolving
* Output formats may change
* Not production-hardened

This project is intended as a **developer utility and research sandbox**.

---

## 🧭 Future Direction (Not Implemented)

These are ideas, not current features:

* Semantic search across MCP tools
* Usage-based MCP recommendations
* Improved schema parsing (AST-based)
* Host-integrated tool loading (if supported in the future)

---

## Tests

```bash
python3 -m unittest discover -s tests -v
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.




