#!/usr/bin/env python3
"""
MCP Context Manager (MCM) - Core Engine
Handles discovery, analysis, conversion, and management of MCPs
"""

import os
import sys
import json
import re
import subprocess
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
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
        self.config["updated_at"] = datetime.utcnow().isoformat() + "Z"
        with open(config_file, "w") as f:
            json.dump(self.config, f, indent=2)

    def log(self, message: str, level: str = "info"):
        """Log message to file and console"""
        timestamp = datetime.utcnow().isoformat()
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
            self.log(f"Discovery failed for {mcp_info['identifier']}: {str(e)}", "error")
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

        # Extract package.json if exists
        print(f"  → raw.githubusercontent.com: {repo_path} package.json")
        package_url = f"https://raw.githubusercontent.com/{repo_path}/main/package.json"
        try:
            pkg_status, pkg_text = http_request("GET", package_url)
            if pkg_status == 200:
                package_json = json.loads(pkg_text)
            else:
                # Try master branch
                package_url = f"https://raw.githubusercontent.com/{repo_path}/master/package.json"
                pkg_status, pkg_text = http_request("GET", package_url)
                package_json = json.loads(pkg_text) if pkg_status == 200 else {}
        except:
            package_json = {}

        metadata = MCPMetadata(
            name=repo_data["name"],
            source="github",
            url=repo_data["html_url"],
            description=repo_data.get("description", ""),
            tools=[],
            tool_count=0,
            complexity_score=0.0,
            context_cost_estimate=0,
            dependencies=list(package_json.get("dependencies", {}).keys()) if package_json else [],
            credentials_needed=self.detect_credentials([]),
            discovered_at=datetime.utcnow().isoformat() + "Z",
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
        latest_version = npm_data["dist-tags"]["latest"]
        latest_data = npm_data["versions"][latest_version]

        # Get repository URL
        repo_url = latest_data.get("repository", {}).get("url", "")
        if repo_url.startswith("git+"):
            repo_url = repo_url[4:]
        if repo_url.endswith(".git"):
            repo_url = repo_url[:-4]

        # If GitHub repo, analyze it
        if "github.com" in repo_url:
            github_path = repo_url.split("github.com/")[-1]
            return self.discover_from_github({"identifier": github_path, "type": "github_url"})

        # Otherwise create basic metadata
        metadata = MCPMetadata(
            name=npm_data["name"],
            source="npm",
            url=f"https://www.npmjs.com/package/{package_name}",
            description=latest_data.get("description", ""),
            tools=[],  # Would need to download and analyze
            tool_count=0,
            complexity_score=0.0,
            context_cost_estimate=0,
            dependencies=list(latest_data.get("dependencies", {}).keys()),
            credentials_needed=[],
            discovered_at=datetime.utcnow().isoformat() + "Z",
            format="direct"
        )

        return metadata

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
        registry_dir = safe_child(self.mcm_home / "registry", metadata.name)
        registry_dir.mkdir(parents=True, exist_ok=True)

        metadata_file = registry_dir / "metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(asdict(metadata), f, indent=2)

        # Update index
        index_file = self.mcm_home / "registry" / "index.json"
        if index_file.exists():
            with open(index_file) as f:
                index = json.load(f)
        else:
            index = {"mcps": [], "updated_at": ""}

        # Add or update
        existing = [m for m in index["mcps"] if m["name"] != metadata.name]
        existing.append({
            "name": metadata.name,
            "source": metadata.source,
            "tool_count": metadata.tool_count,
            "format": metadata.format,
            "discovered_at": metadata.discovered_at
        })

        index["mcps"] = existing
        index["updated_at"] = datetime.utcnow().isoformat() + "Z"

        with open(index_file, "w") as f:
            json.dump(index, f, indent=2)


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


def main():
    """Main entry point"""
    engine = MCMEngine()

    if len(sys.argv) < 2:
        print("Usage: mcm_engine.py <command> [args]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "discover":
        if len(sys.argv) < 3:
            print("Usage: mcm_engine.py discover <mcp-list-file>")
            sys.exit(1)

        mcp_list_file = sys.argv[2]
        with open(mcp_list_file) as f:
            mcp_text = f.read()

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
                    print(f"  ✓ {metadata.name}: saved")
                    ok += 1
            else:
                print(f"  ✗ Failed to discover")

            time.sleep(1)  # Rate limiting

        print(f"Discovered {ok} of {len(mcps)}")
        if len(mcps) > 0 and ok == 0:
            sys.exit(1)

    elif command == "scan-config":
        packages, skipped = scan_claude_config(Path.cwd(), Path.home())
        for package in packages:
            print(package)
        for entry in skipped:
            print(f"Skipped {entry}", file=sys.stderr)

    elif command == "list":
        index_file = engine.mcm_home / "registry" / "index.json"
        if not index_file.exists():
            print("No MCPs discovered yet. Run 'mcm discover' first.")
            sys.exit(1)

        with open(index_file) as f:
            index = json.load(f)

        print(f"\nDiscovered MCPs ({len(index['mcps'])}):\n")
        for mcp in index["mcps"]:
            print(f"  • {mcp['name']}: {mcp['tool_count']} tools ({mcp['format']})")

if __name__ == "__main__":
    main()
