#!/usr/bin/env python3
"""
MCP Context Manager (MCM) - Core Engine
Handles discovery, analysis, conversion, and management of MCPs
"""

import os
import sys
import json
import re
import queue
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib

# Configuration
MCM_HOME = Path(os.getenv("MCM_HOME", Path.home() / ".mcm"))

NPM_NAME = re.compile(
    r"(?:@[A-Za-z0-9][A-Za-z0-9._~-]*/)?[A-Za-z0-9][A-Za-z0-9._~-]*"
)
GITHUB_URL = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]{1,100})(?:/(?:tree|blob)/\S*)?/?"
)
GITHUB_REPO = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}"
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


class SameHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            old = urllib.parse.urlsplit(req.full_url)
            new = urllib.parse.urlsplit(newurl)
            old_port = old.port
            if old_port is None:
                old_port = 443 if old.scheme == "https" else 80
            new_port = new.port
            if new_port is None:
                new_port = 443 if new.scheme == "https" else 80
        except ValueError:
            return None
        old_host = old.hostname
        new_host = new.hostname
        if old_host is None or new_host is None:
            return None
        if (
            old.scheme != new.scheme
            or old_host.lower() != new_host.lower()
            or old_port != new_port
        ):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(SameHostRedirectHandler)


def open_url(request, timeout):
    return _OPENER.open(request, timeout=timeout)


def http_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict] = None,
    timeout: float = 30,
) -> Tuple[int, str]:
    """Send an HTTP request and return (status_code, response_text)."""
    req_headers = dict(headers) if headers else {}
    if "User-Agent" not in req_headers:
        req_headers["User-Agent"] = "mcp-context-manager"

    data = None
    if json_body is not None:
        req_headers["Content-Type"] = "application/json"
        data = json.dumps(json_body).encode("utf-8")

    request = urllib.request.Request(
        url, data=data, headers=req_headers, method=method
    )

    try:
        with open_url(request, timeout=timeout) as response:
            status = response.getcode()
            raw = response.read()
            if isinstance(raw, bytes):
                text = raw.decode("utf-8", errors="replace")
            else:
                text = raw or ""
            return (status, text)
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
        except Exception:
            raw = b""
        if isinstance(raw, bytes):
            body = raw.decode("utf-8", errors="replace")
        else:
            body = raw or ""
        return (exc.code, body)
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        return (0, str(reason) if reason is not None else str(exc))
    except (TimeoutError, socket.timeout) as exc:
        return (0, str(exc))


def http_error(label: str, status: int, text: str) -> Exception:
    if status == 0:
        return Exception(f"{label}: could not connect ({text})")
    if 300 <= status <= 399:
        return Exception(f"{label}: {status} (a redirect to another host was refused)")
    return Exception(f"{label}: {status}")


def _write_json_atomic(path: Path, payload) -> None:
    """Write JSON via a temp file in the same folder, then replace the target."""
    folder = path.parent
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".mcm-tmp-", dir=str(folder))
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _metadata_value_empty(value) -> bool:
    return value == "" or value == []


def _saved_metadata_object(path: Path) -> Optional[Dict]:
    """Return metadata.json when it holds a JSON object, otherwise None."""
    if not path.is_file():
        return None
    try:
        with open(path) as handle:
            data = json.load(handle)
    except (UnicodeDecodeError, ValueError):
        return None
    if isinstance(data, dict):
        return data
    return None


def _merge_metadata_records(new_record: Dict, saved: Dict) -> Dict:
    """Merge a new record with the metadata.json object saved for the same name."""
    if new_record.get("inspected"):
        merged = dict(new_record)
        for field in (
            "description",
            "dependencies",
            "credentials_needed",
            "url",
            "source",
        ):
            if _metadata_value_empty(new_record.get(field)) and field in saved:
                merged[field] = saved[field]
        if "discovered_at" in saved:
            merged["discovered_at"] = saved["discovered_at"]
        return merged
    if saved.get("inspected"):
        merged = dict(new_record)
        for field in (
            "tools",
            "tool_count",
            "complexity_score",
            "context_cost_estimate",
            "format",
            "inspected",
            "inspected_at",
        ):
            if field in saved:
                merged[field] = saved[field]
        return merged
    return dict(new_record)


def safe_child(root: Path, name: str) -> Path:
    if Path(name).is_absolute():
        raise ValueError(f"refusing to write outside {root}: {name!r}")
    root_resolved = root.resolve()
    resolved = (root / name).resolve()
    if resolved == root_resolved or not resolved.is_relative_to(root_resolved):
        raise ValueError(f"refusing to write outside {root}: {name!r}")
    return resolved


@dataclass
class MCPMetadata:
    """Metadata about an MCP"""
    name: str
    source: str  # 'npm', 'github', 'local', etc.
    url: str
    description: str
    tools: List[Dict]
    tool_count: int
    complexity_score: float
    context_cost_estimate: int
    dependencies: List[str]
    credentials_needed: List[Dict]
    discovered_at: str
    format: str  # 'progressive', 'cli', 'skill', 'direct'
    inspected: bool = False
    inspected_at: str = ""

class MCMEngine:
    """Core MCM engine for MCP management"""

    def __init__(self):
        self.mcm_home = MCM_HOME
        self.ensure_directories()
        self.load_config()

    def ensure_directories(self):
        """Create MCM directory structure"""
        dirs = [
            "config", "registry", "converted", "converted/skills",
            "embeddings", "analytics", "cache", "backups", "logs"
        ]
        for dir_name in dirs:
            (self.mcm_home / dir_name).mkdir(parents=True, exist_ok=True)

    def load_config(self):
        """Load MCM configuration"""
        config_file = self.mcm_home / "config" / "mcm-config.json"
        if config_file.exists():
            with open(config_file) as f:
                self.config = json.load(f)
        else:
            self.config = {
                "version": "1.0.0",
                "strategy": "balanced",
                "confidence_threshold": 0.7,
                "max_tool_budget_percent": 40,
                "auto_unload_after_messages": 3,
                "pinned_mcps": []
            }
            self.save_config()

    def save_config(self):
        """Save MCM configuration"""
        config_file = self.mcm_home / "config" / "mcm-config.json"
        self.config["updated_at"] = utc_now_iso()
        with open(config_file, "w") as f:
            json.dump(self.config, f, indent=2)

    def log(self, message: str, level: str = "info"):
        """Log message to file and console"""
        timestamp = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        log_file = self.mcm_home / "logs" / f"{level}.log"

        with open(log_file, "a") as f:
            f.write(f"[{timestamp}] {message}\n")

        # Also print to console
        if level == "error":
            print(f"✗ {message}", file=sys.stderr)
        elif level == "warning":
            print(f"⚠ {message}")
        elif level == "success":
            print(f"✓ {message}")
        else:
            print(f"ℹ {message}")

    def parse_mcp_input(self, input_text: str) -> List[Dict[str, str]]:
        """Parse user input and extract MCP identifiers"""
        mcps = []

        for raw in input_text.split("\n"):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            mcp = {"original": line, "type": "unknown", "identifier": line}

            if "github.com" in line:
                match = GITHUB_URL.fullmatch(line)
                if match:
                    owner = match.group(1)
                    repo = match.group(2)
                    if repo.endswith(".git"):
                        repo = repo[:-4]
                    if (not repo) or repo in (".", ".."):
                        mcp["type"] = "invalid"
                        mcp["reason"] = (
                            "not a GitHub repository URL (https://github.com/owner/repo)"
                        )
                    else:
                        mcp["type"] = "github_url"
                        mcp["identifier"] = owner + "/" + repo
                else:
                    mcp["type"] = "invalid"
                    mcp["reason"] = (
                        "not a GitHub repository URL (https://github.com/owner/repo)"
                    )
            elif (
                line.startswith("@modelcontextprotocol/")
                and NPM_NAME.fullmatch(line)
                and len(line) <= 214
            ):
                mcp["type"] = "npm_official"
                mcp["identifier"] = line
                mcp["name"] = line.replace("@modelcontextprotocol/server-", "")
            elif (
                NPM_NAME.fullmatch(line)
                and len(line) <= 214
                and (line.startswith("@") or "/" not in line)
            ):
                mcp["type"] = "npm_package"
                mcp["identifier"] = line
                mcp["name"] = line.split("/")[-1]
            else:
                mcp["type"] = "invalid"
                mcp["reason"] = (
                    "not an npm package name, a GitHub repository URL or a plain name"
                )

            mcps.append(mcp)

        return mcps

    def discover_mcp(self, mcp_info: Dict) -> Optional[MCPMetadata]:
        """Discover and analyze a single MCP"""
        if mcp_info["type"] == "invalid":
            original = mcp_info.get("original", mcp_info.get("identifier", ""))
            self.log(
                f"Skipped {original!r}: {mcp_info['reason']}",
                "warning",
            )
            return None

        self.log(f"Discovering: {mcp_info['identifier']}", "info")

        try:
            # Try different discovery methods
            if mcp_info["type"] == "github_url":
                return self.discover_from_github(mcp_info)
            elif mcp_info["type"] in ["npm_official", "npm_package"]:
                return self.discover_from_npm(mcp_info)
            else:
                original = mcp_info.get("original", mcp_info.get("identifier", ""))
                self.log(
                    f"Skipped {original!r}: not an npm package name or a GitHub repository URL",
                    "warning",
                )
                return None

        except Exception as e:
            detail = _strip_controls(str(e))
            self.log(
                f"Discovery failed for {mcp_info['identifier']}: {detail}",
                "error",
            )
            return None

    def discover_from_github(self, mcp_info: Dict) -> Optional[MCPMetadata]:
        """Discover MCP from GitHub repository"""
        repo_path = mcp_info["identifier"]
        if (
            GITHUB_REPO.fullmatch(repo_path) is None
            or repo_path.endswith("/.")
            or repo_path.endswith("/..")
        ):
            raise Exception(f"not a GitHub repository: {repo_path!r}")

        api_url = f"https://api.github.com/repos/{repo_path}"

        # Get repo info
        headers = {}
        if github_token := os.getenv("GITHUB_TOKEN"):
            headers["Authorization"] = f"token {github_token}"

        token_note = " (with your GITHUB_TOKEN)" if github_token else ""
        print(f"  → api.github.com: {repo_path}{token_note}")

        status, text = http_request("GET", api_url, headers=headers)
        if status != 200:
            raise http_error("GitHub API error", status, text)

        repo_data = json.loads(text)
        repo_name = repo_data["name"]
        if isinstance(repo_name, str):
            repo_name = _strip_controls(repo_name)

        # Extract package.json if exists. Prefer the repository's default branch.
        print(f"  → raw.githubusercontent.com: {repo_path} package.json")
        package_json = {}
        branches = []
        default_branch = repo_data.get("default_branch")
        if isinstance(default_branch, str) and default_branch:
            branches.append(urllib.parse.quote(default_branch, safe="/"))
        for branch in ("main", "master"):
            if branch not in branches:
                branches.append(branch)
        try:
            for branch in branches:
                package_url = (
                    f"https://raw.githubusercontent.com/{repo_path}/{branch}/package.json"
                )
                pkg_status, pkg_text = http_request("GET", package_url)
                if pkg_status == 200:
                    loaded = json.loads(pkg_text)
                    if isinstance(loaded, dict):
                        package_json = loaded
                    break
        except Exception:
            package_json = {}

        dependency_names = []
        raw_dependencies = package_json.get("dependencies")
        if isinstance(raw_dependencies, dict):
            dependency_names = list(raw_dependencies.keys())

        metadata = MCPMetadata(
            name=repo_name,
            source="github",
            url=repo_data["html_url"],
            description=_stored_description(repo_data.get("description", "")),
            tools=[],
            tool_count=0,
            complexity_score=0.0,
            context_cost_estimate=0,
            dependencies=dependency_names,
            credentials_needed=self.detect_credentials([]),
            discovered_at=utc_now_iso(),
            format="direct"
        )

        return metadata

    def discover_from_npm(self, mcp_info: Dict) -> Optional[MCPMetadata]:
        """Discover MCP from npm registry"""
        package_name = mcp_info["identifier"]
        npm_url = f"https://registry.npmjs.org/{package_name}"

        print(f"  → registry.npmjs.org: {package_name}")
        status, text = http_request("GET", npm_url)
        if status != 200:
            raise http_error("NPM registry error", status, text)

        npm_data = json.loads(text)
        latest_version = None
        versions = None
        if isinstance(npm_data, dict):
            dist_tags = npm_data.get("dist-tags")
            if isinstance(dist_tags, dict):
                latest_version = dist_tags.get("latest")
            versions = npm_data.get("versions")
        if (
            latest_version is None
            or not isinstance(versions, dict)
            or latest_version not in versions
            or not isinstance(versions.get(latest_version), dict)
        ):
            raise Exception(
                "npm registry answer for %s has no latest version" % package_name
            )
        latest_data = versions[latest_version]
        dependencies = latest_data.get("dependencies")
        if isinstance(dependencies, dict):
            dependency_names = list(dependencies.keys())
        else:
            dependency_names = []

        return MCPMetadata(
            name=package_name,
            source="npm",
            url="https://www.npmjs.com/package/%s" % package_name,
            description=_stored_description(latest_data.get("description", "")),
            tools=[],  # Would need to download and analyze
            tool_count=0,
            complexity_score=0.0,
            context_cost_estimate=0,
            dependencies=dependency_names,
            credentials_needed=[],
            discovered_at=utc_now_iso(),
            format="direct"
        )

    def calculate_complexity(self, tools: List[Dict]) -> float:
        """Calculate complexity score for tools"""
        if not tools:
            return 0.0

        total_params = sum(len(tool.get("parameters", [])) for tool in tools)
        avg_params = total_params / len(tools) if tools else 0

        # Complexity = number of tools * average parameters
        return len(tools) * (1 + avg_params * 0.5)

    def estimate_context_cost(self, tools: List[Dict]) -> int:
        """Estimate context token cost for tools"""
        if not tools:
            return 500

        # Rough estimate: 100 tokens per tool + 50 per parameter
        cost = 0
        for tool in tools:
            cost += 100
            cost += len(tool.get("parameters", [])) * 50

        return cost

    def detect_credentials(self, tools: List[Dict]) -> List[Dict]:
        """Detect required credentials from tool definitions"""
        # Simplified - real implementation would analyze code
        credentials = []
        tool_names_str = " ".join([tool.get("name", "") for tool in tools])

        if "github" in tool_names_str.lower():
            credentials.append({
                "name": "GITHUB_TOKEN",
                "description": "GitHub Personal Access Token",
                "url": "https://github.com/settings/tokens",
                "scopes": ["repo", "read:org"]
            })

        return credentials

    def determine_optimal_format(self, tools: List[Dict]) -> str:
        """Determine optimal conversion format"""
        tool_count = len(tools)

        if tool_count == 0:
            return "direct"
        elif tool_count >= 10:
            return "progressive"
        elif tool_count <= 5:
            return "cli"
        else:
            return "skill"

    def save_metadata(self, metadata: MCPMetadata):
        """Save MCP metadata to registry"""
        registry_root = self.mcm_home / "registry"
        index_file = registry_root / "index.json"
        if index_file.exists():
            try:
                with open(index_file) as f:
                    index = json.load(f)
            except json.JSONDecodeError:
                raise ValueError(
                    f"the registry index is not valid JSON: {index_file}"
                )
        else:
            index = {"mcps": [], "updated_at": ""}

        mcps = index.get("mcps", [])
        if not isinstance(mcps, list):
            mcps = []
        index["mcps"] = mcps

        registry_dir = safe_child(registry_root, metadata.name)
        metadata_file = registry_dir / "metadata.json"
        saved = _saved_metadata_object(metadata_file)
        record = asdict(metadata)
        if saved is not None:
            record = _merge_metadata_records(record, saved)

        registry_dir.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(metadata_file, record)

        entry = {
            "name": record["name"],
            "source": record["source"],
            "tool_count": record["tool_count"],
            "format": record["format"],
            "discovered_at": record["discovered_at"],
            "inspected": bool(record.get("inspected")),
        }
        if record.get("inspected"):
            entry["context_tokens"] = record["context_cost_estimate"]

        existing = []
        for item in index["mcps"]:
            if (
                isinstance(item, dict)
                and isinstance(item.get("name"), str)
                and item.get("name") == metadata.name
            ):
                continue
            existing.append(item)
        existing.append(entry)

        index["mcps"] = existing
        index["updated_at"] = utc_now_iso()

        _write_json_atomic(index_file, index)


class InspectError(Exception):
    pass


INSPECT_TIMEOUT = 30

_INSPECT_ENV_KEYS = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "TMPDIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "all_proxy",
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)
_MAX_TOOL_PAGES = 20
_STDERR_TAIL_BYTES = 4096


def _strip_controls(text: str) -> str:
    kept = []
    for ch in text:
        code = ord(ch)
        # Drop C0 controls (including escape), DEL, the C1 range, and format characters.
        if code < 32 or code == 127 or 0x80 <= code <= 0x9F:
            continue
        if unicodedata.category(ch) == "Cf":
            continue
        kept.append(ch)
    return "".join(kept)


def _numeric_count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return value


def _stored_description(value):
    """Registry description safe to save. A null description is an empty string."""
    if value is None:
        return ""
    if isinstance(value, str):
        spaced = value.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        return _strip_controls(spaced)
    return value


def _inspect_env() -> Dict[str, str]:
    env = {}  # type: Dict[str, str]
    for key in _INSPECT_ENV_KEYS:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _read_stderr_tail(path: str) -> str:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size > _STDERR_TAIL_BYTES:
                handle.seek(size - _STDERR_TAIL_BYTES)
            else:
                handle.seek(0)
            data = handle.read(_STDERR_TAIL_BYTES)
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def _stop_inspect_process(proc):
    if proc is None:
        return
    try:
        if proc.stdin is not None and not proc.stdin.closed:
            proc.stdin.close()
    except OSError:
        pass
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def _context_tokens(raw_tools: List) -> int:
    total = 0
    for entry in raw_tools:
        total += len(json.dumps(entry, sort_keys=True, separators=(",", ":")))
    return total // 4


def _clean_tools(raw_tools: List) -> List[Dict]:
    cleaned = []  # type: List[Dict]
    for entry in raw_tools:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str):
            continue
        name = _strip_controls(name)
        if name == "":
            continue
        if len(name) > 200:
            name = name[:200]
        description = entry.get("description", "")
        if not isinstance(description, str):
            description = ""
        description = _stored_description(description)[:200]
        if "inputSchema" not in entry or entry.get("inputSchema") is None:
            schema_size = 0
        else:
            schema_size = len(
                json.dumps(
                    entry["inputSchema"], sort_keys=True, separators=(",", ":")
                )
            )
        cleaned.append(
            {
                "name": name,
                "description": description,
                "schema_size": schema_size,
            }
        )
    return cleaned


def inspect_command(
    command: List[str],
    timeout: float = INSPECT_TIMEOUT,
    notes: Optional[List[str]] = None,
) -> Tuple[List[Dict], int]:
    """Start one MCP server and collect its tool names over stdio."""
    work = tempfile.TemporaryDirectory(prefix="mcm-inspect-")
    proc = None
    stderr_fh = None
    try:
        stderr_path = os.path.join(work.name, "stderr.txt")
        stderr_fh = open(stderr_path, "wb")
        proc = subprocess.Popen(
            command,
            cwd=work.name,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_fh,
            env=_inspect_env(),
            start_new_session=True,
        )
        try:
            return _inspect_exchange(proc, stderr_path, timeout, notes)
        finally:
            _stop_inspect_process(proc)
            proc = None
    finally:
        if proc is not None:
            _stop_inspect_process(proc)
        if stderr_fh is not None:
            try:
                stderr_fh.close()
            except OSError:
                pass
        work.cleanup()


def _inspect_exchange(
    proc,
    stderr_path: str,
    timeout: float,
    notes: Optional[List[str]] = None,
) -> Tuple[List[Dict], int]:
    line_queue = queue.Queue()  # type: queue.Queue
    skipped = [0]

    def reader():
        try:
            while True:
                line = proc.stdout.readline()
                if line == b"":
                    break
                line_queue.put(line)
        except Exception:
            pass
        finally:
            line_queue.put(None)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout

    def non_json_suffix():
        count = skipped[0]
        if count > 0:
            return " (%d line(s) of its output were not JSON-RPC)" % count
        return ""

    def record_note():
        count = skipped[0]
        if notes is not None and count > 0:
            notes.append(
                "the server wrote %d line(s) to its output that are not JSON-RPC; they were ignored"
                % count
            )

    def timed_out():
        record_note()
        raise InspectError(
            "the server did not answer within %g seconds; it was stopped%s. If npx was still downloading the package, run it again."
            % (timeout, non_json_suffix())
        )

    def exited():
        code = proc.poll()
        if code is None:
            try:
                code = proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                code = proc.poll()
        if code is None:
            code = -1
        message = "the server exited before answering (exit code %s)" % code
        err = _read_stderr_tail(stderr_path)
        if err:
            err = err.replace("\r\n", " | ").replace("\n", " | ").replace("\r", " | ")
            err = _strip_controls(err)
            if err:
                message += " | " + err[-500:]
        record_note()
        raise InspectError(message + non_json_suffix())

    def send(payload: Dict):
        if time.monotonic() >= deadline:
            timed_out()
        if proc.poll() is not None:
            exited()
        data = (json.dumps(payload) + "\n").encode("utf-8")
        try:
            proc.stdin.write(data)
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            exited()

    def wait_response(expected_id, method: str):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out()
            try:
                line = line_queue.get(timeout=remaining)
            except queue.Empty:
                timed_out()
            if line is None:
                exited()
            text = line.decode("utf-8", errors="replace").strip()
            if text == "":
                continue
            try:
                message = json.loads(text)
            except (ValueError, RecursionError):
                skipped[0] += 1
                continue
            if not isinstance(message, dict):
                skipped[0] += 1
                continue
            msg_id = message.get("id")
            if isinstance(msg_id, bool) or msg_id != expected_id:
                continue
            if "method" in message:
                continue
            if "result" not in message and "error" not in message:
                continue
            error = message.get("error")
            if "error" in message and error is not None:
                if not isinstance(error, dict):
                    error = {}
                detail = error.get("message", "")
                if not isinstance(detail, str):
                    detail = "" if detail is None else str(detail)
                record_note()
                raise InspectError(
                    "the server answered %s with an error: %s"
                    % (method, _strip_controls(detail))
                )
            return message.get("result")

    send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {
                    "name": "mcp-context-manager",
                    "version": "1.0.0",
                },
            },
        }
    )
    wait_response(1, "initialize")
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    raw_tools = []  # type: List
    cursor = None
    next_id = 2
    for _page in range(_MAX_TOOL_PAGES):
        if cursor is None:
            params = {}  # type: Dict
        else:
            params = {"cursor": cursor}
        send(
            {
                "jsonrpc": "2.0",
                "id": next_id,
                "method": "tools/list",
                "params": params,
            }
        )
        result = wait_response(next_id, "tools/list")
        next_id += 1
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            record_note()
            raise InspectError("the server's tools/list answer has no tools list")
        raw_tools.extend(result["tools"])
        cursor = result.get("nextCursor")
        if not isinstance(cursor, str):
            cursor = None
            break

    record_note()
    if notes is not None and isinstance(cursor, str):
        notes.append(
            "the server has more than 20 pages of tools; only the first 20 pages were read"
        )
    return (_clean_tools(raw_tools), _context_tokens(raw_tools))


def _cmd_inspect(engine: "MCMEngine"):
    if len(sys.argv) < 3 or sys.argv[2].startswith("-"):
        print(
            "Usage: mcm_engine.py inspect <package> [--yes] [-- <server args>...]"
        )
        sys.exit(1)

    package = sys.argv[2]
    rest = sys.argv[3:]
    yes = False
    if rest and rest[0] == "--yes":
        yes = True
        rest = rest[1:]
    server_args = []  # type: List[str]
    if rest and rest[0] == "--":
        server_args = rest[1:]
        rest = []
    if rest:
        print(
            "Usage: mcm_engine.py inspect <package> [--yes] [-- <server args>...]"
        )
        sys.exit(1)

    if NPM_NAME.fullmatch(package) is None or len(package) > 214:
        print(f"Error: not an npm package name: {package!r}")
        sys.exit(1)

    if shutil.which("npx") is None:
        print("Error: npx was not found. Install Node.js, then try again.")
        sys.exit(1)

    print(
        f"This runs {package}'s own code on your machine, the same as installing it."
    )
    if not yes:
        if not sys.stdin.isatty():
            print("Not started. Run it again with --yes to continue.")
            sys.exit(1)
        try:
            answer = input("Continue? (y/n) ")
        except EOFError:
            print("Not started.")
            sys.exit(1)
        if answer.strip().lower() not in ("y", "yes"):
            print("Not started.")
            sys.exit(1)

    print(
        f"Starting npx -y {package} in a temporary folder; it is stopped after {INSPECT_TIMEOUT} seconds."
    )
    notes = []  # type: List[str]
    try:
        tools, context_tokens = inspect_command(
            ["npx", "-y", package] + server_args,
            notes=notes,
        )
    except InspectError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    except OSError as exc:
        print("Error: could not start npx (%s)" % exc)
        sys.exit(1)

    now = utc_now_iso()
    metadata = MCPMetadata(
        name=package,
        source="npm",
        url=f"https://www.npmjs.com/package/{package}",
        description="",
        tools=tools,
        tool_count=len(tools),
        complexity_score=float(len(tools)),
        context_cost_estimate=context_tokens,
        dependencies=[],
        credentials_needed=[],
        discovered_at=now,
        format=engine.determine_optimal_format(tools),
        inspected=True,
        inspected_at=now,
    )
    try:
        engine.save_metadata(metadata)
    except (ValueError, OSError) as exc:
        print(f"Error: {package} was inspected but not saved ({exc})")
        sys.exit(1)
    print(
        f"{package}: {len(tools)} tools, about {context_tokens} tokens of tool definitions"
    )
    for tool in tools:
        print(f"  - {tool['name']} (schema {tool['schema_size']} characters)")
    for note in notes:
        print(f"Note: {note}")


def scan_claude_config(project_dir: Path, home: Path) -> Tuple[List[str], List[str]]:
    packages = []  # type: List[str]
    skipped = []  # type: List[str]

    def strip_version(package):
        if package.startswith("@"):
            idx = package.find("@", 1)
            if idx != -1:
                return package[:idx]
            return package
        idx = package.find("@")
        if idx != -1:
            return package[:idx]
        return package

    def npx_package(entry):
        if not isinstance(entry, dict):
            return None
        command = entry.get("command")
        if not isinstance(command, str):
            return None
        base = os.path.basename(command)
        if base not in ("npx", "bunx"):
            return None
        args = entry.get("args")
        if not isinstance(args, list):
            return None
        for arg in args:
            if isinstance(arg, str) and not arg.startswith("-"):
                return strip_version(arg)
        return None

    def ingest(obj):
        if not isinstance(obj, dict):
            return
        servers = obj.get("mcpServers")
        if not isinstance(servers, dict):
            return
        for name, entry in servers.items():
            package = npx_package(entry)
            if package is not None:
                if package not in packages:
                    packages.append(package)
            else:
                skip_entry = f"{name}: not started with npx or bunx"
                if skip_entry not in skipped:
                    skipped.append(skip_entry)

    def load_object(path):
        try:
            with open(path) as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None
        if isinstance(data, dict):
            return data
        return None

    project_cfg = load_object(project_dir / ".mcp.json")
    if project_cfg is not None:
        ingest(project_cfg)

    home_cfg = load_object(home / ".claude.json")
    if home_cfg is not None:
        ingest(home_cfg)
        projects = home_cfg.get("projects")
        if isinstance(projects, dict):
            for value in projects.values():
                ingest(value)

    return (packages, skipped)


def _engine_usage():
    return (
        "Usage: mcm_engine.py <command> [args]\n"
        "\n"
        "Commands:\n"
        "  discover <file>    Discover MCPs named in a file\n"
        "  inspect <package>  Start a server and list its tools\n"
        "  scan-config        Read MCP package names from Claude config\n"
        "  list               List discovered MCPs"
    )


def main():
    """Main entry point"""
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(_engine_usage())
        sys.exit(0)

    command = sys.argv[1]
    if command not in ("discover", "inspect", "scan-config", "list"):
        print("Error: unknown command %s" % command)
        print(_engine_usage())
        sys.exit(1)

    engine = MCMEngine()

    if command == "discover":
        if len(sys.argv) < 3:
            print("Usage: mcm_engine.py discover <mcp-list-file>")
            sys.exit(1)

        mcp_list_file = sys.argv[2]
        try:
            with open(mcp_list_file) as f:
                mcp_text = f.read()
        except OSError:
            print("Error: cannot read %s" % mcp_list_file)
            sys.exit(1)

        mcps = engine.parse_mcp_input(mcp_text)
        print(f"Found {len(mcps)} MCPs to discover\n")

        ok = 0
        for i, mcp_info in enumerate(mcps, 1):
            print(f"[{i}/{len(mcps)}] Discovering {mcp_info['identifier']}...")
            metadata = engine.discover_mcp(mcp_info)

            if metadata:
                try:
                    engine.save_metadata(metadata)
                except (ValueError, OSError) as exc:
                    print(f"  ✗ {metadata.name}: not saved ({exc})")
                else:
                    from_npm = metadata.source == "npm" or mcp_info.get("type") in (
                        "npm_package",
                        "npm_official",
                    )
                    if from_npm:
                        print(
                            f"  ✓ {metadata.name}: saved; tools not inspected (run: mcm inspect {metadata.name})"
                        )
                    else:
                        print(f"  ✓ {metadata.name}: saved; tools not inspected")
                    ok += 1
            else:
                print(f"  ✗ Failed to discover")

            time.sleep(1)  # Rate limiting

        print(f"Discovered {ok} of {len(mcps)}")
        if len(mcps) > 0 and ok < len(mcps):
            sys.exit(1 if ok == 0 else 2)

    elif command == "inspect":
        _cmd_inspect(engine)

    elif command == "scan-config":
        packages, skipped = scan_claude_config(Path.cwd(), Path.home())
        for package in packages:
            print(package)
        for entry in skipped:
            print(f"Skipped {entry}", file=sys.stderr)

    elif command == "list":
        index_file = engine.mcm_home / "registry" / "index.json"
        if not index_file.exists():
            print("No MCPs discovered yet.")
            sys.exit(1)

        invalid_index = False
        try:
            with open(index_file) as f:
                index = json.load(f)
        except json.JSONDecodeError:
            invalid_index = True
            index = None
        if not invalid_index and (
            not isinstance(index, dict)
            or not isinstance(index.get("mcps", []), list)
        ):
            invalid_index = True
        if invalid_index:
            print(
                "The registry index is not valid JSON: %s. Move it aside and run discover again."
                % index_file
            )
            sys.exit(1)

        mcps = index.get("mcps", [])
        print(f"\nDiscovered MCPs ({len(mcps)}):\n")
        for mcp in mcps:
            if not isinstance(mcp, dict):
                continue
            name = mcp.get("name", "")
            if isinstance(name, str):
                name = _strip_controls(name)
            tool_count = _numeric_count(mcp.get("tool_count", 0))
            fmt = mcp.get("format", "")
            print(f"  • {name}: {tool_count} tools ({fmt})")

if __name__ == "__main__":
    main()
