#!/usr/bin/env python3
"""Fake MCP server for inspect tests. Mode is argv[1]. Standard library only."""

import json
import os
import subprocess
import sys

SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
}


def write_message(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def read_message():
    line = sys.stdin.readline()
    if line == "":
        return None
    return json.loads(line)


def initialize_result(mid):
    write_message(
        {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "serverInfo": {"name": "fake", "version": "0.0.0"},
            },
        }
    )


def ok_tools(mode):
    if mode == "ctrl":
        first = {
            "name": "bad\u001b[31mname",
            "description": "\u0007bell",
            "inputSchema": SCHEMA,
        }
    elif mode == "env":
        first = {
            "name": "env",
            "description": "reports its environment",
            "inputSchema": SCHEMA,
        }
    else:
        first = {
            "name": "read_file",
            "description": "d" * 300,
            "inputSchema": SCHEMA,
        }
    second = {"name": "bare"}
    return [first, second]


def serve_ok(mode):
    tools = ok_tools(mode)
    while True:
        msg = read_message()
        if msg is None:
            return
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            initialize_result(mid)
        elif method == "tools/list":
            write_message(
                {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
            )


def serve_paged():
    while True:
        msg = read_message()
        if msg is None:
            return
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            initialize_result(mid)
        elif method == "tools/list":
            params = msg.get("params")
            if not isinstance(params, dict):
                params = {}
            if params.get("cursor") == "p2":
                result = {"tools": [{"name": "page-two"}]}
            else:
                result = {
                    "tools": [{"name": "page-one"}],
                    "nextCursor": "p2",
                }
            write_message({"jsonrpc": "2.0", "id": mid, "result": result})


def serve_zero():
    while True:
        msg = read_message()
        if msg is None:
            return
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            initialize_result(mid)
        elif method == "tools/list":
            write_message(
                {"jsonrpc": "2.0", "id": mid, "result": {"tools": []}}
            )


def serve_silent(pid_path):
    child = subprocess.Popen(["sleep", "600"])
    with open(pid_path, "w") as handle:
        handle.write(str(child.pid))
    while True:
        line = sys.stdin.readline()
        if line == "":
            return


def serve_escape(pid_path):
    child = subprocess.Popen(["sleep", "600"], start_new_session=True)
    with open(pid_path, "w") as handle:
        handle.write(str(child.pid))
    while True:
        line = sys.stdin.readline()
        if line == "":
            return


def serve_malformed():
    while True:
        msg = read_message()
        if msg is None:
            return
        if msg.get("method") == "initialize":
            sys.stdout.write("this is not json\n")
            sys.stdout.flush()
            return


def serve_error():
    while True:
        msg = read_message()
        if msg is None:
            return
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            initialize_result(mid)
        elif method == "tools/list":
            write_message(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "error": {"code": -32601, "message": "no tools here"},
                }
            )


def serve_exit():
    sys.stderr.write("boom")
    sys.stderr.flush()
    raise SystemExit(3)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(2)
    mode = sys.argv[1]
    if mode == "exit":
        serve_exit()
    elif mode == "silent":
        serve_silent(sys.argv[2])
    elif mode == "escape":
        serve_escape(sys.argv[2])
    elif mode == "malformed":
        serve_malformed()
    elif mode == "error":
        serve_error()
    elif mode == "paged":
        serve_paged()
    elif mode == "zero":
        serve_zero()
    elif mode == "noise":
        write_message(
            {"jsonrpc": "2.0", "method": "notifications/message"}
        )
        write_message({"jsonrpc": "2.0", "id": "s1", "method": "ping"})
        serve_ok("ok")
    elif mode == "env":
        report_path = sys.argv[2]
        with open(report_path, "w") as handle:
            handle.write(
                json.dumps({"cwd": os.getcwd(), "keys": sorted(os.environ)})
            )
        serve_ok(mode)
    elif mode in ("ok", "ctrl"):
        serve_ok(mode)
    else:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
