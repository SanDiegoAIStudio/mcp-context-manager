# Code Review — mcp-context-manager

**Repo:** mcp-context-manager (tier 2) · **Date:** 2026-06-16

> Findings surfaced by review; critical/high are adversarially verified in the Verification section below.

This report was produced by a 9-dimension review pass. Near-duplicate findings (notably the hardcoded `EXA_API_KEY` and the bare-`except` clauses, each reported by multiple reviewers) have been consolidated into single canonical entries with all referenced locations preserved.

## Summary

| Severity | Count |
|----------|-------|
| Critical | 4 |
| High | 19 |
| Medium | 30 |
| Low | 10 |
| **Total** | **63** |

Severity counts are deduplicated (the raw review emitted 6 separate Critical entries for the same `EXA_API_KEY` leak and 1 Low/1 Medium restatements of it — all collapsed into one Critical here).

---

## Critical

**Hardcoded API key exposed in source code**
`src/mcm_engine.py:21`
`EXA_API_KEY` is hardcoded with a default fallback value (`REDACTED`). A real, active key committed to the repo is exposed in source and git history; anyone with repo access can make requests on the legitimate account. Reported independently by 6 reviewers (plus 2 lower-severity restatements) — treat as the headline issue.
*Fix:* Change line 21 to `EXA_API_KEY = os.getenv("EXA_API_KEY", "")`. Fail safely with a clear error/warning when the key is missing rather than falling back to a leaked credential. **Rotate the key immediately** — assume it is compromised since it is in history.

**Bare `except:` clauses catch all exceptions including `SystemExit`/`KeyboardInterrupt`**
`src/mcm_engine.py:175, 311`
The bare `except:` in `discover_from_github()` (175, fetching `package.json`) and `analyze_mcp_tools()` (311, tool extraction loop) swallow every exception — network errors, JSON decode failures, and also `KeyboardInterrupt`/`SystemExit`/`MemoryError`. This masks real failures, makes debugging impossible, and prevents clean interruption. Reported by 8 reviewers.
*Fix:* Replace with specific types, e.g. `except (requests.RequestException, json.JSONDecodeError) as e:`, and log the actual error. Let `KeyboardInterrupt`/`SystemExit` propagate.

**All HTTP requests lack timeout configuration**
`src/mcm_engine.py:158, 167, 173, 203, 261, 295`
Every `requests.get()`/`requests.post()` call lacks a `timeout`. A slow/unresponsive GitHub, npm, or Exa.ai endpoint can hang discovery indefinitely. Affects `discover_from_github()`, `discover_from_npm()`, `discover_via_search()`, and `analyze_mcp_tools()`.
*Fix:* Add `timeout=10` (gets) / `timeout=15` (posts) to all calls and handle `requests.Timeout`.

**Untrusted data used in URL construction (path traversal / SSRF)**
`src/mcm_engine.py:151, 165, 201, 293`
User-controlled identifiers from `parse_mcp_input()` are interpolated directly into API URLs without validation, e.g. `f"https://api.github.com/repos/{repo_path}"` where `repo_path` is derived by splitting raw user input on `github.com/`. A crafted input can inject path segments (e.g. `../../../...`) into the API path; npm package names are likewise unvalidated before `f"https://registry.npmjs.org/{package_name}"`.
*Fix:* Validate identifiers against strict allowlists — GitHub: `^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$`; npm: official naming rules (alphanumeric/dash/underscore, scoped format). URL-encode with `urllib.parse.quote()` where flexibility is needed.

---

## High

**Unchecked chained dict access on npm response**
`src/mcm_engine.py:208-209` (also 225)
`discover_from_npm()` directly indexes `npm_data["dist-tags"]["latest"]` and `npm_data["versions"][latest_version]` (and `npm_data["name"]`). A malformed/changed/MITM'd registry response raises `KeyError`. `latest_version` is also not validated as a string before being used as a key.
*Fix:* `latest_version = npm_data.get("dist-tags", {}).get("latest")`; verify it before indexing `npm_data.get("versions", {}).get(latest_version)`.

**Unchecked dict access on GitHub repo metadata**
`src/mcm_engine.py:182-184`
Direct access to `repo_data["name"]` / `repo_data["html_url"]` without validation; an unexpected/incomplete API response raises `KeyError`.
*Fix:* `repo_data.get("name", "unknown")`, `repo_data.get("html_url", "")` for graceful degradation.

**`response.json()` results assumed to be dicts**
`src/mcm_engine.py:162, 207, 265`
GitHub/npm/Exa.ai `.json()` results are used as dicts without type validation. A list/None/other type yields uninformative downstream errors.
*Fix:* Validate `isinstance(data, dict)` after parsing, or model the responses with TypedDict/Pydantic.

**`.json()` calls not wrapped for `JSONDecodeError`**
`src/mcm_engine.py:162, 169, 174, 207, 265, 297`
Non-JSON or non-200 bodies cause `json.JSONDecodeError` and crash discovery. Line 174's conditional `.json()` also depends on a block whose exceptions are swallowed.
*Fix:* Wrap each `.json()` in `try/except json.JSONDecodeError` returning `None` with logging.

**Unsafe index read in `save_metadata()` (corrupt index → `KeyError`)**
`src/mcm_engine.py:387-388`
`existing = [m for m in index["mcps"] if m["name"] != metadata.name]` assumes `index["mcps"]` exists and every item is a dict with a `name` key. A corrupted/partially-written index (or non-dict entries) raises `KeyError`/`TypeError`. The default-structure guard at 384 only covers a missing file, not a malformed one.
*Fix:* `existing = [m for m in index.get("mcps", []) if isinstance(m, dict) and m.get("name") != metadata.name]`, and wrap the `json.load` in `try/except`.

**Bare/unparameterized `Dict` and `List` type hints**
`src/mcm_engine.py:24-37, 30, 35, 98, 130, 148, 198, 241, 277, 316, 327, 340, 356`
`MCPMetadata.tools` (`List[Dict]`), `MCPMetadata.credentials_needed` (`List[Dict]`), and many function params (`mcp_info: Dict`) use bare generics, defeating static type checking of keys/values.
*Fix:* Parameterize (`List[Dict[str, Any]]`, `Dict[str, str]`) or, better, introduce `Tool`/`Credential` dataclasses (or TypedDicts).

**Tool dict operations assume dict items**
`src/mcm_engine.py:321, 336, 344`
Calls like `tool.get("parameters", [])` over `tools` assume every item is a dict; a non-dict item raises `AttributeError`.
*Fix:* Guard with `if isinstance(tool, dict)` or validate the list at entry.

**N+1 index reads in `save_metadata()` (O(n²) discovery I/O)**
`src/mcm_engine.py:380-400` (filter at 387)
Each of N discoveries reads the entire index, does an O(n) filter, then rewrites — O(n²) over a batch.
*Fix:* Buffer updates and write `index.json` once at the end of the batch (around 424-434), or use append-only with periodic compaction.

**Sequential network requests without timeout/retry**
`src/mcm_engine.py:292-312`
`analyze_mcp_tools()` issues up to 6 sequential `requests.get()` (one per candidate file) with no timeout, no backoff, no connection pooling; one hang blocks the whole discovery.
*Fix:* Set `timeout=5`, fast-fail/circuit-break after the first timeout, use a `requests.Session()` for pooling, and consider `ThreadPoolExecutor` for parallel file probing.

**Unbounded regex over raw repo content (ReDoS / cost)**
`src/mcm_engine.py:303`
`re.findall(r'name:\s*["\']([^"\']*)["\']', content)` scans entire file contents with no size cap; `import re` is also done inside the loop (302).
*Fix:* Move `import re` to module top, compile the pattern once, cap content to ~10KB (or the tool-definition section), and add a max-file-size check.

**Unhandled file I/O in `main()`**
`src/mcm_engine.py:418-419`
Opening `mcp_list_file` is unguarded; a missing/unreadable file raises a bare `FileNotFoundError` traceback.
*Fix:* `try/except FileNotFoundError` → log and `sys.exit(1)`.

**No test suite for a ~450-line engine**
`~/Developer/tools/mcp-context-manager`
`MCMEngine` (discovery, parsing, API I/O, file I/O, JSON) has 0% coverage; no pytest/unittest/test dir.
*Fix:* Add `test/test_mcm_engine.py`: mock `requests` for GitHub/npm/Exa; cover `parse_mcp_input` edge cases, API error paths (404/500/timeout), JSON failures, file-I/O failures, and metadata round-trip.

**No error-path tests for HTTP failures**
`src/mcm_engine.py:158-160, 203-205, 262-263`
Status-code checks raise generic `Exception` with no tests for retries, timeouts, rate-limit headers, malformed bodies, or connection errors.
*Fix:* Parametrized tests across 400/401/403/404/429/500/503/504 plus `ConnectionError`/`Timeout`/`ChunkedEncodingError`.

**Weak HTTP error handling — no retry or fallback**
`src/mcm_engine.py:158-160, 203-205, 261-263, 295-296`
GitHub/npm/Exa/raw-content calls check only `status_code`; transient failures and rate limits fail discovery completely with no backoff or graceful degradation.
*Fix:* Wrap calls in a retry utility (exponential backoff + timeouts); add fallback discovery when a primary source fails.

**Directory init duplicated across three files (DRY)**
`src/mcm_engine.py:47-54`, `install.sh:71-73`, `src/commands/main.sh:45-47`
The MCM directory list is duplicated; structure changes require edits in three places.
*Fix:* Single source of truth (shared `MCM_DIRS` constant / sourced shell util) for both Python and shell.

**Routed CLI subcommands have no implementation files**
`src/commands/main.sh:107-127`
`main.sh` routes `search`, `reload`, `optimize`, `stats`, `config`, `import-env`, but only `discover.sh`, `status.sh`, `validate.sh`, `install.sh`, `main.sh` exist. The missing scripts cause "No such file or directory" failures — a broken user-facing contract.
*Fix:* Implement the missing scripts or remove the routes and help text for unimplemented commands.

**Race condition in `index.json` updates (read-modify-write)**
`src/mcm_engine.py:369-401` (also 379-400)
`save_metadata()` reads, mutates in memory, and rewrites `index.json` with no locking. Two concurrent discoveries (or a double `/mcm discover`) clobber each other; one MCP is lost.
*Fix:* `fcntl.flock()` or a `.lock` file around the read-modify-write, or atomic temp-file + `os.rename()`.

**Unhandled `JSONDecodeError` on corrupted `index.json`**
`src/mcm_engine.py:380-382`
`json.load()` is unguarded; a partial/corrupt index (e.g. crash mid-save) crashes the whole discovery with no recovery, leaving the registry inconsistent.
*Fix:* `try/except json.JSONDecodeError` → log, fall back to empty/backup index, continue. Keep a backup copy before each write.

**Incomplete tool extraction via fragile regex**
`src/mcm_engine.py:298-309`
Tool definitions are extracted with simple regex over raw source (line 299 admits "Real implementation would parse AST"). Fails on TS transpilation, minified code, programmatic tools, nested object syntax, and non-JS implementations; falls back to a dummy `unknown` tool that masks failure.
*Fix:* Parse the AST properly, or read tool definitions from `package.json` exports / an MCP manifest. Return `[]`/`None` on no match rather than dummy data.

**Silent fallback to empty `package.json`**
`src/mcm_engine.py:166-176`
On a missing `main` branch it silently retries `master`; if both fail it returns `{}` with no log or error, cascading degraded data (empty deps, no credential detection) downstream.
*Fix:* Log each failed fetch with its status code; on total failure raise or mark the `MCPMetadata` as "metadata incomplete".

---

## Medium

**Dead code — redundant `if tools` guard**
`src/mcm_engine.py:322`
`avg_params = total_params / len(tools) if tools else 0` — but 318-319 already returns early when `tools` is empty, so the `else` branch is unreachable.
*Fix:* Simplify to `total_params / len(tools)`.

**Shell variable injected into inline Python (`discover.sh`)**
`src/commands/discover.sh:68-75`
`python3 -c "...open('$CLAUDE_CONFIG')..."` interpolates an unquoted path (default contains `$HOME`); special chars/spaces split the command or inject metacharacters.
*Fix:* Pass the path as an `argv` argument (`python3 -c '... sys.argv[1] ...' "$CLAUDE_CONFIG"`) instead of string interpolation.

**Temp file not cleaned on error paths**
`src/commands/discover.sh:41, 96-99`
`MCP_INPUT_FILE` (PID-named, line 41) is removed only on the success path (99); an early error/interrupt leaves it accumulating in `~/.mcm/cache/`.
*Fix:* `trap 'rm -f "$MCP_INPUT_FILE"' EXIT INT TERM` at the top.

**Regex not anchored (ReDoS) / mishandles escaped quotes**
`src/mcm_engine.py:303`
The unanchored `name:` pattern risks backtracking on adversarial input and its character class doesn't account for escaped quotes.
*Fix:* Tighten/anchor the pattern, or replace with a real JSON/AST parser.

**No request-level timeout / rate limiting on external calls**
`src/mcm_engine.py:158, 167, 173, 203, 261, 295`
(Overlaps the Critical timeout finding; restated here for the DoS/resource angle — the `time.sleep(1)` in `main()` does not protect individual requests.)
*Fix:* Per-request `timeout`; consider a pooled session with configured timeouts.

**Shell sources an untrusted credentials file**
`src/commands/validate.sh:15-18`
`source $MCM_HOME/config/credentials.env` with `set -a` executes arbitrary code if the file is writable by an attacker (e.g. `GITHUB_TOKEN=$(cmd)`).
*Fix:* Don't `source`; parse line-by-line validating `KEY=VALUE`, export only validated vars. Verify the file is user-owned and not world-readable first.

**Path traversal via `metadata.name`**
`src/mcm_engine.py:371`
`self.mcm_home / "registry" / metadata.name` uses an API-supplied name to build a path; traversal sequences could escape the registry dir.
*Fix:* Validate against `^[a-zA-Z0-9._-]+$`, reject separators/`..`/URL-encoded variants, or hash the name for the directory.

**No explicit TLS verification**
`src/mcm_engine.py:158, 167, 173, 203, 261, 295`
HTTPS is used but `verify=True` is not set explicitly; a misconfig or old `requests` could permit MITM.
*Fix:* Add `verify=True` for clarity/defense-in-depth; consider cert pinning for GitHub/npm/Exa.

**Unvalidated `case` choice variable**
`src/commands/discover.sh:43`
`case $choice in` after `read` — invalid/unset input silently falls through; unquoted variable risks word-splitting.
*Fix:* Validate `[[ $choice =~ ^[1-3]$ ]]` before the case; quote `"$choice"`.

**Unsafe string splitting without bounds checks**
`src/mcm_engine.py:271, 109`
`url.split("github.com/")[-1].split("/")[0:2]` (and 109) silently returns short/empty results on malformed input.
*Fix:* Check split lengths before use, or parse with `urllib.parse.urlparse()`.

**Inline-Python subprocess calls unchecked in shell**
`src/commands/status.sh:17`, `src/commands/validate.sh:22-30`
`VAR=$(python3 -c "...")` without checking the return code; failures leave `$VAR` empty and the script continues silently.
*Fix:* Append `|| { echo 'Error'; exit 1; }` (subshells may not inherit `set -e`).

**Repeated JSON index reads in shell**
`src/commands/status.sh:17, 22-28`
`index.json` is parsed twice (count, then list), spawning two `python3` processes.
*Fix:* Parse once, extract count + data in a single invocation (or use `jq`).

**Linear search on index update**
`src/mcm_engine.py:387`
O(n) filter to drop the old entry before append; measurable at 100+ MCPs.
*Fix:* Key entries by name in a dict for O(1), then rebuild the list.

**Unused imports**
`src/mcm_engine.py:10, 14, 17`
`subprocess`, `Tuple`, and `hashlib` are imported but unused.
*Fix:* Remove them.

**Fixed `time.sleep(1)` per MCP in discovery loop**
`src/mcm_engine.py:434`
1s/MCP blocking regardless of response time (50 MCPs ⇒ 50s).
*Fix:* Drop the fixed sleep; back off only on HTTP 429 using response headers/timestamps.

**Non-atomic writes to `metadata.json` and `index.json`**
`src/mcm_engine.py:375-376, 399-400` (also 375-400)
Direct `open(path, "w")`; a crash/full disk mid-write truncates files and corrupts the registry.
*Fix:* Write to `.tmp`, `flush()` + `os.fsync()`, then atomic `os.rename()`.

**Race condition in `index.json` updates (medium restatement)**
`src/mcm_engine.py:379-400`
Concurrent read-then-write loses one MCP. (Same root cause as the High race-condition finding; listed for the concurrency-loss angle.)
*Fix:* File locking or a DB; serialize the read-modify-write.

**Hardcoded `master` fallback branch**
`src/mcm_engine.py:165, 172-174, 293`
Assumes a `main`/`master`-only world; breaks for `trunk`/`develop`/custom default branches.
*Fix:* Use the repo object's `default_branch` field (already fetched at 162) instead of hardcoding.

**Bare `except` in tool-analysis loop (medium restatement)**
`src/mcm_engine.py:311`
Silently continues on any error fetching tool definitions, yielding incomplete tool lists.
*Fix:* `except requests.RequestException as e:` with logging of the failing file. (Same site as the Critical bare-except finding.)

**`parse_mcp_input` untested edge cases**
`src/mcm_engine.py:98-128`
No coverage for `http://`/`https://` prefixes outside the `github.com` check, trailing slashes, incomplete GitHub paths (user only), empty/whitespace input, duplicates, or mixed formats.
*Fix:* Add unit tests for each case and various npm scoping patterns.

**No tests for file-I/O failures**
`src/mcm_engine.py:60-61, 77-78, 85-86, 375-376, 381-382, 399-400, 418, 442-443`
No coverage for missing config, corrupt JSON, permission-denied, disk-full, unwritable registry, or concurrent index access.
*Fix:* Mock `open`/`json.load`/`json.dump` to simulate `FileNotFoundError`/`PermissionError`/`JSONDecodeError`/`IOError`; assert default-config creation and graceful save failures.

**Regex tool extraction untested for false positives**
`src/mcm_engine.py:303`
No tests verify false-positive rate, special chars, multiline, or escaped quotes for the lossy name-extraction.
*Fix:* Add edge-case code samples (strings/comments/URLs containing `name:`); document that matching is intentionally lossy and not production-grade.

**Shell scripts missing `set -euo pipefail`**
`src/commands/status.sh:1-37`
`status.sh`/`validate.sh` continue on errors; no guard for missing `MCM_HOME` or corrupt index.
*Fix:* Add `set -euo pipefail`; guard `[[ -f "$MCM_HOME/registry/index.json" ]] || { echo 'Error: index not found'; exit 1; }`; test that malformed JSON gives a clear non-zero exit.

**No tests for config initialization**
`src/mcm_engine.py:42-71`
`__init__`/`load_config` default-creation untested for missing dir, corrupt config, missing keys, version mismatch, concurrent init.
*Fix:* Test the init sequence: no `.mcm` dir → structure + defaults; missing/corrupt config → defaults; missing keys → merged with defaults.

**Default config duplicated across three files**
`src/mcm_engine.py:50-71`, `install.sh:76-89`, `src/commands/main.sh:50-63`
Identical default config defined in three places.
*Fix:* Single source of truth (template JSON or shared constant).

**Oversized `analyze_mcp_tools` with simplistic matching**
`src/mcm_engine.py:277-314`
38-line method tries 6 file paths, extracts only tool names (discards params), and falls back to a dummy `unknown` tool.
*Fix:* Extract into a dedicated module; use an AST parser or read from `package.json`/manifest; return empty/`None` on no match.

**Magic numbers in complexity / cost estimation**
`src/mcm_engine.py:316-338`
`calculate_complexity`/`estimate_context_cost` use undocumented hardcoded values (100 tokens/tool, 50/param) with no empirical grounding.
*Fix:* Extract to named constants with comments; add a calibration mode comparing against real token counts; document accuracy.

**Credential detection only checks tool names**
`src/mcm_engine.py:340-354`
Infers credentials by keyword (e.g. `github`) in tool names; misses AWS/OAuth/API-key needs and only detects GitHub.
*Fix:* Parse descriptions/parameters for credential patterns (`API_KEY`/`token`/`secret`/`password`); maintain a mapping or metadata registry.

**Fragile inline-Python in multiple shell scripts**
`src/commands/status.sh:17, 22-28`, `discover.sh:68-75`, `validate.sh:22-31`
Inline `python3 -c` one-liners with unquoted interpolation create injection risk and break on special chars.
*Fix:* Move logic into `src/utils/` scripts; pass args via files/env, not command-line interpolation.

**No atomic writes to metadata/index (restatement)**
`src/mcm_engine.py:375-376, 399-400`
Direct writes risk truncation/partial state. (Same as the non-atomic-writes finding; flagged separately for registry-corruption focus.)
*Fix:* temp-file + `flush`/`fsync` + atomic `rename`.

**Stale `mcp_input` file on error (restatement)**
`src/commands/discover.sh:41, 96-99`
PID-named temp file leaks on failure/interrupt. (Same as the temp-file-cleanup finding.)
*Fix:* `trap "rm -f \"$MCP_INPUT_FILE\"" EXIT`.

**No permission check on secrets file `credentials.env`**
`src/commands/main.sh:78-96`
Created under default umask (often `0644`), so any local user can read API keys/tokens.
*Fix:* `chmod 600 $MCM_HOME/config/credentials.env` after creation; warn in `validate.sh` if perms exceed `0600`.

**Duplicate registry entries possible under race**
`src/mcm_engine.py:386-394`
Beyond the race condition, no uniqueness/dedup on write means concurrent discoveries of the same MCP can leave duplicates.
*Fix:* Fix the race; add a `last_updated` field; dedup by name on load keeping the most recent.

**No validation of `metadata.json` before indexing**
`src/mcm_engine.py:375-376, 386-394`
`metadata.json` is written, then `index.json` updated; if metadata is corrupt but the index write succeeds, the index points at invalid metadata.
*Fix:* Read back and validate required fields after writing metadata; only update the index if validation passes.

**No validation of parsed MCP input format**
`src/mcm_engine.py:98-128`
`parse_mcp_input` classifies types but never validates the extracted identifier; malformed inputs (`//github.com/user/repo`, `@invalid-scope/name`) pass through and fail later.
*Fix:* Validate per type — GitHub paths = exactly two segments, npm names follow conventions, URLs valid, names non-empty.

**Inconsistent error reporting across discovery methods**
`src/mcm_engine.py:130-276`
The `discover_mcp` dispatcher logs uniformly, but the per-source methods raise differing exception types/detail, making it hard to distinguish network vs. invalid-input vs. rate-limit failures.
*Fix:* Define custom exceptions (`InvalidMCPIdentifier`, `DiscoveryFailed`, `RateLimitExceeded`) and propagate context (status code, URL, API).

**Metadata serialization may fail on non-JSON-safe fields**
`src/mcm_engine.py:369-400`
`asdict()` on `MCPMetadata` will fail or truncate if fields ever hold non-JSON-serializable / complex nested objects.
*Fix:* Implement an explicit `to_dict()` that validates JSON-safety before writing.

**Hardcoded GitHub branch assumptions (restatement)**
`src/mcm_engine.py:165, 173, 293`
Only `main`/`master` are tried; custom default branches break. (Same root cause as the `master`-fallback finding.)
*Fix:* Use the repo's `default_branch` field.

---

## Low

**Missing error handling in bash JSON count**
`src/commands/status.sh:17`
The MCP-count one-liner doesn't validate JSON or report errors; malformed `index.json` fails silently in the subshell.
*Fix:* `... 2>&1 || echo '0'` fallback and validation.

**Exception detail disclosed in logs**
`src/mcm_engine.py:145`
`self.log(f"Discovery failed for {...}: {str(e)}")` may leak sensitive info (keys in API error messages, file paths) into log files users might share.
*Fix:* Log `type(e).__name__` + a generic message; avoid `str(e)`.

**Dataclass fields use bare `Dict`/`List`**
`src/mcm_engine.py:24-37`
`tools: List[Dict]` / `credentials_needed: List[Dict]` give analyzers no structure. (Overlaps the High type-hint finding.)
*Fix:* Introduce `Tool`/`Credential` dataclasses; use `List[Tool]`/`List[Credential]`.

**Hardcoded API key (low restatement)**
`src/mcm_engine.py:21`
Restated operational angle: the hardcoded default also breaks on key rotation. See the Critical finding.
*Fix:* Remove the default; require explicit env/credential setup.

**`set -e` without full error handling**
`src/commands/discover.sh:6`
`set -euo pipefail` is present but several commands (file-existence checks at 53-62, `python3` calls at 68-75) have no explicit handlers/feedback.
*Fix:* Add `command -v python3` guard and `|| { error; exit 1; }` on key calls.

**Unvalidated `read` input in discover**
`src/commands/discover.sh:39, 52`
`read -p` input is used without validation; shell metacharacters could reach file paths/identifiers.
*Fix:* Validate (`[[ $choice =~ ^[1-3]$ ]]`) and quote all subsequent variable uses.

**Complexity calc untested at zero/large tool counts**
`src/mcm_engine.py:316-325`
`calculate_complexity` (and `determine_optimal_format` at 360) untested at 0/1/100+ tools or boundary scores.
*Fix:* Parametrized tests at empty list, single tool, and 10+ tools; verify format boundaries.

**Credential detection name-only (low restatement)**
`src/mcm_engine.py:340-354`
Misses Postgres/Slack/AWS/API tools; untested for false positives (`githubrepo_analysis`). (Overlaps the Medium credential-detection finding.)
*Fix:* Add tests across tool names + false positives; document best-effort matching.

**Helper-function duplication in shell scripts**
`src/commands/main.sh:12-42`, `install.sh:12-24`
Color/output helpers (`info`/`success`/`error`/`warning`/`heading`) defined identically in both.
*Fix:* Shared `src/commands/lib/colors.sh` sourced by both.

**Hardcoded Claude config path**
`src/commands/discover.sh:60`
`$HOME/.config/claude/mcp_config.json` is hardcoded and may not match actual installs (often `$HOME/.claude/settings.json`).
*Fix:* Make it configurable (`MCM_CLAUDE_CONFIG` override), search known locations before failing.

**Unbounded per-level log files**
`src/mcm_engine.py:80-96`
`log()` writes to `info.log`/`error.log`/`warning.log` with no rotation/retention.
*Fix:* Use `logging.RotatingFileHandler` and a retention policy.

**`mkdir(exist_ok=True)` doesn't verify directory type**
`src/mcm_engine.py:46-54, 371-372`
Succeeds even if a *file* exists at the path; subsequent operations then fail.
*Fix:* After `mkdir`, assert `path.is_dir()`.

**`import re` inside conditional block**
`src/mcm_engine.py:302`
`re` is imported in a conditional path (alongside the unused `hashlib` at 17), risking `NameError` on future refactors.
*Fix:* Move `import re` to module top; remove unused `hashlib`.

---

## Verification

Critical and High findings are slated for adversarial verification (re-read of the cited lines + reproduction where feasible). At the time of this report the findings above are **surfaced by the 9-dimension review pass and not yet adversarially confirmed**; the highest-confidence items are:

- **Hardcoded `EXA_API_KEY` (`mcm_engine.py:21`)** — reported by 6 independent reviewers with a consistent literal value; highest confidence. Rotate the key regardless of verification outcome.
- **Bare `except:` (`mcm_engine.py:175, 311`)** — reported by 8 reviewers with consistent line numbers; high confidence.
- **Missing HTTP timeouts** and **unvalidated URL interpolation** — consistent multi-reviewer agreement on the same line sets; high confidence.

Verification has not yet reconciled exact line numbers against the current `src/mcm_engine.py` (some reviewers cite slightly different ranges, e.g. 158-160 vs 158); treat cited lines as approximate until the verification pass confirms them.
