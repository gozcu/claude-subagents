#!/usr/bin/env python3
"""Tests for scripts/mcp_server.py.

Runs against temporary folders with a fake `claude` CLI; nothing outside them is touched.
Usage: python3 scripts/test_mcp_server.py
"""
import json
import os
import pathlib
import pty
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "mcp_server.py"
URL = "https://platform.status402.io/mcp/paid/veryliz/scope/dev/gozcu"
ENTRY = {"type": "http", "url": URL}
ADD = f"mcp add-json liz {json.dumps(ENTRY)} --scope user"
CONNECTED = f"liz: {URL} (HTTP) - ✔ Connected\n"
UNAUTHED = f"liz: {URL} (HTTP) - ! Needs authentication\n"
FAKE_CLAUDE = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_CLAUDE_LOG"
if [ -t 0 ]; then printf '%s\\n' "$2" >> "$FAKE_CLAUDE_LOG.tty"; fi
if [ "$1 $2" = "mcp list" ]; then cat "$FAKE_CLAUDE_LIST"; fi
if [ "$1 $2" = "mcp login" ]; then exit "${FAKE_LOGIN_EXIT:-0}"; fi
"""
FAILURES = []


def check(label, condition, detail=""):
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


class Sandbox:
    """A throwaway $HOME with a fake `claude` that lists the servers in `listing`."""

    def __init__(self):
        self.home = pathlib.Path(tempfile.mkdtemp(prefix="mcp-server-test-"))
        self.log = self.home / "claude.log"
        self.listing = self.home / "claude.list"
        self.listing.write_text("", encoding="utf-8")
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "claude"
        fake.write_text(FAKE_CLAUDE)
        fake.chmod(0o755)

    def register(self, entry):
        (self.home / ".claude.json").write_text(json.dumps({"mcpServers": {"liz": entry}}))

    def run(self, *extra, tty=False, claude=True, **env):
        """tty=True gives the script a terminal on stdin, as when a person runs it."""
        path = f"{self.home / 'bin'}:/usr/bin:/bin" if claude else "/usr/bin:/bin"
        environ = {"HOME": str(self.home), "PATH": path,
                   "FAKE_CLAUDE_LOG": str(self.log), "FAKE_CLAUDE_LIST": str(self.listing), **env}
        master, slave = pty.openpty() if tty else (None, subprocess.DEVNULL)
        try:
            return subprocess.run([sys.executable, str(SCRIPT), "ensure", *extra], env=environ,
                                  stdin=slave, capture_output=True, text=True, timeout=30)
        finally:
            if tty:
                os.close(master)
                os.close(slave)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def cleanup(self):
        shutil.rmtree(self.home)


def scenario(fn):
    sandbox = Sandbox()
    try:
        fn(sandbox)
    except Exception as exc:
        FAILURES.append(f"{fn.__name__}: crashed: {exc!r}")
    finally:
        sandbox.cleanup()
    return fn


@scenario
def registers_and_signs_in(s):
    repo = s.home / "repo"
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    r = s.run("--repo", str(repo), tty=True)
    check("ensure exits 0", r.returncode == 0, r.stderr)
    check("server is registered without credentials, then signed in",
          s.calls() == ["mcp list", ADD, "mcp login liz"], str(s.calls()))
    check("no token file is written", not (s.home / ".config").exists())
    check("only the sign-in is given the terminal",
          pathlib.Path(f"{s.log}.tty").read_text().split() == ["login"])
    recorded = subprocess.run(["git", "-C", str(repo), "config", "--get", "claude-agents.registered-server"],
                              capture_output=True, text=True).stdout.strip()
    check("the checkout records the registration", recorded == "liz", recorded)


@scenario
def replaces_another_url(s):
    s.register({"type": "http", "url": "https://example.com/mcp"})
    s.run(tty=True)
    check("an entry with another URL is replaced", s.calls()[:2] == ["mcp remove liz --scope user", ADD],
          str(s.calls()))


@scenario
def leaves_a_signed_in_server_alone(s):
    s.register(ENTRY)
    s.listing.write_text(CONNECTED, encoding="utf-8")
    r = s.run()
    check("ensure exits 0 without a terminal", r.returncode == 0, r.stderr)
    check("nothing is registered or signed in", s.calls() == ["mcp list"], str(s.calls()))
    check("reports no change", "already registered" in r.stdout, r.stdout)


@scenario
def signs_in_to_an_unauthenticated_server(s):
    s.register(ENTRY)
    s.listing.write_text(UNAUTHED, encoding="utf-8")
    r = s.run(tty=True)
    check("ensure exits 0", r.returncode == 0, r.stderr)
    check("signs in without re-registering", s.calls() == ["mcp list", "mcp login liz"], str(s.calls()))


@scenario
def reports_a_sign_in_that_is_still_needed(s):
    r = s.run()
    check("fails without a terminal", r.returncode == 1 and "claude mcp login liz" in r.stderr, r.stderr)
    check("the server is still registered", ADD in s.calls(), str(s.calls()))
    r = s.run(tty=True, FAKE_LOGIN_EXIT="1")
    check("fails when the sign-in fails", r.returncode == 1 and "claude mcp login liz" in r.stderr, r.stderr)


@scenario
def needs_the_claude_cli(s):
    s.register({"type": "http", "url": "https://example.com/mcp"})
    r = s.run(tty=True, claude=False)
    check("fails without the claude CLI", r.returncode == 1, r.stderr)
    check("prints the commands to run by hand",
          all(c in r.stderr for c in ("claude mcp remove liz", "claude mcp add-json liz", "claude mcp login liz")),
          r.stderr)


def main():
    for failure in FAILURES:
        print(f"FAIL  {failure}")
    print("all MCP server checks passed" if not FAILURES else f"{len(FAILURES)} MCP server check(s) failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
