#!/usr/bin/env python3
"""Tests for MCP Context Manager installer, engine, and command routing."""

import contextlib
import email.message
import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
FAKE = str(Path(__file__).resolve().parent / "fake_mcp_server.py")
INSPECT_SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
}
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

    def test_install_prints_no_raw_color_codes(self):
        """source: the installer's Next steps printed raw color codes"""
        env = isolated_env(self.home)
        proc = subprocess.run(
            ["bash", str(REPO_ROOT / "install.sh")],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        combined = proc.stdout + proc.stderr
        self.assertNotIn("\\033", combined)
        self.assertIn("Next steps:", combined)

    def test_install_does_not_copy_second_installer(self):
        """source: review: the root installer copied a legacy second installer"""
        env = isolated_env(self.home)
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
        scripts = Path(self.home) / ".claude" / "scripts" / "mcm"
        self.assertTrue((scripts / "main.sh").is_file())
        self.assertFalse((scripts / "install.sh").exists())

    def test_install_creates_no_credentials_file(self):
        """source: review: the installer created a world-readable token file that nothing reads"""
        env = isolated_env(self.home)
        proc = subprocess.run(
            ["bash", str(REPO_ROOT / "install.sh")],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        combined = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, combined)
        self.assertNotIn("credentials", combined)
        token_file = "credentials" + ".env"
        found = []
        if self.mcm_home.exists():
            for dirpath, _dirnames, filenames in os.walk(str(self.mcm_home)):
                for filename in filenames:
                    if filename == token_file:
                        found.append(os.path.join(dirpath, filename))
        self.assertEqual(found, [])

    def test_repository_text_omits_credentials_file_name(self):
        """source: review: the installer created a world-readable token file that nothing reads"""
        needle = "credentials" + ".env"
        offenders = []
        for dirpath, dirnames, filenames in os.walk(str(REPO_ROOT)):
            dirnames[:] = [name for name in dirnames if name != ".git"]
            for filename in filenames:
                path = os.path.join(dirpath, filename)
                try:
                    with open(path, "rb") as handle:
                        data = handle.read()
                except OSError:
                    continue
                if b"\0" in data:
                    continue
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if needle in text:
                    offenders.append(path)
        self.assertEqual(offenders, [])

    def test_install_example_list_uses_real_package_names(self):
        """source: the example list named a missing npm package, deprecated packages, and plain names discover looks up as unrelated packages"""
        env = isolated_env(self.home)
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
        example = (self.mcm_home / "cache" / "mcp-list-example.txt").read_text()
        self.assertNotIn("server-playwright", example)
        self.assertNotIn("server-slack", example)
        lines = example.splitlines()
        self.assertNotIn("github", lines)
        self.assertNotIn("postgres", lines)
        self.assertNotIn("filesystem", lines)
        self.assertIn("@modelcontextprotocol/server-filesystem", example)
        self.assertIn("@modelcontextprotocol/server-memory", example)
        self.assertIn("@playwright/mcp", example)
        engine_mod = load_engine(self.mcm_home)
        engine = engine_mod.MCMEngine()
        checked = 0
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parsed = engine.parse_mcp_input(stripped + "\n")
            self.assertEqual(len(parsed), 1, line)
            self.assertNotEqual(parsed[0]["type"], "invalid", line)
            checked += 1
        self.assertGreater(checked, 0)
        self.assertIn(
            "3. Wait for discovery to finish (a few seconds per name)",
            proc.stdout,
        )

    def test_readme_drops_any_format_search_and_long_dash(self):
        """source: the README said discover takes any format and that you can search and compare"""
        text = (REPO_ROOT / "README.md").read_text()
        self.assertNotIn("(any format)", text)
        self.assertNotIn("search, review, and compare", text)
        self.assertNotIn("\u2014", text)


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

    def test_parse_rejects_traversal_and_paths(self):
        """source: untrusted-input-to-authenticated-request-and-path"""
        engine_mod = load_engine(self.mcm_home)
        engine = engine_mod.MCMEngine()
        lines = [
            "https://github.com/owner/repo/../../user",
            "https://github.com/owner/repo.git",
            "https://github.com/owner/..",
            "@scope/pkg",
            "../etc/passwd",
            "/srv/mcp/server.js",
            "name with spaces",
            "filesystem",
        ]
        parsed = engine.parse_mcp_input("\n".join(lines))
        by_original = dict((item["original"], item) for item in parsed)
        self.assertEqual(
            by_original["https://github.com/owner/repo/../../user"]["type"], "invalid"
        )
        self.assertEqual(
            by_original["https://github.com/owner/repo.git"]["type"], "github_url"
        )
        self.assertEqual(
            by_original["https://github.com/owner/repo.git"]["identifier"], "owner/repo"
        )
        self.assertEqual(by_original["https://github.com/owner/.."]["type"], "invalid")
        self.assertEqual(by_original["@scope/pkg"]["type"], "npm_package")
        self.assertEqual(by_original["../etc/passwd"]["type"], "invalid")
        self.assertEqual(by_original["/srv/mcp/server.js"]["type"], "invalid")
        self.assertEqual(by_original["name with spaces"]["type"], "invalid")
        self.assertEqual(by_original["filesystem"]["type"], "npm_package")

    def test_parse_accepts_schemeless_and_tree_github_links(self):
        """source: push review of 5034ea7: scheme-less and /tree/ GitHub links were refused"""
        engine_mod = load_engine(self.mcm_home)
        engine = engine_mod.MCMEngine()
        parsed = engine.parse_mcp_input(
            "\n".join(
                [
                    "github.com/owner/repo",
                    "https://github.com/owner/repo/tree/main/src/filesystem",
                    "https://github.com/owner/repo/../../user",
                    "https://github.com/owner/repo/issues/1",
                ]
            )
        )
        by_original = dict((item["original"], item) for item in parsed)
        self.assertEqual(by_original["github.com/owner/repo"]["type"], "github_url")
        self.assertEqual(
            by_original["github.com/owner/repo"]["identifier"], "owner/repo"
        )
        tree_url = "https://github.com/owner/repo/tree/main/src/filesystem"
        self.assertEqual(by_original[tree_url]["type"], "github_url")
        self.assertEqual(by_original[tree_url]["identifier"], "owner/repo")
        self.assertEqual(
            by_original["https://github.com/owner/repo/../../user"]["type"], "invalid"
        )
        self.assertEqual(
            by_original["https://github.com/owner/repo/issues/1"]["type"], "invalid"
        )


class HttpRequestTests(IsolatedHomeTest):
    def test_http_request_success_http_error_and_url_error(self):
        """source: engine called requests.get/post instead of stdlib HTTP"""
        engine_mod = load_engine(self.mcm_home)

        with patch.object(
            engine_mod,
            "open_url",
            return_value=FakeHTTPResponse(200, "ok-body"),
        ):
            status, text = engine_mod.http_request("GET", "http://example.test/ok")
        self.assertEqual(status, 200)
        self.assertEqual(text, "ok-body")

        with patch.object(
            engine_mod,
            "open_url",
            side_effect=make_http_error("http://example.test/missing", 404, "nope"),
        ):
            status, text = engine_mod.http_request("GET", "http://example.test/missing")
        self.assertEqual(status, 404)
        self.assertEqual(text, "nope")

        with patch.object(
            engine_mod,
            "open_url",
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

        with patch.object(engine_mod, "open_url", side_effect=capture_urlopen):
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

    def test_cross_host_redirect_is_refused(self):
        """source: credential-leak-on-redirect"""
        engine_mod = load_engine(self.mcm_home)
        b_requests = []

        class BHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_GET(self):
                b_requests.append(dict(self.headers))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

        class AHandler(BaseHTTPRequestHandler):
            b_port = 0

            def log_message(self, format, *args):
                return

            def do_GET(self):
                self.send_response(302)
                self.send_header(
                    "Location",
                    "http://127.0.0.1:%d/steal" % AHandler.b_port,
                )
                self.end_headers()

        server_b = ThreadingHTTPServer(("127.0.0.1", 0), BHandler)
        server_a = ThreadingHTTPServer(("127.0.0.1", 0), AHandler)
        AHandler.b_port = server_b.server_address[1]
        thread_b = threading.Thread(target=server_b.serve_forever, daemon=True)
        thread_a = threading.Thread(target=server_a.serve_forever, daemon=True)
        thread_b.start()
        thread_a.start()
        try:
            a_port = server_a.server_address[1]
            status, text = engine_mod.http_request(
                "GET",
                "http://127.0.0.1:%d/start" % a_port,
                headers={"x-api-key": "k", "Authorization": "token t"},
            )
            self.assertEqual(status, 302)
            self.assertEqual(b_requests, [])
        finally:
            server_a.shutdown()
            server_b.shutdown()
            server_a.server_close()
            server_b.server_close()

    def test_same_host_redirect_is_followed(self):
        """source: credential-leak-on-redirect"""
        engine_mod = load_engine(self.mcm_home)

        class AHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_GET(self):
                port = self.server.server_address[1]
                if self.path == "/start":
                    self.send_response(302)
                    self.send_header(
                        "Location",
                        "http://127.0.0.1:%d/end" % port,
                    )
                    self.end_headers()
                elif self.path == "/end":
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"done")
                else:
                    self.send_response(404)
                    self.end_headers()

        server_a = ThreadingHTTPServer(("127.0.0.1", 0), AHandler)
        thread_a = threading.Thread(target=server_a.serve_forever, daemon=True)
        thread_a.start()
        try:
            a_port = server_a.server_address[1]
            status, text = engine_mod.http_request(
                "GET",
                "http://127.0.0.1:%d/start" % a_port,
            )
            self.assertEqual(status, 200)
            self.assertEqual(text, "done")
        finally:
            server_a.shutdown()
            server_a.server_close()

    def test_malformed_location_header_does_not_raise(self):
        """source: push review of 5034ea7: a malformed Location header made the redirect guard raise"""
        engine_mod = load_engine(self.mcm_home)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:99999999/x")
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            try:
                status, text = engine_mod.http_request(
                    "GET",
                    "http://127.0.0.1:%d/start" % port,
                )
            except ValueError as exc:
                self.fail(
                    "the redirect guard raised on a malformed Location: %r" % (exc,)
                )
            self.assertEqual(status, 302)
        finally:
            server.shutdown()
            server.server_close()

    def test_http_error_explains_refused_redirect(self):
        """source: push review of 5034ea7: a refused redirect read as a bare 302"""
        engine_mod = load_engine(self.mcm_home)
        self.assertEqual(
            str(engine_mod.http_error("GitHub API error", 302, "")),
            "GitHub API error: 302 (a redirect to another host was refused)",
        )
        self.assertEqual(
            str(engine_mod.http_error("GitHub API error", 404, "")),
            "GitHub API error: 404",
        )


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

    def test_npm_lookup_says_what_it_sends(self):
        """source: information-disclosure-to-third-party"""
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
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                engine.discover_from_npm(
                    {"identifier": "demo-mcp", "type": "npm_package"}
                )
        self.assertIn("  → registry.npmjs.org: demo-mcp", buf.getvalue())

    def test_discover_from_npm_connection_error_includes_reason(self):
        """source: a lookup that could not connect raised 'NPM registry error: 0' and dropped the reason"""
        engine_mod = load_engine(self.mcm_home)
        engine = engine_mod.MCMEngine()
        with patch.object(engine_mod, "http_request", return_value=(0, "network down")):
            with self.assertRaises(Exception) as ctx:
                engine.discover_from_npm({"identifier": "demo-mcp", "type": "npm_package"})
        self.assertIn("could not connect (network down)", str(ctx.exception))

    def test_discover_from_github_skips_source_files_and_announces_package_json(self):
        """source: push review of 5034ea7: discover fetched source files to guess tools and did not announce its package.json request"""
        engine_mod = load_engine(self.mcm_home)
        recorded = []

        def fake_http(method, url, headers=None, json_body=None, timeout=30):
            recorded.append(url)
            if "api.github.com" in url:
                return (
                    200,
                    json.dumps(
                        {
                            "name": "repo",
                            "html_url": "https://github.com/owner/repo",
                            "description": "d",
                        }
                    ),
                )
            return (404, "")

        engine = engine_mod.MCMEngine()
        buf = io.StringIO()
        with patch.object(engine_mod, "http_request", side_effect=fake_http):
            with contextlib.redirect_stdout(buf):
                metadata = engine.discover_from_github(
                    {"identifier": "owner/repo", "type": "github_url"}
                )
        self.assertEqual(metadata.tools, [])
        self.assertEqual(metadata.tool_count, 0)
        for url in recorded:
            self.assertNotIn("/src/", url)
            self.assertFalse(url.endswith(".ts") or url.endswith(".js"))
        self.assertIn(
            "  → raw.githubusercontent.com: owner/repo package.json",
            buf.getvalue(),
        )

    def test_github_repo_from_known_forms_and_rejections(self):
        """source: review: a string repository or an ssh address was not turned into owner/repo"""
        engine_mod = load_engine(self.mcm_home)
        forms = [
            "https://github.com/owner/repo",
            "https://github.com/owner/repo.git",
            "https://github.com/owner/repo/",
            "https://github.com/owner/repo.git/",
            "https://github.com/owner/repo#fragment",
            "https://github.com/owner/repo/tree/main",
            "https://github.com/owner/repo/tree/main/src",
            "git+https://github.com/owner/repo.git",
            "git://github.com/owner/repo.git",
            "git@github.com:owner/repo.git",
            "ssh://git@github.com/owner/repo.git",
            "github:owner/repo",
            "owner/repo",
            {"url": "https://github.com/owner/repo.git"},
            {"type": "git", "url": "git+https://github.com/owner/repo.git"},
        ]
        for form in forms:
            self.assertEqual(
                engine_mod.github_repo_from(form),
                "owner/repo",
                form,
            )
        for form in (
            "https://gitlab.com/owner/repo",
            "git@example.test:owner/repo.git",
            "owner/../x",
            None,
            42,
        ):
            self.assertIsNone(engine_mod.github_repo_from(form), form)

    def test_discover_from_npm_string_repository_asks_github(self):
        """source: review: an npm repository string raised AttributeError"""
        engine_mod = load_engine(self.mcm_home)
        npm_doc = {
            "name": "string-repo",
            "dist-tags": {"latest": "1.0.0"},
            "versions": {
                "1.0.0": {
                    "description": "from npm",
                    "repository": "github:owner/repo",
                }
            },
        }
        recorded = []

        def fake_http(method, url, headers=None, json_body=None, timeout=30):
            recorded.append(url)
            if "registry.npmjs.org" in url:
                return (200, json.dumps(npm_doc))
            if url == "https://api.github.com/repos/owner/repo":
                return (
                    200,
                    json.dumps(
                        {
                            "name": "repo",
                            "html_url": "https://github.com/owner/repo",
                            "description": "from github",
                            "default_branch": "main",
                        }
                    ),
                )
            return (404, "")

        engine = engine_mod.MCMEngine()
        with patch.object(engine_mod, "http_request", side_effect=fake_http):
            metadata = engine.discover_from_npm(
                {"identifier": "string-repo", "type": "npm_package"}
            )
        self.assertIn("https://api.github.com/repos/owner/repo", recorded)
        self.assertEqual(metadata.name, "string-repo")

    def test_discover_from_npm_keeps_npm_details_when_github_fails(self):
        """source: review: a failed GitHub lookup discarded the npm details already fetched"""
        engine_mod = load_engine(self.mcm_home)
        npm_doc = {
            "name": "blocked-mcp",
            "dist-tags": {"latest": "1.0.0"},
            "versions": {
                "1.0.0": {
                    "description": "Saved anyway",
                    "repository": {"url": "https://github.com/owner/repo"},
                    "dependencies": {"left-pad": "1.0.0"},
                }
            },
        }

        def fake_http(method, url, headers=None, json_body=None, timeout=30):
            if "registry.npmjs.org" in url:
                return (200, json.dumps(npm_doc))
            if "api.github.com" in url:
                return (403, "")
            return (404, "")

        engine = engine_mod.MCMEngine()
        buf = io.StringIO()
        try:
            with patch.object(engine_mod, "http_request", side_effect=fake_http):
                with contextlib.redirect_stdout(buf):
                    metadata = engine.discover_from_npm(
                        {"identifier": "blocked-mcp", "type": "npm_package"}
                    )
        except Exception as exc:
            self.fail(
                "a failed GitHub lookup aborted npm discovery: %s" % exc
            )
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.name, "blocked-mcp")
        self.assertEqual(metadata.source, "npm")
        self.assertEqual(metadata.description, "Saved anyway")
        self.assertEqual(metadata.dependencies, ["left-pad"])
        self.assertEqual(
            metadata.url, "https://www.npmjs.com/package/blocked-mcp"
        )
        self.assertIn("GitHub details unavailable", buf.getvalue())

    def test_discover_from_github_reads_default_branch_package_json(self):
        """source: review: package.json was read from main before the repository default branch"""
        engine_mod = load_engine(self.mcm_home)
        recorded = []

        def fake_http(method, url, headers=None, json_body=None, timeout=30):
            recorded.append(url)
            if "api.github.com" in url:
                return (
                    200,
                    json.dumps(
                        {
                            "name": "repo",
                            "html_url": "https://github.com/owner/repo",
                            "description": "d",
                            "default_branch": "trunk",
                        }
                    ),
                )
            return (404, "")

        engine = engine_mod.MCMEngine()
        with patch.object(engine_mod, "http_request", side_effect=fake_http):
            engine.discover_from_github(
                {"identifier": "owner/repo", "type": "github_url"}
            )
        pkg_urls = [url for url in recorded if url.endswith("/package.json")]
        trunk = "https://raw.githubusercontent.com/owner/repo/trunk/package.json"
        main = "https://raw.githubusercontent.com/owner/repo/main/package.json"
        master = "https://raw.githubusercontent.com/owner/repo/master/package.json"
        self.assertIn(trunk, pkg_urls)
        self.assertLess(pkg_urls.index(trunk), pkg_urls.index(main))
        self.assertLess(pkg_urls.index(trunk), pkg_urls.index(master))

    def test_default_branch_is_quoted_in_the_raw_address(self):
        """source: a default_branch with a space or hash was placed raw in the package.json address"""
        engine_mod = load_engine(self.mcm_home)
        recorded = []

        def fake_http(method, url, headers=None, json_body=None, timeout=30):
            recorded.append(url)
            if "api.github.com" in url:
                return (
                    200,
                    json.dumps(
                        {
                            "name": "repo",
                            "html_url": "https://github.com/owner/repo",
                            "description": "d",
                            "default_branch": "release/1.0 #x",
                        }
                    ),
                )
            return (404, "")

        engine = engine_mod.MCMEngine()
        with patch.object(engine_mod, "http_request", side_effect=fake_http):
            engine.discover_from_github(
                {"identifier": "owner/repo", "type": "github_url"}
            )
        expected = (
            "https://raw.githubusercontent.com/owner/repo/"
            "release/1.0%20%23x/package.json"
        )
        self.assertIn(expected, recorded)

    def test_github_null_description_is_saved_as_empty_string(self):
        """source: review: a null GitHub description was saved as None"""
        engine_mod = load_engine(self.mcm_home)

        def fake_http(method, url, headers=None, json_body=None, timeout=30):
            if "api.github.com" in url:
                return (
                    200,
                    json.dumps(
                        {
                            "name": "repo",
                            "html_url": "https://github.com/owner/repo",
                            "description": None,
                        }
                    ),
                )
            return (404, "")

        engine = engine_mod.MCMEngine()
        with patch.object(engine_mod, "http_request", side_effect=fake_http):
            metadata = engine.discover_from_github(
                {"identifier": "owner/repo", "type": "github_url"}
            )
        self.assertIsInstance(metadata.description, str)
        self.assertEqual(metadata.description, "")
        engine.save_metadata(metadata)
        saved = json.loads(
            (self.mcm_home / "registry" / "repo" / "metadata.json").read_text()
        )
        self.assertEqual(saved["description"], "")

    def test_registry_descriptions_drop_control_characters(self):
        """source: review: GitHub and npm descriptions were saved with terminal control characters"""
        engine_mod = load_engine(self.mcm_home)
        hostile = "hello\u001b[31m\u009b"
        npm_doc = {
            "name": "demo-mcp",
            "dist-tags": {"latest": "1.0.0"},
            "versions": {
                "1.0.0": {
                    "description": hostile,
                    "repository": {"url": "git+https://gitlab.com/example/demo-mcp.git"},
                }
            },
        }

        def fake_npm(method, url, headers=None, json_body=None, timeout=30):
            return (200, json.dumps(npm_doc))

        engine = engine_mod.MCMEngine()
        with patch.object(engine_mod, "http_request", side_effect=fake_npm):
            npm_meta = engine.discover_from_npm(
                {"identifier": "demo-mcp", "type": "npm_package"}
            )
        self.assertEqual(npm_meta.description, "hello[31m")

        def fake_github(method, url, headers=None, json_body=None, timeout=30):
            if "api.github.com" in url:
                return (
                    200,
                    json.dumps(
                        {
                            "name": "repo",
                            "html_url": "https://github.com/owner/repo",
                            "description": hostile,
                        }
                    ),
                )
            return (404, "")

        with patch.object(engine_mod, "http_request", side_effect=fake_github):
            github_meta = engine.discover_from_github(
                {"identifier": "owner/repo", "type": "github_url"}
            )
        self.assertEqual(github_meta.description, "hello[31m")
        for ch in github_meta.description + npm_meta.description:
            self.assertGreaterEqual(ord(ch), 32)
            self.assertFalse(0x80 <= ord(ch) <= 0x9F)

    def test_descriptions_keep_a_space_for_newline_and_tab(self):
        """source: a newline or tab in a description was deleted when control characters were stripped"""
        engine_mod = load_engine(self.mcm_home)

        def fake_http(method, url, headers=None, json_body=None, timeout=30):
            if "api.github.com" in url:
                return (
                    200,
                    json.dumps(
                        {
                            "name": "repo",
                            "html_url": "https://github.com/owner/repo",
                            "description": "first line\nsecond\tline",
                        }
                    ),
                )
            return (404, "")

        engine = engine_mod.MCMEngine()
        with patch.object(engine_mod, "http_request", side_effect=fake_http):
            metadata = engine.discover_from_github(
                {"identifier": "owner/repo", "type": "github_url"}
            )
        self.assertEqual(metadata.description, "first line second line")
        engine.save_metadata(metadata)
        saved = json.loads(
            (self.mcm_home / "registry" / "repo" / "metadata.json").read_text()
        )
        self.assertEqual(saved["description"], "first line second line")
        tools, _tokens = engine_mod.inspect_command(
            [sys.executable, FAKE, "spacing"], timeout=10
        )
        self.assertEqual(tools[0]["description"], "first second")
        self.assertIn(" ", tools[0]["description"])
        self.assertNotIn("\n", tools[0]["description"])


class InputSafetyTests(IsolatedHomeTest):
    def test_invalid_entry_sends_nothing(self):
        """source: untrusted-input-to-authenticated-request-and-path"""
        engine_mod = load_engine(self.mcm_home)
        engine = engine_mod.MCMEngine()
        parsed = engine.parse_mcp_input("../etc/passwd")
        self.assertEqual(len(parsed), 1)
        mock_http = Mock()
        with patch.object(engine_mod, "http_request", mock_http):
            result = engine.discover_mcp(parsed[0])
            self.assertIsNone(result)
            mock_http.assert_not_called()
            with self.assertRaises(Exception):
                engine.discover_from_github(
                    {"identifier": "owner/repo/../../user", "type": "github_url"}
                )
            mock_http.assert_not_called()

    def test_safe_child_refuses_escapes(self):
        """source: untrusted-input-to-authenticated-request-and-path"""
        engine_mod = load_engine(self.mcm_home)
        engine = engine_mod.MCMEngine()
        root = self.mcm_home / "registry"
        with self.assertRaises(ValueError):
            engine_mod.safe_child(root, "../x")
        with self.assertRaises(ValueError):
            engine_mod.safe_child(root, "a/../../x")
        with self.assertRaises(ValueError):
            engine_mod.safe_child(root, "/etc/x")
        child = engine_mod.safe_child(root, "@scope/pkg")
        self.assertTrue(child.is_relative_to(root.resolve()))
        self.assertNotEqual(child, root.resolve())

        metadata = engine_mod.MCPMetadata(
            name="../escape",
            source="npm",
            url="http://example.test",
            description="",
            tools=[],
            tool_count=0,
            complexity_score=0.0,
            context_cost_estimate=0,
            dependencies=[],
            credentials_needed=[],
            discovered_at="2020-01-01T00:00:00Z",
            format="direct",
        )
        with self.assertRaises(ValueError):
            engine.save_metadata(metadata)
        self.assertFalse((self.mcm_home / "escape").exists())

    def test_no_search_service(self):
        """source: information-disclosure-to-third-party: a plain name went to Exa's search API"""
        engine_mod = load_engine(self.mcm_home)
        engine = engine_mod.MCMEngine()
        mock_http = Mock()
        old_exa = os.environ.get("EXA_API_KEY")
        os.environ["EXA_API_KEY"] = "test-key"
        try:
            with patch.object(engine_mod, "http_request", mock_http):
                buf = io.StringIO()
                err = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                    result = engine.discover_mcp(
                        {
                            "type": "name",
                            "identifier": "plainname",
                            "original": "plainname",
                        }
                    )
            self.assertIsNone(result)
            mock_http.assert_not_called()
            combined = buf.getvalue() + err.getvalue()
            self.assertIn("Skipped 'plainname'", combined)
        finally:
            if old_exa is None:
                os.environ.pop("EXA_API_KEY", None)
            else:
                os.environ["EXA_API_KEY"] = old_exa


class EngineMainTests(IsolatedHomeTest):
    def test_discover_exits_1_when_every_mcp_fails(self):
        """source: the engine exited 0 and the script printed Discovery complete when every MCP failed"""
        engine_mod = load_engine(self.mcm_home)
        list_file = self.tmp / "mcp-list.txt"
        list_file.write_text("demo-mcp\n")
        with patch.object(engine_mod, "http_request", return_value=(404, "")), \
             patch.object(engine_mod.time, "sleep"), \
             patch.object(engine_mod.sys, "argv", ["mcm_engine.py", "discover", str(list_file)]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                with self.assertRaises(SystemExit) as ctx:
                    engine_mod.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("Discovered 0 of 1", buf.getvalue())

    def test_discover_exit_codes_for_partial_and_empty_lists(self):
        """source: discover exited 0 when some names failed, so the script said discovery was complete"""
        engine_mod = load_engine(self.mcm_home)

        def meta(name):
            return engine_mod.MCPMetadata(
                name=name,
                source="npm",
                url="http://example.test",
                description="",
                tools=[],
                tool_count=0,
                complexity_score=0.0,
                context_cost_estimate=0,
                dependencies=[],
                credentials_needed=[],
                discovered_at="2020-01-01T00:00:00Z",
                format="direct",
            )

        def run(text, results):
            list_file = self.tmp / "exit-codes.txt"
            list_file.write_text(text)
            with patch.object(
                engine_mod.MCMEngine, "discover_mcp", side_effect=results
            ), patch.object(engine_mod.time, "sleep"), patch.object(
                engine_mod.sys,
                "argv",
                ["mcm_engine.py", "discover", str(list_file)],
            ):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    try:
                        engine_mod.main()
                        code = 0
                    except SystemExit as exc:
                        code = exc.code
            return code, buf.getvalue()

        code, out = run("alpha-mcp\nbeta-mcp\n", [meta("alpha-mcp"), meta("beta-mcp")])
        self.assertEqual(code, 0)
        self.assertIn("Discovered 2 of 2", out)

        code, out = run("alpha-mcp\nbeta-mcp\n", [meta("alpha-mcp"), None])
        self.assertEqual(code, 2)
        self.assertIn("Discovered 1 of 2", out)

        code, out = run("alpha-mcp\nbeta-mcp\n", [None, None])
        self.assertEqual(code, 1)
        self.assertIn("Discovered 0 of 2", out)

        code, out = run("", [])
        self.assertEqual(code, 0)
        self.assertIn("Discovered 0 of 0", out)

    def test_discover_continues_when_save_refuses_a_name(self):
        """source: push review of 5034ea7: a refused registry name aborted the whole run"""
        engine_mod = load_engine(self.mcm_home)
        list_file = self.tmp / "mcp-list.txt"
        list_file.write_text("bad-mcp\ngood-mcp\n")
        metas = [
            engine_mod.MCPMetadata(
                name="../escape",
                source="npm",
                url="http://example.test",
                description="",
                tools=[],
                tool_count=0,
                complexity_score=0.0,
                context_cost_estimate=0,
                dependencies=[],
                credentials_needed=[],
                discovered_at="2020-01-01T00:00:00Z",
                format="direct",
            ),
            engine_mod.MCPMetadata(
                name="good-mcp",
                source="npm",
                url="http://example.test",
                description="",
                tools=[],
                tool_count=0,
                complexity_score=0.0,
                context_cost_estimate=0,
                dependencies=[],
                credentials_needed=[],
                discovered_at="2020-01-01T00:00:00Z",
                format="direct",
            ),
        ]
        with patch.object(
            engine_mod.MCMEngine, "discover_mcp", side_effect=metas
        ), patch.object(engine_mod.time, "sleep"), patch.object(
            engine_mod.sys,
            "argv",
            ["mcm_engine.py", "discover", str(list_file)],
        ):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    engine_mod.main()
                    code = 0
                except SystemExit as exc:
                    code = exc.code
                except (ValueError, OSError) as exc:
                    self.fail("a refused registry name escaped main: %r" % (exc,))
        self.assertEqual(code, 2)
        out = buf.getvalue()
        self.assertIn("../escape: not saved", out)
        self.assertIn("Discovered 1 of 2", out)
        index_path = self.mcm_home / "registry" / "index.json"
        with open(str(index_path)) as handle:
            index = json.load(handle)
        names = [item["name"] for item in index.get("mcps", [])]
        self.assertIn("good-mcp", names)

    def test_engine_runs_without_deprecation_warnings(self):
        """source: every engine run printed datetime.utcnow() DeprecationWarnings on Python 3.12 and newer"""
        list_file = self.tmp / "mcp-list.txt"
        list_file.write_text("../not-a-package\n")
        env = isolated_env(self.home)
        proc = subprocess.run(
            [
                sys.executable,
                "-W",
                "error::DeprecationWarning",
                str(SRC_DIR / "mcm_engine.py"),
                "discover",
                str(list_file),
            ],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        combined = proc.stdout + proc.stderr
        self.assertNotIn("DeprecationWarning", combined)
        self.assertNotIn("Traceback", combined)
        self.assertIn("Discovered 0 of 1", combined)

    def test_engine_cli_usage_unknown_command_and_list(self):
        """source: review: an unknown command printed nothing, a missing list file traced back, and list assumed keys"""
        engine = str(SRC_DIR / "mcm_engine.py")
        env = isolated_env(self.home)

        def run(args):
            return subprocess.run(
                [sys.executable, engine] + args,
                cwd=str(self.tmp),
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )

        for args in ([], ["--help"], ["-h"]):
            proc = run(args)
            combined = proc.stdout + proc.stderr
            self.assertEqual(proc.returncode, 0, combined)
            for word in ("discover", "inspect", "scan-config", "list"):
                self.assertIn(word, combined)

        bogus = run(["bogus"])
        bogus_text = bogus.stdout + bogus.stderr
        self.assertEqual(bogus.returncode, 1, bogus_text)
        self.assertIn("unknown command bogus", bogus_text)
        self.assertIn("discover", bogus_text)
        self.assertNotIn("Traceback", bogus_text)

        missing = self.tmp / "missing-mcp-list.txt"
        discover = run(["discover", str(missing)])
        discover_text = discover.stdout + discover.stderr
        self.assertEqual(discover.returncode, 1, discover_text)
        self.assertIn("cannot read", discover_text)
        self.assertIn(str(missing), discover_text)
        self.assertNotIn("Traceback", discover_text)

        blocked = self.tmp / "unreadable-mcp-list.txt"
        blocked.write_text("../not-a-package\n")
        os.chmod(str(blocked), 0)
        try:
            if os.geteuid() != 0 and not os.access(str(blocked), os.R_OK):
                denied = run(["discover", str(blocked)])
                denied_text = denied.stdout + denied.stderr
                self.assertEqual(denied.returncode, 1, denied_text)
                self.assertIn("cannot read", denied_text)
                self.assertNotIn("Traceback", denied_text)
        finally:
            os.chmod(str(blocked), 0o644)

        empty = run(["list"])
        empty_text = empty.stdout + empty.stderr
        self.assertIn("No MCPs discovered yet.", empty_text)
        self.assertNotIn("mcm discover", empty_text)
        self.assertNotIn("Traceback", empty_text)

        registry = self.mcm_home / "registry"
        registry.mkdir(parents=True, exist_ok=True)
        (registry / "index.json").write_text(
            json.dumps({"mcps": [{"name": "partial"}]})
        )
        listed = run(["list"])
        listed_text = listed.stdout + listed.stderr
        self.assertEqual(listed.returncode, 0, listed_text)
        self.assertIn("partial", listed_text)
        self.assertNotIn("Traceback", listed_text)

    def test_list_corrupt_index_is_reported_without_traceback(self):
        """source: mcm list printed a traceback when the registry index was not valid JSON"""
        registry = self.mcm_home / "registry"
        registry.mkdir(parents=True)
        index_path = registry / "index.json"
        index_path.write_text("{not json")
        env = isolated_env(self.home)
        proc = subprocess.run(
            [sys.executable, str(SRC_DIR / "mcm_engine.py"), "list"],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        combined = proc.stdout + proc.stderr
        expected = (
            "The registry index is not valid JSON: %s. Move it aside and run discover again."
            % index_path
        )
        self.assertEqual(proc.returncode, 1, combined)
        self.assertIn(expected, combined)
        self.assertNotIn("Traceback", combined)


class ScanConfigTests(IsolatedHomeTest):
    def test_scan_claude_config_reads_packages_and_skips_aliases(self):
        """source: menu option 3 fed config aliases such as 'github' to npm lookups"""
        engine_mod = load_engine(self.mcm_home)
        project_dir = self.tmp / "project"
        project_dir.mkdir()
        (project_dir / ".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "fs": {
                            "command": "npx",
                            "args": [
                                "-y",
                                "@modelcontextprotocol/server-filesystem@1.2.0",
                                "/tmp",
                            ],
                        },
                        "remote": {
                            "type": "http",
                            "url": "https://example.test/mcp",
                        },
                    }
                }
            )
        )
        (self.home / ".claude.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "gh": {
                            "command": "/usr/local/bin/npx",
                            "args": ["@modelcontextprotocol/server-github"],
                        }
                    },
                    "projects": {
                        "/x": {
                            "mcpServers": {
                                "fs2": {
                                    "command": "npx",
                                    "args": [
                                        "-y",
                                        "@modelcontextprotocol/server-filesystem",
                                    ],
                                },
                                "local": {
                                    "command": "node",
                                    "args": ["server.js"],
                                },
                                "plain": {
                                    "command": "bunx",
                                    "args": ["some-mcp@latest"],
                                },
                            }
                        }
                    },
                }
            )
        )
        packages, skipped = engine_mod.scan_claude_config(project_dir, self.home)
        self.assertEqual(
            packages,
            [
                "@modelcontextprotocol/server-filesystem",
                "@modelcontextprotocol/server-github",
                "some-mcp",
            ],
        )
        self.assertEqual(
            skipped,
            [
                "remote: not started with npx or bunx",
                "local: not started with npx or bunx",
            ],
        )

    def test_scan_claude_config_survives_bad_files(self):
        """source: a malformed config file stopped the scan"""
        engine_mod = load_engine(self.mcm_home)
        project_dir = self.tmp / "project"
        project_dir.mkdir()
        (project_dir / ".mcp.json").write_text("{not json")
        (self.home / ".claude.json").write_text('["a list"]')
        try:
            packages, skipped = engine_mod.scan_claude_config(project_dir, self.home)
        except Exception as exc:
            self.fail("scan_claude_config raised %r" % (exc,))
        self.assertEqual(packages, [])
        self.assertEqual(skipped, [])


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

    def test_discover_reports_failure_when_engine_fails(self):
        """source: discover.sh printed Discovery complete after the engine failed"""
        scripts = install_copy(self.home)
        stub_path = scripts / "mcm_engine.py"
        stub_path.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "print('stub failing')\n"
            "sys.exit(1)\n"
        )
        env = isolated_env(self.home)
        proc = subprocess.run(
            ["bash", str(scripts / "discover.sh"), "alpha"],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 1)
        combined = proc.stdout + proc.stderr
        self.assertIn("Discovery failed: no MCP could be read.", combined)
        self.assertNotIn("Discovery complete", combined)
        cache = Path(self.home) / ".mcm" / "cache"
        leftovers = list(cache.glob("mcp-input-*.txt"))
        self.assertEqual(leftovers, [])

    def test_discover_sh_reports_partial_failure_and_complete(self):
        """source: discover.sh said discovery was complete when some names failed"""
        scripts = install_copy(self.home)
        stub_path = scripts / "mcm_engine.py"
        env = isolated_env(self.home)
        cache = Path(self.home) / ".mcm" / "cache"

        stub_path.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "sys.exit(2)\n"
        )
        partial = subprocess.run(
            ["bash", str(scripts / "discover.sh"), "alpha"],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        partial_text = partial.stdout + partial.stderr
        self.assertEqual(partial.returncode, 2, partial_text)
        self.assertIn("Discovery finished with failures", partial_text)
        self.assertIn("Next steps:", partial_text)
        self.assertIn("1. Review: cat ", partial_text)
        self.assertIn("2. Validate: mcm validate", partial_text)
        self.assertNotIn("Discovery complete", partial_text)
        self.assertEqual(list(cache.glob("mcp-input-*.txt")), [])

        stub_path.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "sys.exit(0)\n"
        )
        done = subprocess.run(
            ["bash", str(scripts / "discover.sh"), "alpha"],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        done_text = done.stdout + done.stderr
        self.assertEqual(done.returncode, 0, done_text)
        self.assertIn("Discovery complete", done_text)
        self.assertEqual(list(cache.glob("mcp-input-*.txt")), [])

    def test_discover_sh_removes_temp_input_on_every_exit(self):
        """source: review: discover.sh left its temporary input file behind on some exits"""
        env = isolated_env(self.home)
        discover = str(SRC_DIR / "commands" / "discover.sh")
        cache = self.mcm_home / "cache"

        def leftovers():
            if not cache.exists():
                return []
            return list(cache.glob("mcp-input-*"))

        failed = subprocess.run(
            ["bash", discover, "../not-a-package"],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        failed_text = failed.stdout + failed.stderr
        self.assertEqual(failed.returncode, 1, failed_text)
        self.assertIn("Discovery failed", failed_text)
        self.assertNotIn("was not found", failed_text)
        self.assertNotIn("No such file", failed_text)
        self.assertEqual(leftovers(), [])

        empty = subprocess.run(
            ["bash", discover],
            cwd=str(self.tmp),
            env=env,
            input="",
            capture_output=True,
            text=True,
            timeout=30,
        )
        empty_text = empty.stdout + empty.stderr
        self.assertEqual(empty.returncode, 1, empty_text)
        self.assertIn("No MCP names given", empty_text)
        self.assertEqual(leftovers(), [])

        stub_dir = self.tmp / "stub-layout"
        stub_dir.mkdir()
        shutil.copy(
            str(SRC_DIR / "commands" / "discover.sh"),
            str(stub_dir / "discover.sh"),
        )
        (stub_dir / "mcm_engine.py").write_text(
            "#!/usr/bin/env python3\nimport sys\nsys.exit(1)\n"
        )
        stub = subprocess.run(
            ["bash", str(stub_dir / "discover.sh"), "alpha"],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        stub_text = stub.stdout + stub.stderr
        self.assertEqual(stub.returncode, 1, stub_text)
        self.assertIn("Discovery failed", stub_text)
        self.assertEqual(leftovers(), [])


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
        self.assertNotIn("search <query>", help_text)

    def test_help_prints_no_raw_color_codes(self):
        """source: mcm help printed raw color codes such as \\033[1m"""
        main = SRC_DIR / "commands" / "main.sh"
        env = isolated_env(self.home)
        proc = subprocess.run(
            ["bash", str(main), "help"],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        combined = proc.stdout + proc.stderr
        self.assertNotIn("\\033", combined)
        self.assertIn("Commands:", combined)

    def test_main_through_symlink_runs_help_and_status(self):
        """source: review: a symlink to main.sh left SCRIPT_DIR unresolved, so commands could not find sibling scripts"""
        scripts = install_copy(self.home)
        link_dir = self.tmp / "elsewhere"
        link_dir.mkdir()
        link = link_dir / "mcm"
        os.symlink(os.path.relpath(str(scripts / "main.sh"), str(link_dir)), str(link))
        env = isolated_env(self.home)
        help_proc = subprocess.run(
            [str(link), "help"],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(
            help_proc.returncode,
            0,
            help_proc.stdout + help_proc.stderr,
        )

        registry = self.mcm_home / "registry"
        registry.mkdir(parents=True, exist_ok=True)
        (registry / "index.json").write_text(json.dumps({"mcps": []}))
        status_proc = subprocess.run(
            [str(link), "status"],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(
            status_proc.returncode,
            0,
            status_proc.stdout + status_proc.stderr,
        )

    def test_main_sh_from_repo_reaches_the_engine(self):
        """source: review: scripts found the engine only in the installed flat layout"""
        env = isolated_env(self.home)
        proc = subprocess.run(
            ["bash", "src/commands/main.sh", "inspect", "../evil", "--yes"],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        combined = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 1, combined)
        self.assertIn("not an npm package name", combined)
        self.assertNotIn("No such file", combined)

    def test_main_sh_missing_engine_reports_the_search(self):
        """source: review: scripts found the engine only in the installed flat layout"""
        lone = self.tmp / "no-engine" / "commands"
        lone.mkdir(parents=True)
        shutil.copy(str(SRC_DIR / "commands" / "main.sh"), str(lone / "main.sh"))
        env = isolated_env(self.home)
        proc = subprocess.run(
            ["bash", str(lone / "main.sh"), "inspect", "demo", "--yes"],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        combined = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 1, combined)
        self.assertIn("was not found", combined)
        self.assertIn("one folder up", combined)

    def test_main_sh_maps_help_flags(self):
        """source: review: main.sh did not map -h and --help to help"""
        main = SRC_DIR / "commands" / "main.sh"
        env = isolated_env(self.home)
        for flag in ("-h", "--help"):
            proc = subprocess.run(
                ["bash", str(main), flag],
                cwd=str(self.tmp),
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            combined = proc.stdout + proc.stderr
            self.assertEqual(proc.returncode, 0, combined)
            self.assertIn("Commands:", combined)


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


def install_fake_npx(bindir, record):
    bindir.mkdir(parents=True)
    script = bindir / "npx"
    script.write_text(
        "#!/bin/bash\n"
        "printf '%s\\n' \"$*\" >> "
        + shlex.quote(str(record))
        + "\n"
        "exec "
        + shlex.quote(sys.executable)
        + " "
        + shlex.quote(FAKE)
        + ' "$3"\n'
    )
    os.chmod(str(script), 0o755)


def wait_until_gone(pid):
    deadline = time.monotonic() + 5
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    raise AssertionError("pid %s was still running after 5 seconds" % pid)


class InspectTests(IsolatedHomeTest):
    def test_inspect_ok_trims_description_and_measures_schema(self):
        """source: rail: inspect keeps a 200 character description, the schema size, and a token estimate"""
        engine_mod = load_engine(self.mcm_home)
        tools, tokens = engine_mod.inspect_command(
            [sys.executable, FAKE, "ok"], timeout=10
        )
        self.assertEqual(len(tools), 2)
        self.assertEqual(len(tools[0]["description"]), 200)
        expected = len(
            json.dumps(INSPECT_SCHEMA, sort_keys=True, separators=(",", ":"))
        )
        self.assertEqual(tools[0]["schema_size"], expected)
        self.assertEqual(tools[1]["description"], "")
        self.assertEqual(tools[1]["schema_size"], 0)
        self.assertGreater(tokens, 0)

    def test_inspect_paged_collects_every_page(self):
        """source: rail: inspect follows nextCursor and collects every tools page"""
        engine_mod = load_engine(self.mcm_home)
        tools, _tokens = engine_mod.inspect_command(
            [sys.executable, FAKE, "paged"], timeout=10
        )
        self.assertEqual(len(tools), 2)

    def test_inspect_zero_tools(self):
        """source: rail: a server with no tools is a successful empty inspection"""
        engine_mod = load_engine(self.mcm_home)
        self.assertEqual(
            engine_mod.inspect_command([sys.executable, FAKE, "zero"], timeout=10),
            ([], 0),
        )

    def test_inspect_silent_stops_process_group(self):
        """source: rail: a server that does not answer is stopped, including the child it started"""
        engine_mod = load_engine(self.mcm_home)
        pidfile = self.tmp / "child.pid"
        seen = {}

        def watch():
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and "server" not in seen:
                if pidfile.is_file():
                    text = pidfile.read_text().strip()
                    if text:
                        try:
                            child = int(text)
                        except ValueError:
                            time.sleep(0.01)
                            continue
                        seen["child"] = child
                        try:
                            out = subprocess.check_output(
                                ["ps", "-o", "ppid=", "-p", str(child)],
                                text=True,
                                stderr=subprocess.DEVNULL,
                            )
                            ppid = int(out.strip())
                        except (subprocess.CalledProcessError, ValueError, OSError):
                            time.sleep(0.01)
                            continue
                        if ppid > 1:
                            seen["server"] = ppid
                            return
                time.sleep(0.01)

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        started = time.monotonic()
        try:
            with self.assertRaises(engine_mod.InspectError) as ctx:
                engine_mod.inspect_command(
                    [sys.executable, FAKE, "silent", str(pidfile)],
                    timeout=2,
                )
            elapsed = time.monotonic() - started
            self.assertIn("did not answer within 2 seconds", str(ctx.exception))
            self.assertLess(elapsed, 6)
            watcher.join(timeout=1)
            self.assertIn("child", seen)
            self.assertIn("server", seen)
            wait_until_gone(seen["server"])
            wait_until_gone(seen["child"])
        finally:
            for key in ("child", "server"):
                pid = seen.get(key)
                if not pid or pid <= 1:
                    continue
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    continue
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_inspect_returns_on_time_when_a_child_escapes_the_group(self):
        """source: planted fault I2: closing stdout under a blocked reader made inspect hang while an escaped child held the pipe"""
        engine_mod = load_engine(self.mcm_home)
        pidfile = self.tmp / "escape.pid"
        caught = {}

        def run():
            try:
                engine_mod.inspect_command(
                    [sys.executable, FAKE, "escape", str(pidfile)],
                    timeout=2,
                )
            except Exception as exc:
                caught["error"] = exc

        worker = threading.Thread(target=run)
        worker.start()
        try:
            worker.join(timeout=15)
            self.assertFalse(worker.is_alive())
            self.assertIsInstance(caught.get("error"), engine_mod.InspectError)
            self.assertIn("did not answer within 2 seconds", str(caught["error"]))
        finally:
            if pidfile.is_file():
                try:
                    os.kill(int(pidfile.read_text().strip()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_inspect_malformed_line(self):
        """source: a non-JSON stdout line aborted inspect instead of being skipped and counted"""
        engine_mod = load_engine(self.mcm_home)
        notes = []
        tools, _tokens = engine_mod.inspect_command(
            [sys.executable, FAKE, "malformed"], timeout=10, notes=notes
        )
        self.assertEqual(len(tools), 2)
        self.assertEqual(
            notes,
            [
                "the server wrote 1 line(s) to its output that are not JSON-RPC; they were ignored"
            ],
        )

    def test_inspect_nonjson_timeout_names_the_count(self):
        """source: a server that writes only non-JSON lines and never answers timed out without saying those lines were ignored"""
        engine_mod = load_engine(self.mcm_home)
        started = time.monotonic()
        with self.assertRaises(engine_mod.InspectError) as ctx:
            engine_mod.inspect_command(
                [sys.executable, FAKE, "nonjson"],
                timeout=2,
            )
        elapsed = time.monotonic() - started
        message = str(ctx.exception)
        self.assertLess(elapsed, 6)
        self.assertIn("did not answer within 2 seconds", message)
        self.assertTrue(
            message.endswith(" (1 line(s) of its output were not JSON-RPC)"),
            message,
        )

    def test_inspect_cli_prints_nonjson_note(self):
        """source: mcm inspect did not say how many non-JSON-RPC lines it ignored"""
        proc, _record = self._run_inspect(
            ["inspect", "fake-pkg", "--yes", "--", "malformed"]
        )
        combined = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, combined)
        note = (
            "Note: the server wrote 1 line(s) to its output that are not JSON-RPC; they were ignored"
        )
        self.assertIn(note, proc.stdout)
        self.assertGreater(proc.stdout.find(note), proc.stdout.find("schema"))

    def test_inspect_corrupt_index_reports_save_failure(self):
        """source: mcm inspect printed a traceback when the registry index could not be saved"""
        registry = self.mcm_home / "registry"
        registry.mkdir(parents=True)
        (registry / "index.json").write_text("{not json")
        proc, _record = self._run_inspect(
            ["inspect", "fake-pkg", "--yes", "--", "ok"]
        )
        combined = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 1, combined)
        self.assertIn("was inspected but not saved", combined)
        self.assertNotIn("Traceback", combined)

    def test_inspect_tools_list_error(self):
        """source: rail: a tools/list error is reported with the server's message"""
        engine_mod = load_engine(self.mcm_home)
        with self.assertRaises(engine_mod.InspectError) as ctx:
            engine_mod.inspect_command([sys.executable, FAKE, "error"], timeout=10)
        self.assertIn("no tools here", str(ctx.exception))

    def test_inspect_exit_includes_stderr(self):
        """source: rail: a server that exits first reports its exit code and stderr"""
        engine_mod = load_engine(self.mcm_home)
        with self.assertRaises(engine_mod.InspectError) as ctx:
            engine_mod.inspect_command([sys.executable, FAKE, "exit"], timeout=10)
        message = str(ctx.exception)
        self.assertIn("exit code 3", message)
        self.assertIn("boom", message)

    def test_inspect_strips_hostile_stderr(self):
        """source: review: a failed inspect printed the server stderr unsanitized"""
        engine_mod = load_engine(self.mcm_home)
        with self.assertRaises(engine_mod.InspectError) as ctx:
            engine_mod.inspect_command(
                [sys.executable, FAKE, "stderr_controls"], timeout=10
            )
        message = str(ctx.exception)
        self.assertIn("red", message)
        self.assertIn("red |", message)
        for ch in message:
            code = ord(ch)
            self.assertGreaterEqual(code, 32)
            self.assertNotEqual(ch, "\u001b")
            self.assertFalse(0x80 <= code <= 0x9F)

    def test_inspect_ignores_an_answer_with_another_id(self):
        """source: an answer with another id was accepted as the tools list"""
        engine_mod = load_engine(self.mcm_home)
        try:
            ok_tools, _ok_tokens = engine_mod.inspect_command(
                [sys.executable, FAKE, "ok"], timeout=10
            )
        except Exception as exc:
            self.fail("ok mode inspect raised: %s" % exc)
        try:
            tools, _tokens = engine_mod.inspect_command(
                [sys.executable, FAKE, "stale_id"], timeout=10
            )
        except Exception as exc:
            self.fail("an answer with another id aborted inspect: %s" % exc)
        names = [tool["name"] for tool in tools]
        ok_names = [tool["name"] for tool in ok_tools]
        self.assertEqual(names, ok_names)
        self.assertNotIn("wrong_tool", names)

    def test_inspect_skips_request_with_the_awaited_id(self):
        """source: review: a server-sent request whose id equals the awaited id was taken as the answer"""
        engine_mod = load_engine(self.mcm_home)
        try:
            ok_tools, _ok_tokens = engine_mod.inspect_command(
                [sys.executable, FAKE, "ok"], timeout=10
            )
        except Exception as exc:
            self.fail("ok mode inspect raised: %s" % exc)
        try:
            tools, _tokens = engine_mod.inspect_command(
                [sys.executable, FAKE, "same_id"], timeout=10
            )
        except engine_mod.InspectError as exc:
            self.fail("a server request was taken as the answer: %s" % exc)
        self.assertEqual(len(tools), len(ok_tools))
        self.assertEqual(tools[0]["name"], "read_file")

    def test_inspect_env_is_minimal_and_folder_removed(self):
        """source: rail: the server receives only PATH, HOME, USER, LANG and TMPDIR, and its folder is removed"""
        engine_mod = load_engine(self.mcm_home)
        old_exa = os.environ.get("EXA_API_KEY")
        old_github = os.environ.get("GITHUB_TOKEN")
        os.environ["EXA_API_KEY"] = "test-exa"
        os.environ["GITHUB_TOKEN"] = "test-github"
        report = self.tmp / "env-report.json"
        try:
            _tools, _tokens = engine_mod.inspect_command(
                [sys.executable, FAKE, "env", str(report)], timeout=10
            )
        finally:
            if old_exa is None:
                os.environ.pop("EXA_API_KEY", None)
            else:
                os.environ["EXA_API_KEY"] = old_exa
            if old_github is None:
                os.environ.pop("GITHUB_TOKEN", None)
            else:
                os.environ["GITHUB_TOKEN"] = old_github
        with open(report) as handle:
            info = json.loads(handle.read())
        keys = info["keys"]
        self.assertNotIn("EXA_API_KEY", keys)
        self.assertNotIn("GITHUB_TOKEN", keys)
        self.assertIn("PATH", keys)
        self.assertNotEqual(info["cwd"], os.getcwd())
        self.assertFalse(os.path.exists(info["cwd"]))

    def test_inspect_ignores_server_noise(self):
        """source: rail: notifications and requests from the server are ignored and never answered"""
        engine_mod = load_engine(self.mcm_home)
        try:
            tools, _tokens = engine_mod.inspect_command(
                [sys.executable, FAKE, "noise"], timeout=10
            )
        except engine_mod.InspectError as exc:
            self.fail("a server message was taken as an answer: %s" % exc)
        self.assertEqual(len(tools), 2)

    def test_inspect_strips_control_characters(self):
        """source: rail: control characters are removed from saved tool names and descriptions"""
        engine_mod = load_engine(self.mcm_home)
        tools, _tokens = engine_mod.inspect_command(
            [sys.executable, FAKE, "ctrl"], timeout=10
        )
        self.assertGreaterEqual(len(tools), 1)
        for tool in tools:
            for text in (tool["name"], tool["description"]):
                for ch in text:
                    self.assertGreaterEqual(ord(ch), 32)
                    self.assertNotEqual(ord(ch), 127)

    def _run_inspect(self, args):
        bindir = self.tmp / "bin"
        record = self.tmp / "npx-record.txt"
        install_fake_npx(bindir, record)
        env = isolated_env(self.home)
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
        proc = subprocess.run(
            [sys.executable, str(SRC_DIR / "mcm_engine.py")] + args,
            cwd=str(self.tmp),
            env=env,
            input="",
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc, record

    def test_inspect_cli_without_yes_does_not_start(self):
        """source: rail: without --yes and without a terminal, the server is not started"""
        proc, record = self._run_inspect(["inspect", "fake-pkg"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn(
            "This runs fake-pkg's own code on your machine, the same as installing it.",
            proc.stdout,
        )
        self.assertIn(
            "Not started. Run it again with --yes to continue.",
            proc.stdout,
        )
        self.assertFalse(record.exists())
        self.assertFalse((self.mcm_home / "registry" / "index.json").exists())

    def test_inspect_cli_yes_saves_names_and_schema_sizes(self):
        """source: rail: --yes saves tool names, short descriptions and schema sizes, not full schemas"""
        proc, _record = self._run_inspect(
            ["inspect", "fake-pkg", "--yes", "--", "ok"]
        )
        self.assertEqual(
            proc.returncode, 0, proc.stdout + "\n" + proc.stderr
        )
        self.assertIn("fake-pkg: 2 tools", proc.stdout)
        index_path = self.mcm_home / "registry" / "index.json"
        with open(str(index_path)) as handle:
            index = json.load(handle)
        entry = [item for item in index["mcps"] if item["name"] == "fake-pkg"][0]
        self.assertTrue(entry["inspected"])
        self.assertEqual(entry["tool_count"], 2)
        meta_path = self.mcm_home / "registry" / "fake-pkg" / "metadata.json"
        text = meta_path.read_text()
        self.assertNotIn("inputSchema", text)
        self.assertNotIn("properties", text)

    def test_inspect_cli_rejects_invalid_package_name(self):
        """source: rail: a name that is not an npm package never starts a server"""
        proc, record = self._run_inspect(["inspect", "../evil", "--yes"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not an npm package name", proc.stdout + proc.stderr)
        self.assertFalse(record.exists())

    def _write_status_index(self):
        self.mcm_home.mkdir(parents=True)
        registry = self.mcm_home / "registry"
        registry.mkdir()
        index = {
            "mcps": [
                {
                    "name": "a-server",
                    "source": "npm",
                    "tool_count": 2,
                    "format": "cli",
                    "discovered_at": "x",
                    "inspected": True,
                    "context_tokens": 150,
                },
                {
                    "name": "b-server",
                    "source": "npm",
                    "tool_count": 1,
                    "format": "cli",
                    "discovered_at": "x",
                },
            ]
        }
        (registry / "index.json").write_text(json.dumps(index))

    def test_status_shows_real_counts_only_when_inspected(self):
        """source: rail: status shows real counts for inspected servers and not inspected for the rest"""
        self._write_status_index()
        env = isolated_env(self.home)
        proc = subprocess.run(
            ["bash", str(SRC_DIR / "commands" / "status.sh")],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        lines = proc.stdout.splitlines()
        a_line = [line for line in lines if "a-server" in line][0]
        b_line = [line for line in lines if "b-server" in line][0]
        self.assertIn("2 tools", a_line)
        self.assertIn("~150 tokens", a_line)
        self.assertIn("not inspected", b_line)
        self.assertIn("Inspected 1 of 2", proc.stdout)

    def test_validate_marks_uninspected_servers(self):
        """source: rail: validate shows not inspected and does not claim servers were validated"""
        self._write_status_index()
        env = isolated_env(self.home)
        proc = subprocess.run(
            ["bash", str(SRC_DIR / "commands" / "validate.sh")],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        b_line = [
            line for line in proc.stdout.splitlines() if "b-server" in line
        ][0]
        self.assertIn("not inspected", b_line)
        self.assertNotIn("validated", proc.stdout)
        self.assertNotIn("validated", proc.stderr)

    def test_discover_from_npm_keeps_requested_package_name(self):
        """source: rail: discover keeps the npm package name the user asked for"""
        engine_mod = load_engine(self.mcm_home)
        npm_doc = {
            "name": "servers",
            "dist-tags": {"latest": "1.0.0"},
            "versions": {
                "1.0.0": {
                    "description": "d",
                    "repository": {
                        "url": "git+https://github.com/owner/servers.git"
                    },
                }
            },
        }

        def fake_http(method, url, headers=None, json_body=None, timeout=30):
            if "registry.npmjs.org" in url:
                return (200, json.dumps(npm_doc))
            if "api.github.com/repos/owner/servers" in url:
                return (
                    200,
                    json.dumps(
                        {
                            "name": "servers",
                            "html_url": "https://github.com/owner/servers",
                            "description": "d",
                        }
                    ),
                )
            if "raw.githubusercontent.com" in url:
                return (404, "")
            return (404, "")

        engine = engine_mod.MCMEngine()
        with patch.object(engine_mod, "http_request", side_effect=fake_http):
            metadata = engine.discover_from_npm(
                {
                    "identifier": "@scope/server-x",
                    "type": "npm_package",
                    "original": "@scope/server-x",
                }
            )
        self.assertEqual(metadata.name, "@scope/server-x")
        self.assertFalse(metadata.inspected)

    def test_discover_does_not_start_a_process(self):
        """source: rail: a server starts only when the person types inspect for a named package"""
        engine_mod = load_engine(self.mcm_home)
        list_file = self.tmp / "one.txt"
        list_file.write_text("demo-mcp\n")
        npm_doc = {
            "name": "demo-mcp",
            "dist-tags": {"latest": "1.0.0"},
            "versions": {
                "1.0.0": {
                    "description": "d",
                    "repository": {"url": "https://gitlab.com/example/demo-mcp"},
                }
            },
        }
        popen = Mock()
        with patch.object(engine_mod.subprocess, "Popen", popen), patch.object(
            engine_mod, "http_request", return_value=(200, json.dumps(npm_doc))
        ), patch.object(engine_mod.time, "sleep"), patch.object(
            engine_mod.sys,
            "argv",
            ["mcm_engine.py", "discover", str(list_file)],
        ):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                engine_mod.main()
        popen.assert_not_called()

    def test_save_metadata_keeps_inspected_entry(self):
        """source: rail: saving a package again without inspection keeps the inspected tool count"""
        engine_mod = load_engine(self.mcm_home)
        engine = engine_mod.MCMEngine()
        inspected = engine_mod.MCPMetadata(
            name="demo-mcp",
            source="npm",
            url="https://www.npmjs.com/package/demo-mcp",
            description="",
            tools=[
                {"name": "a", "description": "", "schema_size": 1},
                {"name": "b", "description": "", "schema_size": 2},
            ],
            tool_count=2,
            complexity_score=2.0,
            context_cost_estimate=10,
            dependencies=[],
            credentials_needed=[],
            discovered_at="2020-01-01T00:00:00Z",
            format="cli",
            inspected=True,
            inspected_at="2020-01-01T00:00:00Z",
        )
        plain = engine_mod.MCPMetadata(
            name="demo-mcp",
            source="npm",
            url="https://www.npmjs.com/package/demo-mcp",
            description="later",
            tools=[],
            tool_count=0,
            complexity_score=0.0,
            context_cost_estimate=0,
            dependencies=[],
            credentials_needed=[],
            discovered_at="2021-01-01T00:00:00Z",
            format="direct",
        )
        engine.save_metadata(inspected)
        meta_path = self.mcm_home / "registry" / "demo-mcp" / "metadata.json"
        before = meta_path.read_text()
        engine.save_metadata(plain)
        self.assertEqual(meta_path.read_text(), before)
        index = json.loads((self.mcm_home / "registry" / "index.json").read_text())
        entry = [item for item in index["mcps"] if item["name"] == "demo-mcp"][0]
        self.assertTrue(entry["inspected"])
        self.assertEqual(entry["tool_count"], 2)


class RegistryIndexTests(IsolatedHomeTest):
    def _metadata(self, engine_mod, name="demo-mcp"):
        return engine_mod.MCPMetadata(
            name=name,
            source="npm",
            url="https://www.npmjs.com/package/" + name,
            description="",
            tools=[],
            tool_count=0,
            complexity_score=0.0,
            context_cost_estimate=0,
            dependencies=[],
            credentials_needed=[],
            discovered_at="2020-01-01T00:00:00Z",
            format="direct",
        )

    def test_corrupt_index_is_reported_without_traceback(self):
        """source: review: a corrupt registry index raised a traceback in status and validate"""
        engine_mod = load_engine(self.mcm_home)
        engine = engine_mod.MCMEngine()
        index_path = self.mcm_home / "registry" / "index.json"
        index_path.write_text("{not json")
        with self.assertRaises(ValueError) as ctx:
            engine.save_metadata(self._metadata(engine_mod))
        self.assertEqual(
            str(ctx.exception),
            "the registry index is not valid JSON: %s" % index_path,
        )

        env = isolated_env(self.home)
        expected = (
            "The registry index is not valid JSON: %s. Move it aside and run discover again."
            % index_path
        )
        for script in ("status.sh", "validate.sh"):
            proc = subprocess.run(
                ["bash", str(SRC_DIR / "commands" / script)],
                cwd=str(self.tmp),
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            combined = proc.stdout + proc.stderr
            self.assertEqual(proc.returncode, 1, combined)
            self.assertIn(expected, combined)
            self.assertIn("is not valid JSON", combined)
            self.assertNotIn("Traceback", combined)

    def test_index_without_mcps_is_accepted(self):
        """source: review: an index without mcps was not accepted"""
        engine_mod = load_engine(self.mcm_home)
        engine = engine_mod.MCMEngine()
        index_path = self.mcm_home / "registry" / "index.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("{}")
        engine.save_metadata(self._metadata(engine_mod))
        saved = json.loads(index_path.read_text())
        self.assertEqual([item["name"] for item in saved["mcps"]], ["demo-mcp"])

    def test_save_metadata_leaves_no_temp_file(self):
        """source: review: the registry index was rewritten in place"""
        engine_mod = load_engine(self.mcm_home)
        engine = engine_mod.MCMEngine()
        engine.save_metadata(self._metadata(engine_mod))
        registry = self.mcm_home / "registry"
        files = sorted(
            path.relative_to(registry).as_posix()
            for path in registry.rglob("*")
            if path.is_file()
        )
        self.assertEqual(files, ["demo-mcp/metadata.json", "index.json"])
        parsed = json.loads((registry / "index.json").read_text())
        self.assertEqual(parsed["mcps"][0]["name"], "demo-mcp")

    def test_failed_index_write_keeps_the_old_index_and_no_temp_file(self):
        """source: a failed registry index write replaced the old index or left a temp file"""
        engine_mod = load_engine(self.mcm_home)
        engine = engine_mod.MCMEngine()
        engine.save_metadata(self._metadata(engine_mod, "kept-mcp"))
        index_path = self.mcm_home / "registry" / "index.json"
        recorded = index_path.read_bytes()
        real_dump = engine_mod.json.dump

        def failing_dump(payload, handle, *args, **kwargs):
            if isinstance(payload, dict) and "mcps" in payload:
                handle.write("{")
                raise OSError("disk full")
            return real_dump(payload, handle, *args, **kwargs)

        with patch.object(engine_mod.json, "dump", failing_dump):
            with self.assertRaises(OSError):
                engine.save_metadata(self._metadata(engine_mod, "other-mcp"))
        self.assertEqual(index_path.read_bytes(), recorded)
        registry = self.mcm_home / "registry"
        leftover = []
        for dirpath, _dirnames, filenames in os.walk(str(registry)):
            for name in filenames:
                if name.startswith(".mcm-tmp-"):
                    leftover.append(os.path.join(dirpath, name))
        self.assertEqual(leftover, [])


if __name__ == "__main__":
    unittest.main()
