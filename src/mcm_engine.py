#!/usr/bin/env python3
"""
MCP Context Manager (MCM) - Core Engine
Handles discovery, analysis, conversion, and management of MCPs
"""

import os
import sys
import json
import subprocess
import requests
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import hashlib

# Configuration
MCM_HOME = Path(os.getenv("MCM_HOME", Path.home() / ".mcm"))
EXA_API_KEY = os.getenv("EXA_API_KEY", "")

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
        lines = [line.strip() for line in input_text.strip().split("\n") if line.strip()]

        for line in lines:
            mcp = {"original": line, "type": "unknown", "identifier": line}

            # GitHub URL
            if "github.com" in line:
                mcp["type"] = "github_url"
                mcp["identifier"] = line.split("github.com/")[-1].rstrip("/")
            # NPM package
            elif line.startswith("@") or "/" not in line:
                if line.startswith("@modelcontextprotocol/"):
                    mcp["type"] = "npm_official"
                    mcp["identifier"] = line
                    mcp["name"] = line.replace("@modelcontextprotocol/server-", "")
                else:
                    mcp["type"] = "npm_package"
                    mcp["identifier"] = line
                    mcp["name"] = line.split("/")[-1]
            # Simple name
            else:
                mcp["type"] = "name"
                mcp["identifier"] = line
                mcp["name"] = line

            mcps.append(mcp)

        return mcps

    def discover_mcp(self, mcp_info: Dict) -> Optional[MCPMetadata]:
        """Discover and analyze a single MCP"""
        self.log(f"Discovering: {mcp_info['identifier']}", "info")

        try:
            # Try different discovery methods
            if mcp_info["type"] == "github_url":
                return self.discover_from_github(mcp_info)
            elif mcp_info["type"] in ["npm_official", "npm_package"]:
                return self.discover_from_npm(mcp_info)
            else:
                # Try Exa.ai search
                return self.discover_via_search(mcp_info)

        except Exception as e:
            self.log(f"Discovery failed for {mcp_info['identifier']}: {str(e)}", "error")
            return None

    def discover_from_github(self, mcp_info: Dict) -> Optional[MCPMetadata]:
        """Discover MCP from GitHub repository"""
        repo_path = mcp_info["identifier"]
        api_url = f"https://api.github.com/repos/{repo_path}"

        # Get repo info
        headers = {}
        if github_token := os.getenv("GITHUB_TOKEN"):
            headers["Authorization"] = f"token {github_token}"

        response = requests.get(api_url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"GitHub API error: {response.status_code}")

        repo_data = response.json()

        # Extract package.json if exists
        package_url = f"https://raw.githubusercontent.com/{repo_path}/main/package.json"
        try:
            pkg_response = requests.get(package_url)
            if pkg_response.status_code == 200:
                package_json = pkg_response.json()
            else:
                # Try master branch
                package_url = f"https://raw.githubusercontent.com/{repo_path}/master/package.json"
                pkg_response = requests.get(package_url)
                package_json = pkg_response.json() if pkg_response.status_code == 200 else {}
        except:
            package_json = {}

        # Analyze repository structure
        tools = self.analyze_mcp_tools(repo_path, headers)

        metadata = MCPMetadata(
            name=repo_data["name"],
            source="github",
            url=repo_data["html_url"],
            description=repo_data.get("description", ""),
            tools=tools,
            tool_count=len(tools),
            complexity_score=self.calculate_complexity(tools),
            context_cost_estimate=self.estimate_context_cost(tools),
            dependencies=list(package_json.get("dependencies", {}).keys()) if package_json else [],
            credentials_needed=self.detect_credentials(tools),
            discovered_at=datetime.utcnow().isoformat() + "Z",
            format=self.determine_optimal_format(tools)
        )

        return metadata

    def discover_from_npm(self, mcp_info: Dict) -> Optional[MCPMetadata]:
        """Discover MCP from npm registry"""
        package_name = mcp_info["identifier"]
        npm_url = f"https://registry.npmjs.org/{package_name}"

        response = requests.get(npm_url)
        if response.status_code != 200:
            raise Exception(f"NPM registry error: {response.status_code}")

        npm_data = response.json()
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

    def discover_via_search(self, mcp_info: Dict) -> Optional[MCPMetadata]:
        """Discover MCP using Exa.ai search"""
        query = f"model context protocol MCP {mcp_info['identifier']} server"

        if not EXA_API_KEY:
            self.log("EXA_API_KEY not set, falling back to basic search", "warning")
            return None

        headers = {
            "Content-Type": "application/json",
            "x-api-key": EXA_API_KEY
        }

        data = {
            "query": query,
            "numResults": 3,
            "useAutoprompt": True,
            "type": "neural"
        }

        response = requests.post("https://api.exa.ai/search", headers=headers, json=data)
        if response.status_code != 200:
            raise Exception(f"Exa.ai API error: {response.status_code}")

        results = response.json().get("results", [])

        # Try to find GitHub repo in results
        for result in results:
            url = result.get("url", "")
            if "github.com" in url:
                github_path = url.split("github.com/")[-1].split("/")[0:2]
                github_path = "/".join(github_path)
                return self.discover_from_github({"identifier": github_path, "type": "github_url"})

        return None

    def analyze_mcp_tools(self, repo_path: str, headers: Dict) -> List[Dict]:
        """Analyze MCP repository to extract tool definitions"""
        # This is a simplified version - would need more sophisticated analysis
        tools = []

        # Try to fetch common MCP server files
        possible_files = [
            "src/index.ts",
            "src/index.js",
            "index.ts",
            "index.js",
            "server.ts",
            "server.js"
        ]

        for file_path in possible_files:
            url = f"https://raw.githubusercontent.com/{repo_path}/main/{file_path}"
            try:
                response = requests.get(url)
                if response.status_code == 200:
                    content = response.text
                    # Simple pattern matching for tools
                    # Real implementation would parse AST
                    if "addTool" in content or "server.tool" in content:
                        # Extract tool names (simplified)
                        import re
                        tool_patterns = re.findall(r'name:\s*["\']([^"\']+)["\']', content)
                        for tool_name in tool_patterns:
                            tools.append({
                                "name": tool_name,
                                "description": "",
                                "parameters": []
                            })
                    break
            except:
                continue

        return tools if tools else [{"name": "unknown", "description": "", "parameters": []}]

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
        registry_dir = self.mcm_home / "registry" / metadata.name
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

        for i, mcp_info in enumerate(mcps, 1):
            print(f"[{i}/{len(mcps)}] Discovering {mcp_info['identifier']}...")
            metadata = engine.discover_mcp(mcp_info)

            if metadata:
                engine.save_metadata(metadata)
                print(f"  ✓ {metadata.name}: {metadata.tool_count} tools, format: {metadata.format}")
            else:
                print(f"  ✗ Failed to discover")

            time.sleep(1)  # Rate limiting

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
