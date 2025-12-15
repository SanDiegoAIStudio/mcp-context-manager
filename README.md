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
git clone https://github.com/Lucface/mcp-context-manager.git
cd mcp-context-manager
./install.sh
```

### Discover MCPs

In **Claude Code**, type:

```
/mcm discover
```

Paste MCP names, packages, or URLs (any format).
MCM will analyze them and store results locally.

---

## 📊 How It Works (High Level)

1. `/mcm` commands invoke local shell scripts
2. Scripts call a Python analysis engine
3. MCP metadata is fetched from GitHub, npm, or Exa.ai (if configured)
4. Tool summaries and indexes are written to `~/.mcm/`
5. Claude references structured summaries instead of raw schemas

This moves MCP reasoning from **prompt-time → offline-time**.

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

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.




