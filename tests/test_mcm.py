#!/usr/bin/env python3
"""Tests for MCP Context Manager installer, engine, and command routing."""

import email.message
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
ISO_CREATED_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

STUB_ENGINE = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

record = Path(os.environ["MCM_STUB_RECORD"])
contents = ""
if len(sys.argv) > 2:
    contents = Path(sys.argv[2]).read_text()
entry = {"argv": sys.argv, "contents": contents}
if record.exists():
    items = json.loads(record.read_text())
else:
    items = []
items.append(entry)
record.write_text(json.dumps(items))
"""


def isolated_env(home, extra=None):
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["MCM_HOME"] = str(Path(home) / ".mcm")
    if extra:
        env.update(extra)
    return env


def load_engine(mcm_home):
    os.environ["MCM_HOME"] = str(mcm_home)
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    sys.modules.pop("mcm_engine", None)
    import mcm_engine
    mcm_engine.MCM_HOME = Path(mcm_home)
    return mcm_engine


def install_copy(home):
    claude_scripts = Path(home) / ".claude" / "scripts" / "mcm"
    claude_scripts.mkdir(parents=True)
    (Path(home) / ".claude" / "commands").mkdir(parents=True)
    shutil.copy(str(SRC_DIR / "mcm.md"), str(Path(home) / ".claude" / "commands" / "mcm.md"))
    shutil.copy(str(SRC_DIR / "mcm_engine.py"), str(claude_scripts / "mcm_engine.py"))
    for script in ("main.sh", "discover.sh", "status.sh", "validate.sh"):
        dest = claude_scripts / script
        shutil.copy(str(SRC_DIR / "commands" / script), str(dest))
        os.chmod(str(dest), 0o755)
    mcm_home = Path(home) / ".mcm"
    for name in (
        "config",
        "registry",
        "converted",
        "embeddings",
        "analytics",
        "cache",
        "backups",
        "logs",
    ):
        (mcm_home / name).mkdir(parents=True)
    return claude_scripts


class FakeHTTPResponse(object):
    def __init__(self, status, body):
        self._status = status
        if isinstance(body, bytes):
            self._body = body
        else:
            self._body = body.encode("utf-8")

    def getcode(self):
        return self._status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def make_http_error(url, code, body):
    raw = body.encode("utf-8") if isinstance(body, str) else body
    return urllib.error.HTTPError(
        url, code, "Error", email.message.Message(), io.BytesIO(raw)
    )


class IsolatedHomeTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.mcm_home = self.home / ".mcm"
        self._old_home = os.environ.get("HOME")
        self._old_mcm = os.environ.get("MCM_HOME")
        os.environ["HOME"] = str(self.home)
        os.environ["MCM_HOME"] = str(self.mcm_home)

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        if self._old_mcm is None:
            os.environ.pop("MCM_HOME", None)
        else:
            os.environ["MCM_HOME"] = self._old_mcm
        self._tmpdir.cleanup()


class InstallScriptTests(IsolatedHomeTest):
    def test_install_writes_valid_config_copies_scripts_and_skips_pip(self):
        """source: installer pip-installed requests and wrote invalid JSON for created_at"""
        bindir = self.tmp / "bin"
        bindir.mkdir()
        record = self.tmp / "python-args.log"
        wrapper = bindir / "python3"
        wrapper.write_text(
            "#!/bin/bash\n"
            "echo \"$@\" >> \"$MCM_TEST_PY_RECORD\"\n"
            "exec \"$MCM_TEST_REAL_PYTHON\" \"$@\"\n"
        )
        os.chmod(str(wrapper), 0o755)

        env = isolated_env(
            self.home,
            {
                "MCM_TEST_PY_RECORD": str(record),
                "MCM_TEST_REAL_PYTHON": sys.executable,
            },
        )
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")

        proc = subprocess.run(
            ["bash", str(REPO_ROOT / "install.sh")],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            proc.returncode,
            0,
            "install.sh failed:\n%s\n%s" % (proc.stdout, proc.stderr),
        )

        config_path = self.mcm_home / "config" / "mcm-config.json"
        self.assertTrue(config_path.is_file())
        with open(str(config_path)) as handle:
            try:
                config = json.load(handle)
            except ValueError as exc:
                self.fail("mcm-config.json is not valid JSON: %s" % exc)
        self.assertRegex(config.get("created_at", ""), ISO_CREATED_AT)

        scripts = Path(self.home) / ".claude" / "scripts" / "mcm"
        for name in ("main.sh", "discover.sh", "status.sh", "validate.sh", "mcm_engine.py"):
            self.assertTrue((scripts / name).is_file(), "missing %s" % name)

        recorded = record.read_text() if record.exists() else ""
        self.assertNotIn("pip", recorded)


class ParseMcpInputTests(IsolatedHomeTest):
    def test_parse_mcp_input_skips_comments_and_classifies_names(self):
        """source: parse_mcp_input treated comment and blank lines as MCP names"""
        engine_mod = load_engine(self.mcm_home)
        engine = engine_mod.MCMEngine()
        parsed = engine.parse_mcp_input(
            "\n".join(
                [
                    "# comment",
                    "",
                    "https://github.com/owner/repo",
                    "@scope/pkg",
                    "",
                    "filesystem",
                    "# trailing comment",
                ]
            )
        )
        self.assertEqual(len(parsed), 3)
        by_original = dict((item["original"], item) for item in parsed)
        self.assertEqual(by_original["https://github.com/owner/repo"]["type"], "github_url")
        self.assertEqual(by_original["@scope/pkg"]["type"], "npm_package")
        self.assertEqual(by_original["filesystem"]["type"], "npm_package")
        self.assertEqual(by_original["filesystem"]["identifier"], "filesystem")


class HttpRequestTests(IsolatedHomeTest):
    def test_http_request_success_http_error_and_url_error(self):
        """source: engine called requests.get/post instead of stdlib HTTP"""
        engine_mod = load_engine(self.mcm_home)

        with patch(
            "urllib.request.urlopen",
            return_value=FakeHTTPResponse(200, "ok-body"),
        ):
            status, text = engine_mod.http_request("GET", "http://example.test/ok")
        self.assertEqual(status, 200)
        self.assertEqual(text, "ok-body")

        with patch(
            "urllib.request.urlopen",
            side_effect=make_http_error("http://example.test/missing", 404, "nope"),
        ):
            status, text = engine_mod.http_request("GET", "http://example.test/missing")
        self.assertEqual(status, 404)
        self.assertEqual(text, "nope")

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("network down"),
        ):
            status, text = engine_mod.http_request("GET", "http://example.test/down")
        self.assertEqual(status, 0)
        self.assertIn("network down", text)

    def test_http_request_sends_json_body_and_user_agent(self):
        """source: requests set the JSON content type and body for the Exa search; the stdlib call must send them itself"""
        engine_mod = load_engine(self.mcm_home)
        recorded = []

        def capture_urlopen(request, *args, **kwargs):
            recorded.append(request)
            return FakeHTTPResponse(200, "{}")

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            engine_mod.http_request(
                "POST",
                "http://example.test/search",
                json_body={"query": "x", "numResults": 2},
            )
            engine_mod.http_request(
                "GET",
                "http://example.test/page",
                headers={"User-Agent": "custom-agent"},
            )

        request = recorded[0]
        headers = {k.lower(): v for k, v in request.header_items()}
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(headers.get("content-type"), "application/json")
        self.assertEqual(headers.get("user-agent"), "mcp-context-manager")
        try:
            parsed = json.loads(request.data.decode("utf-8"))
        except ValueError as exc:
            self.fail("request body is not JSON: %s" % exc)
        self.assertEqual(parsed, {"query": "x", "numResults": 2})

        request = recorded[1]
        headers = {k.lower(): v for k, v in request.header_items()}
        self.assertEqual(headers.get("user-agent"), "custom-agent")
        self.assertNotIn("content-type", headers)
        self.assertIsNone(request.data)


class NpmDiscoverTests(IsolatedHomeTest):
    def test_discover_from_npm_non_github_and_save_metadata(self):
        """source: discover_from_npm could not run without requests, and registry index was untested"""
        engine_mod = load_engine(self.mcm_home)
        npm_doc = {
            "name": "demo-mcp",
            "dist-tags": {"latest": "1.2.3"},
            "versions": {
                "1.2.3": {
                    "description": "Demo MCP",
                    "repository": {"url": "git+https://gitlab.com/example/demo-mcp.git"},
                    "dependencies": {"left-pad": "1.0.0"},
                }
            },
        }

        def fake_http(method, url, headers=None, json_body=None, timeout=30):
            return (200, json.dumps(npm_doc))

        engine = engine_mod.MCMEngine()
        with patch.object(engine_mod, "http_request", side_effect=fake_http):
            try:
                metadata = engine.discover_from_npm(
                    {"identifier": "demo-mcp", "type": "npm_package"}
                )
            except Exception as exc:
                self.fail("discover_from_npm raised %r" % (exc,))

        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.name, "demo-mcp")
        self.assertEqual(metadata.source, "npm")
        self.assertEqual(metadata.description, "Demo MCP")

        engine.save_metadata(metadata)
        index_path = self.mcm_home / "registry" / "index.json"
        with open(str(index_path)) as handle:
            index = json.load(handle)
        names = [item["name"] for item in index.get("mcps", [])]
        self.assertIn("demo-mcp", names)


class DiscoverScriptTests(IsolatedHomeTest):
    def test_discover_args_call_engine_and_empty_stdin_exits(self):
        """source: /mcm discover only worked through an interactive menu Claude Code cannot answer"""
        scripts = install_copy(self.home)
        stub_path = scripts / "mcm_engine.py"
        stub_path.write_text(STUB_ENGINE)
        record = self.tmp / "stub-record.json"
        env = isolated_env(self.home, {"MCM_STUB_RECORD": str(record)})

        proc = subprocess.run(
            ["bash", str(scripts / "discover.sh"), "alpha", "beta"],
            cwd=str(self.tmp),
            env=env,
            input="",
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            proc.returncode,
            0,
            "discover.sh with names failed:\n%s\n%s" % (proc.stdout, proc.stderr),
        )
        self.assertTrue(record.is_file())
        items = json.loads(record.read_text())
        self.assertEqual(len(items), 1)
        argv = items[0]["argv"]
        self.assertEqual(argv[1], "discover")
        self.assertEqual(len(argv), 3)
        self.assertEqual(items[0]["contents"].splitlines(), ["alpha", "beta"])

        empty_record = self.tmp / "stub-record-empty.json"
        env_empty = isolated_env(self.home, {"MCM_STUB_RECORD": str(empty_record)})
        empty = subprocess.run(
            ["bash", str(scripts / "discover.sh")],
            cwd=str(self.tmp),
            env=env_empty,
            input="",
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(empty.returncode, 1)
        combined = empty.stdout + empty.stderr
        self.assertIn(
            "No MCP names given. Example: mcm discover @modelcontextprotocol/server-filesystem",
            combined,
        )
        self.assertFalse(empty_record.exists())

    def test_discover_comment_only_stdin_exits(self):
        """source: a list holding only comment and blank lines reached the engine as if it held names"""
        scripts = install_copy(self.home)
        stub_path = scripts / "mcm_engine.py"
        stub_path.write_text(STUB_ENGINE)
        record = self.tmp / "stub-record-comments.json"
        env = isolated_env(self.home, {"MCM_STUB_RECORD": str(record)})

        proc = subprocess.run(
            ["bash", str(scripts / "discover.sh")],
            cwd=str(self.tmp),
            env=env,
            input="# just a comment\n\n   \n# another\n",
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 1)
        combined = proc.stdout + proc.stderr
        self.assertIn(
            "No MCP names given. Example: mcm discover @modelcontextprotocol/server-filesystem",
            combined,
        )
        self.assertFalse(record.exists())

    def test_discover_piped_names_reach_engine(self):
        """source: names piped on standard input (the README's paste flow) must reach the engine without the menu"""
        scripts = install_copy(self.home)
        stub_path = scripts / "mcm_engine.py"
        stub_path.write_text(STUB_ENGINE)
        record = self.tmp / "stub-record-piped.json"
        env = isolated_env(self.home, {"MCM_STUB_RECORD": str(record)})

        proc = subprocess.run(
            ["bash", str(scripts / "discover.sh")],
            cwd=str(self.tmp),
            env=env,
            input="gamma\n# note\n\ndelta\n",
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            proc.returncode,
            0,
            "discover.sh with piped names failed:\n%s\n%s" % (proc.stdout, proc.stderr),
        )
        self.assertTrue(record.is_file())
        items = json.loads(record.read_text())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["argv"][1], "discover")
        names = [
            line
            for line in items[0]["contents"].splitlines()
            if line and not line.startswith("#")
        ]
        self.assertEqual(names, ["gamma", "delta"])


class MainScriptTests(IsolatedHomeTest):
    def test_main_sh_search_is_unknown_and_help_omits_search(self):
        """source: main.sh routed search to a missing script and help listed commands with no scripts"""
        main = SRC_DIR / "commands" / "main.sh"
        env = isolated_env(self.home)

        search = subprocess.run(
            ["bash", str(main), "search"],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(search.returncode, 1)
        self.assertIn("Unknown command", search.stdout + search.stderr)

        help_proc = subprocess.run(
            ["bash", str(main), "help"],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(help_proc.returncode, 0)
        help_text = (help_proc.stdout + help_proc.stderr).lower()
        self.assertNotIn("search", help_text)


class ImportTests(unittest.TestCase):
    def test_import_succeeds_when_requests_is_blocked(self):
        """source: engine imported requests, which the installer tried to pip-install"""
        had_requests = "requests" in sys.modules
        saved_requests = sys.modules.get("requests")
        sys.modules["requests"] = None
        try:
            sys.modules.pop("mcm_engine", None)
            if str(SRC_DIR) not in sys.path:
                sys.path.insert(0, str(SRC_DIR))
            try:
                import mcm_engine
            except ImportError as exc:
                self.fail("importing mcm_engine needs requests: %s" % exc)
            self.assertTrue(hasattr(mcm_engine, "http_request"))
            self.assertTrue(hasattr(mcm_engine, "MCMEngine"))
        finally:
            if had_requests:
                sys.modules["requests"] = saved_requests
            else:
                sys.modules.pop("requests", None)


if __name__ == "__main__":
    unittest.main()
