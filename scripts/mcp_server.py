#!/usr/bin/env python3
"""Register the status402 MCP server in Claude Code and sign in to it.

  mcp_server.py ensure [--server NAME] [--url URL] [--repo DIR]

ensure  registers the server for all projects (user scope) if it isn't there,
        then runs `claude mcp login`, which opens your browser to sign in.
        status402 supports OAuth dynamic client registration, so there is no
        token to copy; Claude Code registers itself as a client and keeps the
        credentials. A registered server that still needs authentication gets
        the same sign-in. A user-scope entry with another URL is replaced.

Options:
  --server NAME   name to register the server under (default: liz)
  --url URL       MCP endpoint
  --repo DIR      the checkout; records there that install.sh registered the
                  server, so that uninstalling removes it again

install.sh runs this for the router, and risk_hook.py imports it.
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from settings_hooks import SettingsError  # noqa: E402

HOME = pathlib.Path.home()
DEFAULT_MCP_URL = "https://platform.status402.io/mcp/paid/veryliz/scope/dev/gozcu"


def interactive():
    return sys.stdin.isatty()


def terminal():
    """The terminal's own device (such as /dev/ttys003), or None. Under `curl | bash`
    stdin is /dev/tty, which macOS can't poll, and the claude CLI crashes on it."""
    for fd in (0, 1, 2):
        try:
            name = os.ttyname(fd)
        except OSError:
            continue
        if name != "/dev/tty":
            return name
    return None


def user_servers():
    """The user-scope servers in ~/.claude.json, {name: entry}."""
    try:
        with open(HOME / ".claude.json", encoding="utf-8") as f:
            servers = json.load(f).get("mcpServers")
    except (OSError, ValueError, AttributeError):
        servers = None
    return servers if isinstance(servers, dict) else {}


def registered_servers():
    """(user-scope names in ~/.claude.json, lines of `claude mcp list`)."""
    names = set(user_servers())
    lines = []
    if shutil.which("claude"):
        # Run from $HOME so servers scoped to the current project don't count:
        # the hooks are in user settings and fire in every project.
        try:
            result = subprocess.run(["claude", "mcp", "list"], cwd=HOME, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                lines = result.stdout.splitlines()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return names, lines


def server_state(server, registered):
    """connected, needs-auth, or None if the server isn't registered."""
    names, lines = registered
    for line in lines:
        if line.startswith(f"{server}: "):
            return "needs-auth" if "Needs authentication" in line else "connected"
    return "connected" if server in names else None


def run_claude(*command, **options):
    """Runs `claude mcp ...` with no stdin unless one is given; see terminal()."""
    options.setdefault("stdin", subprocess.DEVNULL)
    try:
        return subprocess.run(["claude", "mcp", *command], cwd=HOME, timeout=600, **options).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


def register_server(server, url, replace=False):
    """User scope, with no credentials: Claude Code finds the OAuth endpoints from the URL."""
    wanted = json.dumps({"type": "http", "url": url})
    add = f"claude mcp add-json {server} '{wanted}' --scope user"
    if not shutil.which("claude"):
        remove = f"  claude mcp remove {server} --scope user\n" if replace else ""
        raise SettingsError(f"the claude CLI isn't on your PATH, so the MCP server can't be registered. Run:\n"
                            f"{remove}  {add}\n  claude mcp login {server}\nthen re-run this.")
    if replace:
        run_claude("remove", server, "--scope", "user", capture_output=True)
    if run_claude("add-json", server, wanted, "--scope", "user", capture_output=True):
        raise SettingsError(f"could not register the MCP server '{server}'; try: {add}")
    print(f"    MCP server '{server}': registered for all projects ({url})")


def login(server):
    """Sign in through Claude Code, which registers itself as an OAuth client and stores the credentials."""
    retry = f"Run `claude mcp login {server}` (or /mcp in Claude Code), then re-run this."
    device = terminal() if interactive() else None
    if not device:
        raise SettingsError(f"the MCP server '{server}' needs you to sign in, which takes a terminal. {retry}")
    print(f"    MCP server '{server}': signing in through your browser")
    sys.stdout.flush()
    with open(device, "rb+", buffering=0) as tty:
        if run_claude("login", server, stdin=tty):
            raise SettingsError(f"sign-in to the MCP server '{server}' didn't finish. {retry}")


def cmd_ensure(args):
    entry = user_servers().get(args.server)
    stale = entry is not None and (not isinstance(entry, dict) or entry.get("url") != args.url)
    state = None if stale else server_state(args.server, registered_servers())
    if state:
        print(f"    MCP server '{args.server}': already registered")
    else:
        if stale:
            print(f"    MCP server '{args.server}': replacing your existing user-scope entry with this one")
        register_server(args.server, args.url, replace=stale)
        if args.repo:
            subprocess.run(["git", "-C", str(args.repo), "config", "claude-agents.registered-server",
                            args.server], check=False)
    if state != "connected":
        login(args.server)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["ensure"])
    parser.add_argument("--server", default="liz")
    parser.add_argument("--url", default=os.environ.get("STATUS402_MCP_URL") or DEFAULT_MCP_URL)
    parser.add_argument("--repo", type=pathlib.Path)
    args = parser.parse_args()
    try:
        cmd_ensure(args)
    except SettingsError as exc:
        print(f"mcp server: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nmcp server: cancelled", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
